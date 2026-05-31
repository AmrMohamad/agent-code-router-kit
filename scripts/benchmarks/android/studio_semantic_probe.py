#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


REQUIRED_COLUMNS = [
    "case_id",
    "repo",
    "project",
    "command_type",
    "symbol",
    "context_file",
    "expected_status",
    "purpose",
]

VALID_COMMAND_TYPES = {"check", "analyze-file", "find-declaration", "find-usages"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def estimate_tokens(text: str) -> int:
    # Same conservative proxy used in the routing docs: roughly 4 chars/token.
    return (len(text) + 3) // 4


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise SystemExit(f"schema mismatch: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise SystemExit("case manifest is empty")
    return rows


def parse_repo_args(values: list[str]) -> dict[str, Path]:
    repos: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--repo must be name=/path, got {value!r}")
        name, raw = value.split("=", 1)
        repos[name] = Path(raw).expanduser().resolve()
    return repos


def validate(cases: list[dict[str, str]], repos: dict[str, Path], require_repos: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(cases, start=2):
        for col in REQUIRED_COLUMNS:
            if col not in row:
                errors.append(f"line {index}: missing column {col}")
        if not row.get("case_id"):
            errors.append(f"line {index}: missing case_id")
        if row.get("case_id") in seen:
            errors.append(f"line {index}: duplicate case_id {row.get('case_id')}")
        seen.add(row.get("case_id", ""))
        if row.get("command_type") not in VALID_COMMAND_TYPES:
            errors.append(f"line {index}: invalid command_type {row.get('command_type')!r}")
        if row.get("command_type") in {"find-declaration", "find-usages"} and not row.get("symbol"):
            errors.append(f"line {index}: symbol is required for {row.get('command_type')}")
        if row.get("command_type") == "analyze-file" and not row.get("context_file"):
            errors.append(f"line {index}: context_file is required for analyze-file")
        if require_repos:
            repo = row.get("repo", "")
            if repo not in repos:
                errors.append(f"line {index}: repo {repo!r} not provided")
            elif not repos[repo].exists():
                errors.append(f"line {index}: repo path missing: {repos[repo]}")
            elif row.get("context_file"):
                context_file = Path(row["context_file"])
                if not context_file.is_absolute():
                    context_file = repos[repo] / context_file
                if not context_file.exists():
                    errors.append(f"line {index}: context_file missing: {context_file}")
    return errors


def build_command(row: dict[str, str], repo_path: Path) -> list[str]:
    command_type = row["command_type"]
    base = ["android", "studio"]
    if command_type == "check":
        return base + ["check"]
    if command_type == "analyze-file":
        return base + ["analyze-file", "--project", row["project"], row["context_file"]]
    if command_type == "find-declaration":
        argv = base + ["find-declaration", "--project", row["project"], "--short"]
        if row.get("context_file"):
            argv += ["--context-file", str(repo_path / row["context_file"])]
        return argv + [row["symbol"]]
    if command_type == "find-usages":
        return base + ["find-usages", "--project", row["project"], "--short", row["symbol"]]
    raise AssertionError(command_type)


def classify_status(row: dict[str, str], exit_code: int, stdout: str, stderr: str, timed_out: bool) -> str:
    text = f"{stdout}\n{stderr}"
    if timed_out:
        return "timeout"
    if exit_code != 0:
        return "error"
    if row["command_type"] == "check":
        return "pass" if row["project"] in text and "READY" in text else "no-ready-project"
    if row["command_type"] == "analyze-file":
        return "pass" if "No issues found" in text or "Analyzing file:" in text else "unknown"
    if "No declaration found" in text or "failed to identify the target declaration" in text:
        return "no-result"
    if text.strip():
        return "pass"
    return "empty"


def execute(row: dict[str, str], repo_path: Path, timeout: float) -> dict[str, object]:
    argv = build_command(row, repo_path)
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=repo_path,
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        wall = time.perf_counter() - started
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        wall = time.perf_counter() - started
        stdout = (exc.stdout or "")
        stderr = (exc.stderr or "")
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        exit_code = 124
        timed_out = True
    combined = f"{stdout}{stderr}"
    return {
        "argv": argv,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "status": classify_status(row, exit_code, stdout, stderr, timed_out),
        "line_count": len(combined.splitlines()),
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
    }


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("_")


def build_assertions(rows: list[dict[str, object]]) -> dict[str, object]:
    statuses_by_case: dict[str, set[str]] = {}
    for row in rows:
        statuses_by_case.setdefault(str(row["case_id"]), set()).add(str(row["status"]))

    assertions = []
    for row in rows:
        expected = str(row["expected_status"])
        status = str(row["status"])
        ok = (
            expected == "probe"
            or expected == status
            or (expected == "pass" and status == "pass")
        )
        transient_expected_pass = expected == "pass" and status != "pass" and "pass" in statuses_by_case[str(row["case_id"])]
        assertions.append(
            {
                "status": "pass" if ok else "warn" if transient_expected_pass else "fail",
                "check": "expected_status" if not transient_expected_pass else "transient_expected_status",
                "message": f"expected={expected} actual={status}",
                "context": {
                    "repo": row["repo"],
                    "case_id": row["case_id"],
                    "pass_index": row["pass_index"],
                },
            }
        )
        if status in {"no-result", "timeout", "error"}:
            assertions.append(
                {
                    "status": "warn",
                    "check": "semantic_probe_not_ready",
                    "message": f"actual={status}",
                    "context": {
                        "repo": row["repo"],
                        "case_id": row["case_id"],
                        "pass_index": row["pass_index"],
                    },
                }
            )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions}


def run(args: argparse.Namespace, cases: list[dict[str, str]], repos: dict[str, Path]) -> int:
    output_root = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output_root / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []

    for pass_index in range(1, args.repeats + 1):
        for row in cases:
            result = execute(row, repos[row["repo"]], args.timeout)
            base = safe_name(f"{row['repo']}_{row['case_id']}_pass{pass_index}")
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
                    "command_type": row["command_type"],
                    "symbol": row["symbol"],
                    "context_file": row["context_file"],
                    "expected_status": row["expected_status"],
                    "purpose": row["purpose"],
                    "status": result["status"],
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                    "line_count": result["line_count"],
                    "byte_count": result["byte_count"],
                    "estimated_tokens": result["estimated_tokens"],
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "command_argv": json.dumps(result["argv"]),
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)
    rows_path = output_root / f"android-studio-semantic-{run_id}.tsv"
    summary_path = output_root / f"android-studio-semantic-summary-{run_id}.json"
    assertions_path = output_root / f"android-studio-semantic-assertions-{run_id}.json"

    fieldnames = [
        "pass_index",
        "repo",
        "case_id",
        "project",
        "command_type",
        "symbol",
        "context_file",
        "expected_status",
        "purpose",
        "status",
        "exit_code",
        "timed_out",
        "wall_seconds",
        "line_count",
        "byte_count",
        "estimated_tokens",
        "stdout_path",
        "stderr_path",
        "command_argv",
    ]
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), []).append(row)
    summary = []
    for case_id, group in sorted(grouped.items()):
        walls = [float(row["wall_seconds"]) for row in group]
        last = group[-1]
        summary.append(
            {
                "case_id": case_id,
                "repo": last["repo"],
                "command_type": last["command_type"],
                "symbol": last["symbol"],
                "statuses": sorted({str(row["status"]) for row in group}),
                "best_wall_seconds": min(walls),
                "median_wall_seconds": median(walls),
                "avg_wall_seconds": mean(walls),
                "last_byte_count": int(last["byte_count"]),
                "last_estimated_tokens": int(last["estimated_tokens"]),
                "expected_status": last["expected_status"],
            }
        )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    assertion_payload = build_assertions(rows)
    counts = assertion_payload["summary"]
    assertions_path.write_text(
        json.dumps(
            {
                "schema": "agent-code-router-kit.android-studio-semantic-assertions.v1",
                "date_utc": utc_now(),
                "summary": counts,
                "assertions": assertion_payload["assertions"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}")
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure Android Studio CLI semantic probes.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--repo", action="append", default=[], help="Repo mapping name=/path")
    parser.add_argument("--output", default="results/android")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    cases = load_cases(Path(args.cases))
    repos = parse_repo_args(args.repo)
    errors = validate(cases, repos, require_repos=args.run)
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases")
    if args.run:
        return run(args, cases, repos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
