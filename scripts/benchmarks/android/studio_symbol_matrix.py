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
from typing import Any


REQUIRED_COLUMNS = [
    "case_id",
    "repo",
    "project",
    "category",
    "symbol",
    "context_file",
    "expected_declaration_file",
    "expected_usage_files_json",
    "expected_min_usages",
    "expected_kind",
    "expected_status",
    "no_result_classification",
    "purpose",
]
VALID_EXPECTED_STATUSES = {"pass", "probe", "boundary"}
DEFAULT_DECLARATION_THRESHOLD = 8
DEFAULT_USAGE_THRESHOLD = 7


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("_")


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


def decode_expected_usage_files(row: dict[str, str]) -> list[str]:
    decoded = json.loads(row["expected_usage_files_json"])
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise ValueError("expected_usage_files_json must decode to a list of strings")
    return decoded


def validate(cases: list[dict[str, str]], repos: dict[str, Path], require_repos: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(cases, start=2):
        for column in REQUIRED_COLUMNS:
            if column not in row:
                errors.append(f"line {index}: missing column {column}")
        case_id = row.get("case_id", "")
        if not case_id:
            errors.append(f"line {index}: missing case_id")
        if case_id in seen:
            errors.append(f"line {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        if row.get("expected_status") not in VALID_EXPECTED_STATUSES:
            errors.append(f"line {index}: invalid expected_status {row.get('expected_status')!r}")
        try:
            expected_min = int(row.get("expected_min_usages", ""))
            if expected_min < 0:
                errors.append(f"line {index}: expected_min_usages must be >= 0")
        except ValueError:
            errors.append(f"line {index}: expected_min_usages must be an integer")
        try:
            decode_expected_usage_files(row)
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(f"line {index}: invalid expected_usage_files_json: {exc}")
        if row.get("expected_status") == "pass":
            if not row.get("expected_declaration_file"):
                errors.append(f"line {index}: pass cases need expected_declaration_file")
            if not row.get("expected_usage_files_json"):
                errors.append(f"line {index}: pass cases need expected_usage_files_json")
        if require_repos:
            repo_name = row.get("repo", "")
            repo = repos.get(repo_name)
            if repo is None:
                errors.append(f"line {index}: repo {repo_name!r} not provided")
                continue
            if not repo.exists():
                errors.append(f"line {index}: repo path missing: {repo}")
                continue
            context_file = row.get("context_file", "")
            if context_file and not (repo / context_file).exists():
                errors.append(f"line {index}: context_file missing: {repo / context_file}")
            expected_declaration = row.get("expected_declaration_file", "")
            if expected_declaration and not (repo / expected_declaration).exists():
                errors.append(f"line {index}: expected_declaration_file missing: {repo / expected_declaration}")
            for expected_usage in decode_expected_usage_files(row):
                if not (repo / expected_usage).exists():
                    errors.append(f"line {index}: expected usage file missing: {repo / expected_usage}")
    return errors


def status_text(result: dict[str, Any]) -> str:
    return f"{result.get('stdout', '')}\n{result.get('stderr', '')}"


def normalize_studio_status(exit_code: int, stdout: str, stderr: str, timed_out: bool) -> str:
    text = f"{stdout}\n{stderr}"
    stripped = text.strip()
    if timed_out:
        return "timeout"
    if exit_code != 0:
        return "error"
    if "No running Android Studio instance has project" in text:
        return "error"
    if stripped.startswith("Error:") or "\nError:" in text:
        return "error"
    lowered = stripped.lower()
    no_result_markers = [
        "no declaration found",
        "failed to identify the target declaration",
        "no usages found",
        "no usage found",
    ]
    if any(marker in lowered for marker in no_result_markers):
        return "no-result"
    if stripped:
        return "pass"
    return "empty"


def build_declaration_command(row: dict[str, str], repo: Path) -> list[str]:
    argv = ["android", "studio", "find-declaration", "--project", row["project"], "--short"]
    if row.get("context_file"):
        argv += ["--context-file", str(repo / row["context_file"])]
    return argv + [row["symbol"]]


def build_usages_command(row: dict[str, str]) -> list[str]:
    return ["android", "studio", "find-usages", "--project", row["project"], "--short", row["symbol"]]


def run_command(argv: list[str], cwd: Path, timeout: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
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
    status = normalize_studio_status(exit_code, stdout, stderr, timed_out)
    combined = f"{stdout}{stderr}"
    return {
        "argv": argv,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "status": status,
        "line_count": len(combined.splitlines()),
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
    }


def extract_repo_paths(text: str, repo: Path) -> set[str]:
    paths: set[str] = set()
    extensions = r"(?:kt|java|xml|kts)"
    repo_text = re.escape(str(repo))
    absolute_pattern = re.compile(repo_text + rf"/[A-Za-z0-9_./@+~() -]+\.{extensions}")
    for match in absolute_pattern.finditer(text):
        candidate = Path(match.group(0).rstrip(").,;"))
        try:
            relative = candidate.relative_to(repo)
        except ValueError:
            continue
        if (repo / relative).exists():
            paths.add(str(relative))

    relative_pattern = re.compile(rf"(?<![A-Za-z0-9_./@+-])([A-Za-z0-9_./@+~-]+\.{extensions})")
    for match in relative_pattern.finditer(text):
        raw = match.group(1).strip("./")
        if raw and (repo / raw).exists():
            paths.add(raw)
    return paths


def evaluate_case(
    row: dict[str, str],
    repo: Path,
    declaration_result: dict[str, Any],
    usages_result: dict[str, Any],
) -> dict[str, Any]:
    declaration_paths = extract_repo_paths(status_text(declaration_result), repo)
    usage_paths = extract_repo_paths(status_text(usages_result), repo)
    expected_declaration = row.get("expected_declaration_file", "")
    expected_usage_files = set(decode_expected_usage_files(row))
    expected_min_usages = int(row["expected_min_usages"])
    declaration_status = str(declaration_result["status"])
    usages_status = str(usages_result["status"])

    declaration_pass = bool(
        declaration_status == "pass"
        and expected_declaration
        and expected_declaration in declaration_paths
    )
    usage_file_pass = expected_usage_files.issubset(usage_paths)
    usage_count_pass = len(usage_paths) >= expected_min_usages
    usages_pass = usages_status == "pass" and usage_file_pass and usage_count_pass

    if declaration_pass and usages_pass:
        classification = "pass"
    elif "timeout" in {declaration_status, usages_status}:
        classification = "timeout"
    elif "error" in {declaration_status, usages_status}:
        classification = "error"
    elif "no-result" in {declaration_status, usages_status}:
        classification = "no-result-classified" if row.get("no_result_classification") else "no-result-unclassified"
    elif declaration_pass and not usages_pass:
        classification = "declaration-only"
    elif usages_pass and not declaration_pass:
        classification = "usage-only"
    elif declaration_status == "pass" and expected_declaration and expected_declaration not in declaration_paths:
        classification = "wrong-declaration-target"
    elif usages_status == "pass" and not usage_file_pass:
        classification = "incomplete-usages"
    else:
        classification = "unclassified"

    return {
        "classification": classification,
        "declaration_status": declaration_status,
        "usages_status": usages_status,
        "declaration_paths": sorted(declaration_paths),
        "usage_paths": sorted(usage_paths),
        "expected_declaration_found": declaration_pass,
        "expected_usage_files_found": sorted(expected_usage_files & usage_paths),
        "expected_usage_files_missing": sorted(expected_usage_files - usage_paths),
        "declaration_pass": declaration_pass,
        "usages_pass": usages_pass,
        "usage_path_count": len(usage_paths),
        "usage_count_pass": usage_count_pass,
    }


def execute_case(row: dict[str, str], repo: Path, timeout: float) -> dict[str, Any]:
    declaration_result = run_command(build_declaration_command(row, repo), repo, timeout)
    usages_result = run_command(build_usages_command(row), repo, timeout)
    evaluation = evaluate_case(row, repo, declaration_result, usages_result)
    return {
        "declaration_result": declaration_result,
        "usages_result": usages_result,
        "evaluation": evaluation,
        "wall_seconds": float(declaration_result["wall_seconds"]) + float(usages_result["wall_seconds"]),
    }


def build_assertions(
    rows: list[dict[str, Any]],
    declaration_threshold: int,
    usage_threshold: int,
) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    declaration_pass_count = sum(1 for row in rows if row["declaration_pass"])
    usage_pass_count = sum(1 for row in rows if row["usages_pass"])
    assertions.append(
        {
            "status": "pass" if declaration_pass_count >= declaration_threshold else "fail",
            "check": "declaration_threshold",
            "message": f"declaration_pass={declaration_pass_count} threshold={declaration_threshold}",
        }
    )
    assertions.append(
        {
            "status": "pass" if usage_pass_count >= usage_threshold else "fail",
            "check": "usage_threshold",
            "message": f"usage_pass={usage_pass_count} threshold={usage_threshold}",
        }
    )

    for row in rows:
        expected_status = str(row["expected_status"])
        classification = str(row["classification"])
        context = {"case_id": row["case_id"], "symbol": row["symbol"], "category": row["category"]}
        if expected_status == "pass":
            assertions.append(
                {
                    "status": "pass" if classification == "pass" else "fail",
                    "check": "expected_pass_case",
                    "message": f"classification={classification}",
                    "context": context,
                }
            )
        elif expected_status == "boundary":
            assertions.append(
                {
                    "status": "pass" if row["no_result_classification"] else "fail",
                    "check": "boundary_classified",
                    "message": row["no_result_classification"] or "missing boundary classification",
                    "context": context,
                }
            )
            if classification != "pass":
                assertions.append(
                    {
                        "status": "warn",
                        "check": "boundary_result",
                        "message": f"classification={classification}",
                        "context": context,
                    }
                )
        else:
            assertions.append(
                {
                    "status": "warn" if classification != "pass" else "pass",
                    "check": "probe_result",
                    "message": f"classification={classification}",
                    "context": context,
                }
            )

        if classification in {"no-result-unclassified", "error", "timeout", "unclassified"} and expected_status == "pass":
            assertions.append(
                {
                    "status": "fail",
                    "check": "unclassified_semantic_failure",
                    "message": (
                        f"declaration_status={row['declaration_status']} "
                        f"usages_status={row['usages_status']}"
                    ),
                    "context": context,
                }
            )
        elif classification in {"no-result-classified", "error", "timeout", "unclassified"}:
            assertions.append(
                {
                    "status": "warn",
                    "check": "classified_semantic_boundary",
                    "message": row["no_result_classification"] or classification,
                    "context": context,
                }
            )

        if row["expected_usage_files_missing"]:
            assertions.append(
                {
                    "status": "fail" if expected_status == "pass" else "warn",
                    "check": "expected_usage_file_overlap",
                    "message": f"missing={','.join(row['expected_usage_files_missing'])}",
                    "context": context,
                }
            )

    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {
        "summary": counts,
        "assertions": assertions,
        "declaration_pass_count": declaration_pass_count,
        "usage_pass_count": usage_pass_count,
    }


def run(args: argparse.Namespace, cases: list[dict[str, str]], repos: dict[str, Path]) -> int:
    output = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for row in cases:
        repo = repos[row["repo"]]
        result = execute_case(row, repo, args.timeout)
        base = safe_name(f"{row['repo']}_{row['case_id']}")
        declaration_stdout_path = raw_dir / f"{base}.declaration.stdout"
        declaration_stderr_path = raw_dir / f"{base}.declaration.stderr"
        usages_stdout_path = raw_dir / f"{base}.usages.stdout"
        usages_stderr_path = raw_dir / f"{base}.usages.stderr"
        declaration_stdout_path.write_text(str(result["declaration_result"]["stdout"]))
        declaration_stderr_path.write_text(str(result["declaration_result"]["stderr"]))
        usages_stdout_path.write_text(str(result["usages_result"]["stdout"]))
        usages_stderr_path.write_text(str(result["usages_result"]["stderr"]))
        evaluation = result["evaluation"]
        rows.append(
            {
                "case_id": row["case_id"],
                "repo": row["repo"],
                "project": row["project"],
                "category": row["category"],
                "symbol": row["symbol"],
                "context_file": row["context_file"],
                "expected_kind": row["expected_kind"],
                "expected_status": row["expected_status"],
                "no_result_classification": row["no_result_classification"],
                "classification": evaluation["classification"],
                "declaration_status": evaluation["declaration_status"],
                "usages_status": evaluation["usages_status"],
                "declaration_pass": evaluation["declaration_pass"],
                "usages_pass": evaluation["usages_pass"],
                "expected_declaration_file": row["expected_declaration_file"],
                "expected_declaration_found": evaluation["expected_declaration_found"],
                "expected_usage_files_missing": evaluation["expected_usage_files_missing"],
                "expected_usage_files_found": evaluation["expected_usage_files_found"],
                "usage_path_count": evaluation["usage_path_count"],
                "usage_count_pass": evaluation["usage_count_pass"],
                "declaration_paths_json": json.dumps(evaluation["declaration_paths"]),
                "usage_paths_json": json.dumps(evaluation["usage_paths"]),
                "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                "byte_count": int(result["declaration_result"]["byte_count"]) + int(result["usages_result"]["byte_count"]),
                "estimated_tokens": int(result["declaration_result"]["estimated_tokens"]) + int(result["usages_result"]["estimated_tokens"]),
                "declaration_stdout_path": str(declaration_stdout_path),
                "declaration_stderr_path": str(declaration_stderr_path),
                "usages_stdout_path": str(usages_stdout_path),
                "usages_stderr_path": str(usages_stderr_path),
                "declaration_argv_json": json.dumps(result["declaration_result"]["argv"]),
                "usages_argv_json": json.dumps(result["usages_result"]["argv"]),
                "purpose": row["purpose"],
            }
        )

    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / f"android-studio-symbol-matrix-{run_id}.tsv"
    summary_path = output / f"android-studio-symbol-matrix-summary-{run_id}.json"
    assertions_path = output / f"android-studio-symbol-matrix-assertions-{run_id}.json"
    fieldnames = list(rows[0].keys()) if rows else []
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    walls = [float(row["wall_seconds"]) for row in rows]
    assertion_payload = build_assertions(rows, args.min_declaration_pass, args.min_usage_pass)
    trusted_studio_layer = (
        assertion_payload["declaration_pass_count"] >= args.min_declaration_pass
        and assertion_payload["usage_pass_count"] >= args.min_usage_pass
        and assertion_payload["summary"]["fail"] == 0
    )
    summary = {
        "schema": "agent-code-router-kit.android-studio-symbol-matrix.v1",
        "date_utc": utc_now(),
        "case_count": len(rows),
        "trusted_studio_layer": trusted_studio_layer,
        "declaration_pass_count": assertion_payload["declaration_pass_count"],
        "usage_pass_count": assertion_payload["usage_pass_count"],
        "classification_counts": {
            key: sum(1 for row in rows if row["classification"] == key)
            for key in sorted({row["classification"] for row in rows})
        },
        "best_wall_seconds": min(walls) if walls else 0,
        "median_wall_seconds": median(walls) if walls else 0,
        "avg_wall_seconds": mean(walls) if walls else 0,
        "rows_path": str(rows_path),
        "raw_dir": str(raw_dir),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(
        json.dumps(
            {
                "schema": "agent-code-router-kit.android-studio-symbol-matrix-assertions.v1",
                "date_utc": utc_now(),
                "summary": assertion_payload["summary"],
                "declaration_pass_count": assertion_payload["declaration_pass_count"],
                "usage_pass_count": assertion_payload["usage_pass_count"],
                "assertions": assertion_payload["assertions"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    counts = assertion_payload["summary"]
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(f"Studio trusted layer: {trusted_studio_layer}")
    print(
        "Assertions: "
        f"pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}; "
        f"declaration_pass={assertion_payload['declaration_pass_count']}; "
        f"usage_pass={assertion_payload['usage_pass_count']}"
    )
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Android Studio semantic symbol matrix.")
    parser.add_argument("--cases", default="benchmarks/android/studio-symbol-matrix.sample-b2b.tsv")
    parser.add_argument("--repo", action="append", default=[], help="Repo mapping name=/path")
    parser.add_argument("--output", default="results/android/studio-symbol-matrix")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--min-declaration-pass", type=int, default=DEFAULT_DECLARATION_THRESHOLD)
    parser.add_argument("--min-usage-pass", type=int, default=DEFAULT_USAGE_THRESHOLD)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")
    if args.min_declaration_pass < 0 or args.min_usage_pass < 0:
        parser.error("thresholds must be >= 0")

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
