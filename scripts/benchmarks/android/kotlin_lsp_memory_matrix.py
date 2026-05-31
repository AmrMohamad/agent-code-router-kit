#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterator


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import process_state_probe as process_probe  # noqa: E402
import serena_transport_benchmark as transport_probe  # noqa: E402
import serena_project_server_probe as serena_probe  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def parse_jvm_values(raw: str) -> list[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("at least one JVM option is required")
    for value in values:
        if not value.startswith("-Xmx"):
            raise argparse.ArgumentTypeError(f"JVM option must start with -Xmx: {value}")
    return values


def local_override_text(jvm_options: str) -> str:
    return (
        "# Generated temporarily by kotlin_lsp_memory_matrix.py.\n"
        "# The benchmark restores the previous file unless --keep-local-override is used.\n"
        "ls_specific_settings:\n"
        "  kotlin:\n"
        f"    jvm_options: \"{jvm_options}\"\n"
    )


@contextmanager
def temporary_project_local_override(
    repo: Path,
    jvm_options: str,
    keep_local_override: bool = False,
) -> Iterator[Path]:
    serena_dir = repo / ".serena"
    serena_dir.mkdir(parents=True, exist_ok=True)
    local_path = serena_dir / "project.local.yml"
    existed = local_path.exists()
    original = local_path.read_text() if existed else None
    local_path.write_text(local_override_text(jvm_options))
    try:
        yield local_path
    finally:
        if keep_local_override:
            pass
        elif existed and original is not None:
            local_path.write_text(original)
        elif local_path.exists():
            local_path.unlink()


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return ordered[index]


def run_one_matrix_value(
    *,
    cases: list[dict[str, str]],
    repo: Path,
    jvm_options: str,
    port: int,
    timeout: float,
    startup_timeout: float,
    repeats: int,
    warmups: int,
    raw_dir: Path,
    target_project_path: str,
    expected_serena_mcp_count: int,
    allow_http_serena_server: bool,
    max_serena_growth: int,
) -> dict[str, Any]:
    before_process = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=target_project_path or None,
        expected_serena_mcp_count=expected_serena_mcp_count,
        allow_http_serena_server=allow_http_serena_server,
    )
    rows: list[dict[str, Any]] = []
    server = serena_probe.start_server(port, startup_timeout)
    try:
        for _ in range(warmups):
            for row in cases:
                serena_probe.execute(row, port, timeout)
        for pass_index in range(1, repeats + 1):
            for row in cases:
                result = serena_probe.execute(row, port, timeout)
                base = serena_probe.safe_name(f"{jvm_options}_{row['repo']}_{row['case_id']}_pass{pass_index}")
                stdout_path = raw_dir / f"{base}.stdout"
                stderr_path = raw_dir / f"{base}.stderr"
                stdout_path.write_text(str(result["stdout"]))
                stderr_path.write_text(str(result["stderr"]))
                rows.append(
                    {
                        "jvm_options": jvm_options,
                        "pass_index": pass_index,
                        "repo": row["repo"],
                        "case_id": row["case_id"],
                        "project": row["project"],
                        "tool_name": row["tool_name"],
                        "expected_status": row["expected_status"],
                        "min_byte_count": int(row["min_byte_count"]),
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
        target_project_path=target_project_path or None,
        expected_serena_mcp_count=expected_serena_mcp_count,
        allow_http_serena_server=allow_http_serena_server,
    )
    assertions = transport_probe.build_transport_assertions(
        rows,
        before_process,
        after_process,
        expected_repeats=repeats,
        max_serena_growth=max_serena_growth,
    )
    process_churn = {key: value for key, value in assertions["process_delta"].items() if value != 0}
    assertions["assertions"].append(
        {
            "status": "pass" if not process_churn else "warn",
            "check": "process_churn_absent",
            "message": f"process_delta={process_churn or {}}",
        }
    )
    assertions["summary"] = {
        "pass": sum(1 for item in assertions["assertions"] if item["status"] == "pass"),
        "warn": sum(1 for item in assertions["assertions"] if item["status"] == "warn"),
        "fail": sum(1 for item in assertions["assertions"] if item["status"] == "fail"),
    }
    walls = [float(row["wall_seconds"]) for row in rows]
    return {
        "jvm_options": jvm_options,
        "rows": rows,
        "assertions": assertions,
        "process_delta": assertions["process_delta"],
        "before_process_status": before_process["status"],
        "after_process_status": after_process["status"],
        "best_wall_seconds": min(walls) if walls else 0.0,
        "median_wall_seconds": median(walls) if walls else 0.0,
        "avg_wall_seconds": mean(walls) if walls else 0.0,
        "p95_wall_seconds": percentile_95(walls),
        "measured_rows": len(rows),
    }


def choose_lowest_stable(results: list[dict[str, Any]]) -> str | None:
    for result in results:
        summary = result["assertions"]["summary"]
        process_stable = all(value == 0 for value in result.get("process_delta", {}).values())
        if summary["fail"] == 0 and process_stable and not transport_probe.transport_error_seen(result["rows"]):
            return str(result["jvm_options"])
    return None


def write_outputs(output: Path, run_id: str, results: list[dict[str, Any]], cases: list[dict[str, str]], raw_dir: Path) -> dict[str, Path]:
    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / f"android-kotlin-lsp-memory-matrix-{run_id}.tsv"
    summary_path = output / f"android-kotlin-lsp-memory-matrix-summary-{run_id}.json"
    assertions_path = output / f"android-kotlin-lsp-memory-matrix-assertions-{run_id}.json"
    rows = []
    assertions_by_value: dict[str, Any] = {}
    for result in results:
        assertions_by_value[result["jvm_options"]] = result["assertions"]
        for row in result["rows"]:
            rows.append({key: value for key, value in row.items() if key not in {"stdout", "stderr"}})
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "schema": "agent-code-router-kit.android-kotlin-lsp-memory-matrix.v1",
        "date_utc": utc_now(),
        "case_count": len(cases),
        "recommended_jvm_options": choose_lowest_stable(results),
        "values": [
            {
                "jvm_options": result["jvm_options"],
                "assertions": result["assertions"]["summary"],
                "process_delta": result["process_delta"],
                "before_process_status": result["before_process_status"],
                "after_process_status": result["after_process_status"],
                "measured_rows": result["measured_rows"],
                "best_wall_seconds": result["best_wall_seconds"],
                "median_wall_seconds": result["median_wall_seconds"],
                "avg_wall_seconds": result["avg_wall_seconds"],
                "p95_wall_seconds": result["p95_wall_seconds"],
            }
            for result in results
        ],
        "rows_path": str(rows_path),
        "raw_dir": str(raw_dir),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions_by_value, indent=2, sort_keys=True) + "\n")
    return {"rows": rows_path, "summary": summary_path, "assertions": assertions_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Kotlin LSP JVM memory options for Android Serena ProjectServer.")
    parser.add_argument("--cases", default="benchmarks/android/serena-transport.sample-b2b.tsv")
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--target-repo-name", default="sample_b2b")
    parser.add_argument("--target-project-path", default="")
    parser.add_argument("--output", default="results/android/kotlin-lsp-memory-matrix")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--values", type=parse_jvm_values, default=parse_jvm_values("-Xmx2G,-Xmx4G,-Xmx6G"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--port-base", type=int, default=24710)
    parser.add_argument("--expected-serena-mcp-count", type=int, default=1)
    parser.add_argument("--allow-http-serena-server", action="store_true")
    parser.add_argument("--max-serena-growth", type=int, default=0)
    parser.add_argument("--keep-local-override", action="store_true")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.repeats < 1 or args.warmups < 0:
        parser.error("--repeats must be >= 1 and --warmups must be >= 0")
    if args.timeout <= 0 or args.startup_timeout <= 0:
        parser.error("timeouts must be > 0")
    if args.port_base <= 0:
        parser.error("--port-base must be > 0")

    cases = serena_probe.load_cases(Path(args.cases))
    repos = serena_probe.parse_repo_args(args.repo)
    errors = serena_probe.validate(cases, repos, require_repos=args.run)
    if args.run:
        target_repo = repos.get(args.target_repo_name)
        if target_repo is None:
            errors.append(f"target repo {args.target_repo_name!r} not provided")
        elif not (target_repo / ".serena" / "project.yml").exists():
            errors.append(f"target repo has no .serena/project.yml: {target_repo}")
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases; values={','.join(args.values)}")
    if not args.run:
        return 0

    target_repo = repos[args.target_repo_name]
    output = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for index, value in enumerate(args.values):
        with temporary_project_local_override(target_repo, value, keep_local_override=args.keep_local_override):
            results.append(
                run_one_matrix_value(
                    cases=cases,
                    repo=target_repo,
                    jvm_options=value,
                    port=args.port_base + index,
                    timeout=args.timeout,
                    startup_timeout=args.startup_timeout,
                    repeats=args.repeats,
                    warmups=args.warmups,
                    raw_dir=raw_dir,
                    target_project_path=args.target_project_path or str(target_repo),
                    expected_serena_mcp_count=args.expected_serena_mcp_count,
                    allow_http_serena_server=args.allow_http_serena_server,
                    max_serena_growth=args.max_serena_growth,
                )
            )
    paths = write_outputs(output, run_id, results, cases, raw_dir)
    total_counts = {
        "pass": sum(result["assertions"]["summary"]["pass"] for result in results),
        "warn": sum(result["assertions"]["summary"]["warn"] for result in results),
        "fail": sum(result["assertions"]["summary"]["fail"] for result in results),
    }
    recommended = choose_lowest_stable(results)
    print(f"Wrote {paths['rows']}")
    print(f"Wrote {paths['summary']}")
    print(f"Wrote {paths['assertions']}")
    print(
        "Assertions: "
        f"pass={total_counts['pass']}, warn={total_counts['warn']}, fail={total_counts['fail']}; "
        f"recommended={recommended or 'none'}"
    )
    return 3 if args.enforce_assertions and total_counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
