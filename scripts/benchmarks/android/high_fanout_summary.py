#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SHARED_DIR = SCRIPT_DIR.parent / "shared"
sys.path.insert(0, str(SHARED_DIR))
import output_budget  # noqa: E402


DEFAULT_PATTERNS = ["UseCase", "ViewModel", "Repository", "Mapper", "Service", "Module"]
DEFAULT_GLOBS = ["*.kt", "*.java"]


@dataclass(frozen=True)
class PatternSummary:
    pattern: str
    status: str
    total_matches: int
    file_count: int
    top_files: list[dict[str, Any]]
    top_modules: list[dict[str, Any]]
    top_packages: list[dict[str, Any]]
    command: list[str]
    wall_seconds: float
    output_bytes: int
    budget: dict[str, object]
    next_actions: list[str]
    stderr: str


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def parse_count_output(stdout: str) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for raw in stdout.splitlines():
        if not raw.strip() or ":" not in raw:
            continue
        path, count_text = raw.rsplit(":", 1)
        try:
            count = int(count_text.strip())
        except ValueError:
            continue
        rows.append((path, count))
    return rows


def next_actions_for_pattern(file_count: int, total_matches: int) -> list[str]:
    actions = [
        "narrow by Gradle module",
        "narrow by package",
        "narrow by concrete class or member",
    ]
    if file_count > 20 or total_matches > 50:
        actions.append("switch to semantic symbol proof after selecting a concrete target")
    else:
        actions.append("read focused ranges only")
    return actions


def summarize_pattern(repo: Path, pattern: str, globs: list[str], top_limit: int, timeout: float) -> PatternSummary:
    argv = ["rg", "--count-matches", "--sort", "path"]
    for glob in globs:
        argv.extend(["--glob", glob])
    argv.extend(["--", pattern, "."])
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=repo,
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        status = "pass" if proc.returncode in {0, 1} else "error"
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        status = "timeout"
    wall = time.perf_counter() - started
    rows = parse_count_output(stdout)
    sorted_rows = sorted(rows, key=lambda item: (-item[1], item[0]))
    budget = output_budget.evaluate_output_size(len(stdout.encode()))
    total_matches = sum(count for _, count in rows)
    file_count = len(rows)
    return PatternSummary(
        pattern=pattern,
        status=status,
        total_matches=total_matches,
        file_count=file_count,
        top_files=[{"path": path, "matches": count} for path, count in sorted_rows[:top_limit]],
        top_modules=output_budget.top_group_counts(
            rows,
            output_budget.android_module_from_path,
            limit=top_limit,
        ),
        top_packages=output_budget.top_group_counts(
            rows,
            output_budget.android_package_from_path,
            limit=top_limit,
        ),
        command=argv,
        wall_seconds=wall,
        output_bytes=len(stdout.encode()),
        budget=budget,
        next_actions=next_actions_for_pattern(file_count, total_matches),
        stderr=stderr,
    )


def build_payload(repo: Path, patterns: list[str], globs: list[str], top_limit: int, timeout: float) -> dict[str, Any]:
    summaries = [summarize_pattern(repo, pattern, globs, top_limit, timeout) for pattern in patterns]
    return {
        "created_at": utc_now(),
        "repo": str(repo),
        "mode": "summary_only",
        "summary_policy": {
            "raw_snippets": "disabled",
            "top_file_limit": top_limit,
            "globs": globs,
        },
        "patterns": [
            {
                "pattern": item.pattern,
                "status": item.status,
                "total_matches": item.total_matches,
                "file_count": item.file_count,
                "top_files": item.top_files,
                "top_modules": item.top_modules,
                "top_packages": item.top_packages,
                "command": item.command,
                "mode": "summary_only",
                "wall_seconds": round(item.wall_seconds, 6),
                "command_output_bytes": item.output_bytes,
                "output_budget": item.budget,
                "estimated_summary_tokens": estimate_tokens(json.dumps(item.top_files, sort_keys=True)),
                "next_actions": item.next_actions,
                "stderr": item.stderr,
            }
            for item in summaries
        ],
    }


def build_assertions(payload: dict[str, Any]) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = [
        {
            "status": "pass",
            "check": "summary_mode",
            "message": "High-fanout probe used rg count summaries and did not emit raw match snippets.",
        }
    ]
    for item in payload["patterns"]:
        status = item["status"]
        assertions.append(
            {
                "status": "pass" if status == "pass" else "fail",
                "check": "pattern_status",
                "message": f"pattern={item['pattern']} status={status}",
            }
        )
        if int(item["file_count"]) > 20 or int(item["total_matches"]) > 50:
            assertions.append(
                {
                    "status": "warn",
                    "check": "high_fanout_requires_summary_first",
                    "message": (
                        f"pattern={item['pattern']} files={item['file_count']} "
                        f"matches={item['total_matches']}"
                    ),
                }
            )
        budget = item.get("output_budget") or {"status": "pass", "message": "not recorded"}
        budget_status = str(budget.get("status", "pass"))
        assertions.append(
            {
                "status": budget_status if budget_status in {"pass", "warn", "fail"} else "fail",
                "check": "output_budget",
                "message": f"pattern={item['pattern']} {budget.get('message', '')}",
            }
        )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions}


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize high-fanout Android symbols without raw dumps.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pattern", action="append", dest="patterns")
    parser.add_argument("--glob", action="append", dest="globs")
    parser.add_argument("--top-limit", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", default="results/android/high-fanout-summary")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if args.top_limit < 1:
        parser.error("--top-limit must be >= 1")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")
    if args.validate:
        if not repo.exists():
            raise SystemExit(f"repo path missing: {repo}")
        print("VALIDATION PASSED: high-fanout summary")
    if not args.run:
        return 0

    payload = build_payload(repo, args.patterns or DEFAULT_PATTERNS, args.globs or DEFAULT_GLOBS, args.top_limit, args.timeout)
    assertions = build_assertions(payload)
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    summary_path = output / f"android-high-fanout-summary-{run_id}.json"
    assertions_path = output / f"android-high-fanout-assertions-{run_id}.json"
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(
        "Assertions: "
        f"pass={assertions['summary']['pass']}, "
        f"warn={assertions['summary']['warn']}, "
        f"fail={assertions['summary']['fail']}"
    )
    if args.enforce_assertions and assertions["summary"]["fail"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
