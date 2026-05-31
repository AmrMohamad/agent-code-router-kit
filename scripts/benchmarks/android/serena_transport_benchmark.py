#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import process_state_probe as process_probe  # noqa: E402
import serena_project_server_probe as serena_probe  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def process_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    before_counts = dict(before.get("counts", {}))
    after_counts = dict(after.get("counts", {}))
    keys = sorted(set(before_counts) | set(after_counts))
    return {key: int(after_counts.get(key, 0)) - int(before_counts.get(key, 0)) for key in keys}


def transport_error_seen(rows: list[dict[str, Any]]) -> bool:
    needles = ["transport closed", "connection refused", "connection reset", "broken pipe"]
    for row in rows:
        text = f"{row.get('stdout', '')}\n{row.get('stderr', '')}".lower()
        if any(needle in text for needle in needles):
            return True
    return False


def build_transport_assertions(
    rows: list[dict[str, Any]],
    before_process: dict[str, Any],
    after_process: dict[str, Any],
    expected_repeats: int,
    max_serena_growth: int,
) -> dict[str, Any]:
    payload = serena_probe.build_assertions(rows, expected_repeats=expected_repeats)
    assertions = list(payload["assertions"])
    delta = process_delta(before_process, after_process)
    assertions.append(
        {
            "status": "pass" if not transport_error_seen(rows) else "fail",
            "check": "transport_error_absent",
            "message": "No transport closed / reset / refused marker appeared in ProjectServer responses.",
        }
    )
    serena_growth = delta.get("serena_mcp", 0)
    assertions.append(
        {
            "status": "pass" if serena_growth <= max_serena_growth else "fail",
            "check": "serena_process_growth",
            "message": f"serena_mcp_delta={serena_growth} max={max_serena_growth}",
        }
    )
    kotlin_growth = delta.get("kotlin_lsp", 0)
    assertions.append(
        {
            "status": "pass" if kotlin_growth <= 1 else "warn",
            "check": "kotlin_lsp_process_growth",
            "message": f"kotlin_lsp_delta={kotlin_growth}",
        }
    )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions, "process_delta": delta}


def run(args: argparse.Namespace, cases: list[dict[str, str]]) -> int:
    output = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    before_process = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=args.target_project_path or None,
        expected_serena_mcp_count=args.expected_serena_mcp_count,
        allow_http_serena_server=args.allow_http_serena_server,
    )
    rows: list[dict[str, Any]] = []
    server = serena_probe.start_server(args.port, args.startup_timeout)
    try:
        for _ in range(args.warmups):
            for row in cases:
                serena_probe.execute(row, args.port, args.timeout)
        for pass_index in range(1, args.repeats + 1):
            for row in cases:
                result = serena_probe.execute(row, args.port, args.timeout)
                base = serena_probe.safe_name(f"{row['repo']}_{row['case_id']}_pass{pass_index}")
                stdout_path = raw_dir / f"{base}.stdout"
                stderr_path = raw_dir / f"{base}.stderr"
                stdout_path.write_text(str(result["stdout"]))
                stderr_path.write_text(str(result["stderr"]))
                rows.append(
                    {
                        "pass_index": pass_index,
                        "repo": row["repo"],
                        "case_id": row["case_id"],
                        "project": row["project"],
                        "tool_name": row["tool_name"],
                        "expected_status": row["expected_status"],
                        "min_byte_count": int(row["min_byte_count"]),
                        "purpose": row["purpose"],
                        "status": result["status"],
                        "timed_out": result["timed_out"],
                        "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                        "line_count": result["line_count"],
                        "byte_count": result["byte_count"],
                        "estimated_tokens": result["estimated_tokens"],
                        "stdout_path": str(stdout_path),
                        "stderr_path": str(stderr_path),
                        "stdout": result["stdout"],
                        "stderr": result["stderr"],
                    }
                )
    finally:
        serena_probe.stop_server(server)
    after_process = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=args.target_project_path or None,
        expected_serena_mcp_count=args.expected_serena_mcp_count,
        allow_http_serena_server=args.allow_http_serena_server,
    )

    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / f"android-serena-transport-{run_id}.tsv"
    summary_path = output / f"android-serena-transport-summary-{run_id}.json"
    assertions_path = output / f"android-serena-transport-assertions-{run_id}.json"
    persisted_rows = [{key: value for key, value in row.items() if key not in {"stdout", "stderr"}} for row in rows]
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=list(persisted_rows[0].keys()))
        writer.writeheader()
        writer.writerows(persisted_rows)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), []).append(row)
    case_summaries = []
    for case_id, group in sorted(grouped.items()):
        walls = [float(row["wall_seconds"]) for row in group]
        case_summaries.append(
            {
                "case_id": case_id,
                "tool_name": group[-1]["tool_name"],
                "statuses": sorted({str(row["status"]) for row in group}),
                "best_wall_seconds": min(walls),
                "median_wall_seconds": median(walls),
                "avg_wall_seconds": mean(walls),
                "measured_pass_count": len(group),
                "last_byte_count": int(group[-1]["byte_count"]),
                "last_estimated_tokens": int(group[-1]["estimated_tokens"]),
            }
        )
    assertion_payload = build_transport_assertions(
        rows,
        before_process,
        after_process,
        expected_repeats=args.repeats,
        max_serena_growth=args.max_serena_growth,
    )
    summary = {
        "schema": "agent-code-router-kit.android-serena-transport.v1",
        "date_utc": utc_now(),
        "mode": "project-server-fallback",
        "case_count": len(cases),
        "measured_rows": len(rows),
        "repeats": args.repeats,
        "warmups": args.warmups,
        "process_delta": assertion_payload["process_delta"],
        "before_process_status": before_process["status"],
        "after_process_status": after_process["status"],
        "cases": case_summaries,
        "rows_path": str(rows_path),
        "raw_dir": str(raw_dir),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertion_payload, indent=2, sort_keys=True) + "\n")
    counts = assertion_payload["summary"]
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(
        "Assertions: "
        f"pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}; "
        f"process_delta={assertion_payload['process_delta']}"
    )
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark stable Serena ProjectServer transport stability.")
    parser.add_argument("--cases", default="benchmarks/android/serena-transport.sample-b2b.tsv")
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--output", default="results/android/serena-transport")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--port", type=int, default=24602)
    parser.add_argument("--target-project-path", default="")
    parser.add_argument("--expected-serena-mcp-count", type=int, default=1)
    parser.add_argument("--allow-http-serena-server", action="store_true")
    parser.add_argument("--max-serena-growth", type=int, default=0)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.repeats < 1 or args.warmups < 0:
        parser.error("--repeats must be >= 1 and --warmups must be >= 0")
    if args.timeout <= 0 or args.startup_timeout <= 0:
        parser.error("timeouts must be > 0")
    cases = serena_probe.load_cases(Path(args.cases))
    repos = serena_probe.parse_repo_args(args.repo)
    errors = serena_probe.validate(cases, repos, require_repos=args.run)
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases")
    if args.run:
        return run(args, cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
