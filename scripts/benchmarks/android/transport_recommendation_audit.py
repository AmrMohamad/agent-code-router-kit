#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def all_zero(values: dict[str, Any] | None) -> bool:
    return all(int(value) == 0 for value in (values or {}).values())


def summary_counts(payload: dict[str, Any]) -> dict[str, int]:
    raw = payload.get("summary") or payload.get("assertions") or {}
    if isinstance(raw, dict) and "summary" in raw and isinstance(raw["summary"], dict):
        raw = raw["summary"]
    if not isinstance(raw, dict):
        raw = {}
    return {"pass": int(raw.get("pass", 0)), "warn": int(raw.get("warn", 0)), "fail": int(raw.get("fail", 0))}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def lifecycle_candidate(payload: dict[str, Any]) -> str:
    perf = payload.get("transport_performance") or {}
    candidate = str(perf.get("candidate_transport") or "")
    if candidate:
        return candidate

    by_transport: dict[str, list[float]] = {}
    for row in payload.get("cases", []):
        if row.get("status") != "pass":
            continue
        transport = str(row.get("transport", ""))
        if not transport:
            continue
        by_transport.setdefault(transport, []).append(float(row.get("wall_seconds", 0.0)))
    if not by_transport:
        return ""
    averages = {transport: sum(values) / len(values) for transport, values in by_transport.items() if values}
    return min(averages.items(), key=lambda item: (item[1], item[0]))[0] if averages else ""


def qualified_lifecycle(payload: dict[str, Any]) -> bool:
    transports = set(payload.get("transports", []))
    return (
        int(payload.get("case_count", 0)) >= 8
        and {"stdio", "streamable-http"} <= transports
        and all_zero(payload.get("process_delta", {}))
        and summary_counts(payload)["fail"] == 0
    )


def collect_lifecycle(results_root: Path) -> list[dict[str, Any]]:
    lifecycle_dir = results_root / "serena-mcp-lifecycle"
    records: list[dict[str, Any]] = []
    for path in sorted(lifecycle_dir.glob("android-serena-mcp-lifecycle-summary-*.json")):
        payload = load_json(path)
        records.append(
            {
                "path": str(path),
                "qualified": qualified_lifecycle(payload),
                "candidate_transport": lifecycle_candidate(payload),
                "case_count": int(payload.get("case_count", 0)),
                "transports": sorted(payload.get("transports", [])),
                "process_delta": payload.get("process_delta", {}),
                "assertions": summary_counts(payload),
            }
        )
    return records


def load_real_task_log(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return []
    if path.suffix == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            data = data.get("observations", data.get("rows", []))
        if not isinstance(data, list):
            raise SystemExit("real-task JSON must be a list or object with observations/rows")
        return [{str(k): str(v) for k, v in row.items()} for row in data]
    with path.open(newline="") as f:
        return [{str(k): str(v) for k, v in row.items()} for row in csv.DictReader(f, delimiter="\t")]


def summarize_real_tasks(rows: list[dict[str, str]]) -> dict[str, Any]:
    transport_counts = Counter(row.get("transport", "") for row in rows if row.get("transport"))
    failures = [
        row
        for row in rows
        if row.get("status", "pass") != "pass"
        or row.get("transport_error", "false").lower() in {"1", "true", "yes"}
        or row.get("process_growth", "0") not in {"", "0"}
        or not row.get("evidence", "").strip()
    ]
    return {
        "case_count": len(rows),
        "transport_counts": dict(sorted(transport_counts.items())),
        "evidence_count": sum(1 for row in rows if row.get("evidence", "").strip()),
        "failure_count": len(failures),
    }


def build_audit(results_root: Path, real_task_log: Path | None, min_real_tasks: int) -> dict[str, Any]:
    lifecycle = collect_lifecycle(results_root)
    qualified = [item for item in lifecycle if item["qualified"] and item["candidate_transport"]]
    candidate_counts = Counter(item["candidate_transport"] for item in qualified)
    candidate = candidate_counts.most_common(1)[0][0] if candidate_counts else ""

    real_tasks = summarize_real_tasks(load_real_task_log(real_task_log))
    real_task_ok = real_tasks["case_count"] >= min_real_tasks and real_tasks["failure_count"] == 0
    recommendation_status = "daily_recommendation" if candidate and real_task_ok else "lifecycle_candidate_only" if candidate else "insufficient_lifecycle_evidence"

    assertions = []
    assertions.append(
        {
            "status": "pass" if qualified else "fail",
            "check": "qualified_lifecycle_runs_present",
            "message": f"qualified_lifecycle_runs={len(qualified)}",
        }
    )
    assertions.append(
        {
            "status": "pass" if candidate else "fail",
            "check": "candidate_transport_present",
            "message": f"candidate_transport={candidate or 'none'}",
        }
    )
    assertions.append(
        {
            "status": "pass" if real_task_ok else "warn",
            "check": "real_task_observation_threshold",
            "message": f"real_task_count={real_tasks['case_count']} min={min_real_tasks} failures={real_tasks['failure_count']}",
        }
    )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }

    return {
        "schema": "agent-code-router-kit.android-transport-recommendation.v1",
        "date_utc": utc_now(),
        "results_root": str(results_root),
        "candidate_transport": candidate,
        "recommendation_status": recommendation_status,
        "recommendation_boundary": "Lifecycle evidence can nominate a candidate; daily recommendation requires enough real-task observations.",
        "minimum_real_task_observations": min_real_tasks,
        "lifecycle_summary": {
            "run_count": len(lifecycle),
            "qualified_run_count": len(qualified),
            "candidate_counts": dict(sorted(candidate_counts.items())),
            "runs": lifecycle,
        },
        "real_task_summary": real_tasks,
        "assertions": counts,
        "assertion_details": assertions,
    }


def write_outputs(output: Path, data: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    summary_path = output / f"android-transport-recommendation-summary-{run_id}.json"
    summary_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return {"summary": str(summary_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Android Serena transport evidence before selecting a daily MCP mode.")
    parser.add_argument("--results-root", default="results/android")
    parser.add_argument("--output", default="results/android/transport-recommendation")
    parser.add_argument("--real-task-log", help="Optional JSON/TSV real-task transport observations.")
    parser.add_argument("--min-real-tasks", type=int, default=10)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if args.min_real_tasks < 1:
        parser.error("--min-real-tasks must be >= 1")
    data = build_audit(
        Path(args.results_root).expanduser().resolve(),
        Path(args.real_task_log).expanduser().resolve() if args.real_task_log else None,
        args.min_real_tasks,
    )
    paths = write_outputs(Path(args.output).expanduser().resolve(), data)
    counts = data["assertions"]
    print(f"Wrote {paths['summary']}")
    print(
        f"Recommendation: {data['recommendation_status']} candidate={data['candidate_transport'] or 'none'}; "
        f"assertions pass={counts['pass']} warn={counts['warn']} fail={counts['fail']}"
    )
    return 3 if args.enforce_assertions and counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
