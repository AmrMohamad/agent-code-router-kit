#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BEHAVIOR_REQUIRED_COLUMNS = [
    "case_id",
    "repo_scope",
    "task_prompt",
    "expected_intent",
    "expected_first_tool",
    "expected_proof_layer",
    "expected_summary_mode",
    "forbidden_first_tools_json",
    "purpose",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_behavior_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != BEHAVIOR_REQUIRED_COLUMNS:
            raise SystemExit(f"behavior manifest schema mismatch: {reader.fieldnames}")
        return list(reader)


def choose_behavior_cases(cases: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    selected: list[dict[str, str]] = []
    seen_tools: set[str] = set()
    for row in cases:
        tool = row["expected_first_tool"]
        if tool in seen_tools:
            continue
        selected.append(row)
        seen_tools.add(tool)
        if len(selected) >= limit:
            return selected
    for row in cases:
        if row in selected:
            continue
        selected.append(row)
        if len(selected) >= limit:
            return selected
    return selected


def behavior_template(cases: list[dict[str, str]], limit: int) -> dict[str, Any]:
    selected = choose_behavior_cases(cases, limit)
    return {
        "schema": "agent-code-router-kit.android-live-behavior-observations.template.v1",
        "date_utc": utc_now(),
        "instructions": [
            "Fill observed_first_tool only after watching the live agent choose its first tool.",
            "Do not copy expected_first_tool into observed_first_tool unless that is what actually happened.",
            "Run agent_behavior_gate.py with --observed-log after filling the observations.",
        ],
        "minimum_observations_for_readiness": limit,
        "observations": [
            {
                "case_id": row["case_id"],
                "task_prompt": row["task_prompt"],
                "expected_first_tool": row["expected_first_tool"],
                "observed_first_tool": "",
                "observed_notes": "",
                "evidence": "",
            }
            for row in selected
        ],
    }


def transport_template(limit: int, candidate_transport: str) -> dict[str, Any]:
    return {
        "schema": "agent-code-router-kit.android-transport-real-task-observations.template.v1",
        "date_utc": utc_now(),
        "instructions": [
            "Fill one row per real Android task that used the candidate Serena MCP transport.",
            "status must be pass only when the task completed without transport failure.",
            "transport_error should be true if Transport closed/reset/refused/broken-pipe was observed.",
            "process_growth must be 0 unless a new stale Serena/Kotlin process remained after the task.",
        ],
        "candidate_transport": candidate_transport,
        "minimum_observations_for_readiness": limit,
        "observations": [
            {
                "task_id": f"transport-task-{index:02d}",
                "transport": candidate_transport,
                "status": "",
                "transport_error": "",
                "process_growth": "",
                "notes": "",
                "evidence": "",
            }
            for index in range(1, limit + 1)
        ],
    }


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate fillable Android live-evidence observation templates.")
    parser.add_argument("--behavior-cases", default="benchmarks/android/agent-behavior.sample-b2b.tsv")
    parser.add_argument("--output", default="results/android/live-evidence-templates")
    parser.add_argument("--min-observations", type=int, default=10)
    parser.add_argument("--candidate-transport", default="streamable-http")
    args = parser.parse_args()

    if args.min_observations < 1:
        parser.error("--min-observations must be >= 1")
    output = Path(args.output).expanduser().resolve()
    behavior = behavior_template(load_behavior_cases(Path(args.behavior_cases)), args.min_observations)
    transport = transport_template(args.min_observations, args.candidate_transport)
    behavior_path = output / "android-live-behavior-observations.template.json"
    transport_path = output / "android-transport-real-task-observations.template.json"
    write_json(behavior_path, behavior)
    write_json(transport_path, transport)
    print(f"Wrote {behavior_path}")
    print(f"Wrote {transport_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
