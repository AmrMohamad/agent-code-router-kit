#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import append_jsonl, load_tasks, to_json_file
from scripts.lib.task_oracles import load_task_oracles, validate_task_oracle_plan, verify_transcript_file


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_run_oracles(args: argparse.Namespace) -> int:
    if not args.out:
        raise SystemExit("--runs mode requires --out")
    rows = load_jsonl(Path(args.runs))
    oracles = load_task_oracles(args.oracles)
    results: list[dict[str, object]] = []
    if args.jsonl:
        Path(args.jsonl).unlink(missing_ok=True)
    for row in rows:
        task_id = str(row.get("task_id", ""))
        task_family = str(row.get("task_family", ""))
        oracle = oracles.get(task_id) or oracles.get(f"family:{task_family}")
        transcript = Path(str(row.get("run_dir", ""))) / "transcript.txt"
        if not transcript.exists():
            result = {
                "task_id": task_id,
                "oracle_id": oracle.get("oracle_id", task_id) if oracle else "",
                "oracle_type": oracle.get("type", "missing_transcript") if oracle else "missing_transcript",
                "status": "fail",
                "checks": [],
                "reason": "transcript.txt is missing",
            }
        else:
            result = asdict(
                verify_transcript_file(
                    task_id=task_id,
                    oracle=oracle,
                    transcript_path=transcript,
                    run_row=row,
                )
            )
        result["run_id"] = row.get("run_id", "")
        result["profile"] = row.get("profile", "")
        results.append(result)
        if args.jsonl:
            append_jsonl(args.jsonl, result)

    summary = {
        "run_count": len(rows),
        "oracle_pass_count": sum(1 for item in results if item["status"] == "pass"),
        "oracle_fail_count": sum(1 for item in results if item["status"] == "fail"),
        "oracle_not_configured_count": sum(1 for item in results if item["status"] == "not_configured"),
        "rows": results,
    }
    to_json_file(args.out, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["oracle_fail_count"] == 0 and summary["oracle_not_configured_count"] == 0 else 1


def validate_oracle_plan(args: argparse.Namespace) -> int:
    result = validate_task_oracle_plan(
        tasks=load_tasks(args.tasks),
        oracles=load_task_oracles(args.oracles),
        require_task_specific=args.require_task_specific,
    )
    if args.out:
        to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify benchmark oracles or validate task-oracle coverage.")
    parser.add_argument("--runs", help="Path to runs.jsonl for transcript verification mode.")
    parser.add_argument("--tasks", help="Path to tasks TSV for oracle-plan validation mode.")
    parser.add_argument("--oracles", required=True, help="Path to task-oracles.json.")
    parser.add_argument("--require-task-specific", action="store_true")
    parser.add_argument("--out", help="Output JSON path.")
    parser.add_argument("--jsonl", help="Optional per-run oracle JSONL output for --runs mode.")
    args = parser.parse_args(argv)

    if args.tasks:
        return validate_oracle_plan(args)
    if args.runs:
        return verify_run_oracles(args)
    raise SystemExit("provide either --tasks for oracle-plan validation or --runs for transcript verification")


if __name__ == "__main__":
    raise SystemExit(main())
