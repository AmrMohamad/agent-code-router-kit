#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import append_jsonl, to_json_file
from scripts.lib.task_oracles import load_task_oracles, verify_transcript_file


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify real-agent benchmark transcripts against external task oracles.")
    parser.add_argument("--runs", required=True, help="Path to runs.jsonl.")
    parser.add_argument("--oracles", required=True, help="Path to task-oracles.json.")
    parser.add_argument("--out", required=True, help="Output oracle verification JSON.")
    parser.add_argument("--jsonl", help="Optional per-run oracle JSONL output.")
    args = parser.parse_args(argv)

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
    return 0 if summary["oracle_fail_count"] == 0 and summary["oracle_not_configured_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
