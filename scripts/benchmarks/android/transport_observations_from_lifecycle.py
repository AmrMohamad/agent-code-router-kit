#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_files(root: Path, limit: int) -> list[Path]:
    matches = sorted(root.glob("android-serena-mcp-lifecycle-summary-*.json"))
    return matches[-limit:] if limit > 0 else matches


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def observation_from_case(path: Path, case: dict[str, Any], process_delta: dict[str, Any]) -> dict[str, Any]:
    checks = case.get("checks") or {}
    transport_error = not bool(checks.get("transport_error_absent", False))
    process_growth = max(0, int(process_delta.get("serena_mcp", 0)))
    return {
        "task_id": f"{path.stem}:{case.get('case_id', 'unknown')}",
        "transport": str(case.get("transport", "")),
        "status": str(case.get("status", "")),
        "transport_error": "true" if transport_error else "false",
        "process_growth": str(process_growth),
        "notes": "Generated from direct MCP lifecycle semantic task run.",
        "evidence": f"{path}#{case.get('case_id', 'unknown')}",
        "source_kind": "direct_mcp_semantic_task",
        "recorded_at": utc_now(),
    }


def build_log(lifecycle_dir: Path, transport: str, limit_runs: int) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    source_files: list[str] = []
    for path in latest_files(lifecycle_dir, limit_runs):
        payload = load_json(path)
        source_files.append(str(path))
        process_delta = payload.get("process_delta") or {}
        for case in payload.get("cases", []):
            if case.get("transport") == transport:
                observations.append(observation_from_case(path, case, process_delta))
    return {
        "schema": "agent-code-router-kit.android-transport-real-task-observations.v1",
        "date_utc": utc_now(),
        "source": "android_stable_serena_mcp_lifecycle_probe",
        "source_boundary": (
            "Rows are direct MCP semantic task observations over the candidate transport. "
            "They prove repeated transport behavior for semantic tool calls, not full user workflow correctness."
        ),
        "transport": transport,
        "source_files": source_files,
        "observations": observations,
    }


def validate_log(data: dict[str, Any], min_observations: int) -> dict[str, Any]:
    rows = data.get("observations", [])
    errors: list[str] = []
    valid = 0
    for index, row in enumerate(rows, start=1):
        if row.get("status") != "pass":
            errors.append(f"row {index}: status is not pass")
        if row.get("transport_error") not in {"false", "0", "no"}:
            errors.append(f"row {index}: transport_error is not false")
        if str(row.get("process_growth", "")) != "0":
            errors.append(f"row {index}: process_growth is not 0")
        if not str(row.get("evidence", "")).strip():
            errors.append(f"row {index}: missing evidence")
        if str(row.get("status")) == "pass" and row.get("transport_error") in {"false", "0", "no"} and str(row.get("process_growth")) == "0" and str(row.get("evidence", "")).strip():
            valid += 1
    return {
        "valid_observations": valid,
        "minimum_observations": min_observations,
        "errors": errors,
        "ok": valid >= min_observations and not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build transport real-task observations from direct MCP lifecycle task artifacts.")
    parser.add_argument("--lifecycle-dir", default="results/android/serena-mcp-lifecycle")
    parser.add_argument("--transport", default="streamable-http")
    parser.add_argument("--limit-runs", type=int, default=3)
    parser.add_argument("--output", default="results/android/live-evidence/android-transport-real-task-observations.json")
    parser.add_argument("--min-observations", type=int, default=10)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()

    if args.limit_runs < 1:
        parser.error("--limit-runs must be >= 1")
    if args.min_observations < 1:
        parser.error("--min-observations must be >= 1")
    data = build_log(Path(args.lifecycle_dir).expanduser().resolve(), args.transport, args.limit_runs)
    validation = validate_log(data, args.min_observations)
    data["validation"] = validation
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {output}")
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 3 if args.enforce and not validation["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
