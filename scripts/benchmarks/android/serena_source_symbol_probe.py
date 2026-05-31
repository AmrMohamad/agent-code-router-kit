#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


REQUIRED_COLUMNS = ["case_id", "repo", "source_file", "expected_status", "min_symbol_count", "purpose"]
VALID_STATUSES = {
    "pass",
    "probe",
    "timeout",
    "no-symbols",
    "multiple-editing-sessions",
    "gradle-import-failed",
    "lsp-cancelled",
    "error",
}

SAVED_RE = re.compile(r"(?P<count>\d+)\s+symbols saved")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def estimate_tokens(text: str) -> int:
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


def source_path(row: dict[str, str], repos: dict[str, Path]) -> Path:
    path = Path(row["source_file"])
    if path.is_absolute():
        return path
    return repos[row["repo"]] / path


def validate(cases: list[dict[str, str]], repos: dict[str, Path], require_repos: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(cases, start=2):
        for col in REQUIRED_COLUMNS:
            if col not in row or not row[col]:
                errors.append(f"line {index}: missing {col}")
        case_id = row.get("case_id", "")
        if case_id in seen:
            errors.append(f"line {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        if row.get("expected_status") not in VALID_STATUSES:
            errors.append(f"line {index}: invalid expected_status {row.get('expected_status')!r}")
        try:
            minimum = int(row.get("min_symbol_count", ""))
            if minimum < 0:
                errors.append(f"line {index}: min_symbol_count must be >= 0")
        except ValueError:
            errors.append(f"line {index}: min_symbol_count must be an integer")
        if require_repos:
            repo = row.get("repo", "")
            if repo not in repos:
                errors.append(f"line {index}: repo {repo!r} not provided")
            elif not repos[repo].exists():
                errors.append(f"line {index}: repo path missing: {repos[repo]}")
            elif not source_path(row, repos).exists():
                errors.append(f"line {index}: source_file missing: {source_path(row, repos)}")
    return errors


def classify(exit_code: int, stdout: str, stderr: str, timed_out: bool, symbol_count: int) -> str:
    text = f"{stdout}\n{stderr}"
    if timed_out:
        return "timeout"
    if "Multiple editing sessions for one workspace" in text:
        return "multiple-editing-sessions"
    if "Gradle import failed" in text:
        return "gradle-import-failed"
    if "cancelled (-32800)" in text:
        return "lsp-cancelled"
    if exit_code == 0 and symbol_count > 0:
        return "pass"
    if exit_code == 0:
        return "no-symbols"
    return "error"


def symbol_count_from(stdout: str) -> int:
    counts = [int(match.group("count")) for match in SAVED_RE.finditer(stdout)]
    if counts:
        return max(counts)
    return sum(1 for line in stdout.splitlines() if line.startswith("  - "))


def execute(row: dict[str, str], repo: Path, timeout: float) -> dict[str, object]:
    file_path = source_path(row, {row["repo"]: repo})
    argv = ["serena", "project", "index-file", "-v", str(file_path), str(repo)]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=repo,
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        stdout = proc.stdout
        stderr = proc.stderr
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        exit_code = 124
        timed_out = True
    wall = time.perf_counter() - started
    combined = f"{stdout}{stderr}"
    count = symbol_count_from(stdout)
    return {
        "argv": argv,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "status": classify(exit_code, stdout, stderr, timed_out, count),
        "symbol_count": count,
        "line_count": len(combined.splitlines()),
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
    }


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("_")


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
                    "source_file": row["source_file"],
                    "expected_status": row["expected_status"],
                    "min_symbol_count": int(row["min_symbol_count"]),
                    "purpose": row["purpose"],
                    "status": result["status"],
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                    "symbol_count": result["symbol_count"],
                    "line_count": result["line_count"],
                    "byte_count": result["byte_count"],
                    "estimated_tokens": result["estimated_tokens"],
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "command_argv": json.dumps(result["argv"]),
                }
            )

    rows_path = output_root / f"serena-source-symbol-{run_id}.tsv"
    summary_path = output_root / f"serena-source-symbol-summary-{run_id}.json"
    assertions_path = output_root / f"serena-source-symbol-assertions-{run_id}.json"
    fieldnames = [
        "pass_index",
        "repo",
        "case_id",
        "source_file",
        "expected_status",
        "min_symbol_count",
        "purpose",
        "status",
        "exit_code",
        "timed_out",
        "wall_seconds",
        "symbol_count",
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
                "source_file": last["source_file"],
                "statuses": sorted({str(row["status"]) for row in group}),
                "expected_status": last["expected_status"],
                "best_wall_seconds": min(walls),
                "median_wall_seconds": median(walls),
                "avg_wall_seconds": mean(walls),
                "last_symbol_count": int(last["symbol_count"]),
                "last_byte_count": int(last["byte_count"]),
                "last_estimated_tokens": int(last["estimated_tokens"]),
            }
        )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    assertions = []
    for row in rows:
        expected = str(row["expected_status"])
        status = str(row["status"])
        minimum = int(row["min_symbol_count"])
        symbol_count = int(row["symbol_count"])
        expected_ok = expected == "probe" or status == expected
        symbols_ok = expected != "pass" or symbol_count >= minimum
        context = {
            "repo": row["repo"],
            "case_id": row["case_id"],
            "pass_index": row["pass_index"],
        }
        assertions.append(
            {
                "status": "pass" if expected_ok and symbols_ok else "fail",
                "check": "expected_status_and_symbol_count",
                "message": f"expected={expected} actual={status} symbols={symbol_count} min={minimum}",
                "context": context,
            }
        )
        if status != "pass":
            assertions.append(
                {
                    "status": "warn",
                    "check": "serena_source_symbol_not_ready",
                    "message": f"actual={status}",
                    "context": context,
                }
            )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    assertions_path.write_text(
        json.dumps(
            {
                "schema": "agent-code-router-kit.serena-source-symbol-assertions.v1",
                "date_utc": utc_now(),
                "summary": counts,
                "assertions": assertions,
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
    parser = argparse.ArgumentParser(description="Probe Serena/Kotlin LSP source-symbol extraction.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--repo", action="append", default=[], help="Repo mapping name=/path")
    parser.add_argument("--output", default="results/android/serena-source-symbol")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")
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
