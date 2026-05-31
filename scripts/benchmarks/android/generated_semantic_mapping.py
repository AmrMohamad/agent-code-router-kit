#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import studio_symbol_matrix as studio_matrix  # noqa: E402


REQUIRED_COLUMNS = [
    "case_id",
    "repo",
    "project",
    "flow_type",
    "source_surface",
    "source_pattern",
    "generated_file",
    "generated_symbol",
    "usage_file",
    "usage_pattern",
    "semantic_symbol",
    "semantic_context_file",
    "expected_declaration_file",
    "expected_semantic_status",
    "build_task",
    "purpose",
]
VALID_SEMANTIC_STATUSES = {"pass", "boundary", "not-run"}


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


def file_contains(path: Path, needle: str) -> bool:
    return needle in path.read_text(errors="replace")


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
        if row.get("expected_semantic_status") not in VALID_SEMANTIC_STATUSES:
            errors.append(f"line {index}: invalid expected_semantic_status {row.get('expected_semantic_status')!r}")
        if row.get("expected_semantic_status") == "pass" and not row.get("expected_declaration_file"):
            errors.append(f"line {index}: semantic pass cases need expected_declaration_file")
        if require_repos:
            repo_name = row.get("repo", "")
            repo = repos.get(repo_name)
            if repo is None:
                errors.append(f"line {index}: repo {repo_name!r} not provided")
                continue
            if not repo.exists():
                errors.append(f"line {index}: repo path missing: {repo}")
                continue
            for column in ["source_surface", "generated_file", "usage_file", "semantic_context_file"]:
                value = row.get(column, "")
                if value and not (repo / value).exists():
                    errors.append(f"line {index}: {column} missing: {repo / value}")
            expected_declaration = row.get("expected_declaration_file", "")
            if expected_declaration and not (repo / expected_declaration).exists():
                errors.append(f"line {index}: expected_declaration_file missing: {repo / expected_declaration}")
    return errors


def run_studio_declaration(row: dict[str, str], repo: Path, timeout: float) -> dict[str, Any]:
    if row["expected_semantic_status"] == "not-run" or not row.get("semantic_symbol"):
        return {
            "argv": [],
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "wall_seconds": 0.0,
            "status": "not-run",
            "line_count": 0,
            "byte_count": 0,
            "estimated_tokens": 0,
        }
    matrix_row = {
        "project": row["project"],
        "context_file": row["semantic_context_file"],
        "symbol": row["semantic_symbol"],
    }
    return studio_matrix.run_command(studio_matrix.build_declaration_command(matrix_row, repo), repo, timeout)


def run_build_task(repo: Path, build_task: str, timeout: float) -> dict[str, Any]:
    if not build_task:
        return {
            "argv": [],
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
            "timed_out": False,
            "wall_seconds": 0.0,
            "status": "not-run",
            "byte_count": 0,
            "estimated_tokens": 0,
        }
    argv = ["./gradlew", build_task, "--no-daemon"]
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
    status = "timeout" if timed_out else "pass" if exit_code == 0 else "error"
    return {
        "argv": argv,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "status": status,
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
    }


def evaluate_case(
    row: dict[str, str],
    repo: Path,
    semantic_result: dict[str, Any],
    build_result: dict[str, Any],
) -> dict[str, Any]:
    source_path = repo / row["source_surface"]
    generated_path = repo / row["generated_file"]
    usage_path = repo / row["usage_file"]

    source_exists = source_path.exists()
    generated_exists = generated_path.exists()
    usage_exists = usage_path.exists()
    source_pattern_found = source_exists and file_contains(source_path, row["source_pattern"])
    generated_symbol_found = generated_exists and file_contains(generated_path, row["generated_symbol"])
    usage_pattern_found = usage_exists and file_contains(usage_path, row["usage_pattern"])
    discovery_pass = source_exists and generated_exists and usage_exists
    mapping_pass = source_pattern_found and generated_symbol_found and usage_pattern_found

    semantic_paths = studio_matrix.extract_repo_paths(studio_matrix.status_text(semantic_result), repo)
    expected_declaration = row.get("expected_declaration_file", "")
    semantic_status = str(semantic_result["status"])
    if row["expected_semantic_status"] == "not-run":
        semantic_pass = True
        semantic_classification = "not-run"
    elif row["expected_semantic_status"] == "pass":
        semantic_pass = semantic_status == "pass" and expected_declaration in semantic_paths
        semantic_classification = "pass" if semantic_pass else "semantic-mismatch"
    else:
        semantic_pass = semantic_status in {"no-result", "empty", "error", "pass"}
        semantic_classification = "boundary" if semantic_status != "pass" else "boundary-resolved"

    build_status = str(build_result["status"])
    build_pass = build_status in {"not-run", "pass"}
    classification = "pass" if discovery_pass and mapping_pass and semantic_pass and build_pass else "fail"
    if classification == "pass" and row["expected_semantic_status"] in {"boundary", "not-run"}:
        classification = "pass-with-boundary"

    return {
        "classification": classification,
        "discovery_pass": discovery_pass,
        "mapping_pass": mapping_pass,
        "semantic_pass": semantic_pass,
        "semantic_classification": semantic_classification,
        "build_pass": build_pass,
        "source_exists": source_exists,
        "generated_exists": generated_exists,
        "usage_exists": usage_exists,
        "source_pattern_found": source_pattern_found,
        "generated_symbol_found": generated_symbol_found,
        "usage_pattern_found": usage_pattern_found,
        "semantic_status": semantic_status,
        "semantic_paths": sorted(semantic_paths),
        "expected_declaration_found": bool(expected_declaration and expected_declaration in semantic_paths),
        "build_status": build_status,
    }


def execute_case(
    row: dict[str, str],
    repo: Path,
    studio_timeout: float,
    build_timeout: float,
    run_build_proofs: bool,
) -> dict[str, Any]:
    semantic_result = run_studio_declaration(row, repo, studio_timeout)
    build_result = run_build_task(repo, row["build_task"], build_timeout) if run_build_proofs else run_build_task(repo, "", build_timeout)
    evaluation = evaluate_case(row, repo, semantic_result, build_result)
    return {
        "semantic_result": semantic_result,
        "build_result": build_result,
        "evaluation": evaluation,
        "wall_seconds": float(semantic_result["wall_seconds"]) + float(build_result["wall_seconds"]),
    }


def build_assertions(rows: list[dict[str, Any]], min_mapping_pass: int, min_semantic_pass: int) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    mapping_pass_count = sum(1 for row in rows if row["mapping_pass"])
    semantic_pass_count = sum(1 for row in rows if row["expected_semantic_status"] == "pass" and row["semantic_classification"] == "pass")
    assertions.append(
        {
            "status": "pass" if mapping_pass_count >= min_mapping_pass else "fail",
            "check": "mapping_threshold",
            "message": f"mapping_pass={mapping_pass_count} threshold={min_mapping_pass}",
        }
    )
    assertions.append(
        {
            "status": "pass" if semantic_pass_count >= min_semantic_pass else "fail",
            "check": "semantic_threshold",
            "message": f"semantic_pass={semantic_pass_count} threshold={min_semantic_pass}",
        }
    )
    for row in rows:
        context = {"case_id": row["case_id"], "flow_type": row["flow_type"]}
        assertions.append(
            {
                "status": "pass" if row["discovery_pass"] else "fail",
                "check": "discovery_proof",
                "message": (
                    f"source={row['source_exists']} generated={row['generated_exists']} "
                    f"usage={row['usage_exists']}"
                ),
                "context": context,
            }
        )
        assertions.append(
            {
                "status": "pass" if row["mapping_pass"] else "fail",
                "check": "mapping_proof",
                "message": (
                    f"source_pattern={row['source_pattern_found']} "
                    f"generated_symbol={row['generated_symbol_found']} "
                    f"usage_pattern={row['usage_pattern_found']}"
                ),
                "context": context,
            }
        )
        expected_semantic = row["expected_semantic_status"]
        if expected_semantic == "pass":
            assertions.append(
                {
                    "status": "pass" if row["semantic_classification"] == "pass" else "fail",
                    "check": "semantic_proof",
                    "message": f"semantic={row['semantic_classification']} status={row['semantic_status']}",
                    "context": context,
                }
            )
        elif expected_semantic == "boundary":
            assertions.append(
                {
                    "status": "warn",
                    "check": "semantic_boundary",
                    "message": f"semantic={row['semantic_classification']} status={row['semantic_status']}",
                    "context": context,
                }
            )
        else:
            assertions.append(
                {
                    "status": "warn",
                    "check": "semantic_not_run",
                    "message": "semantic proof intentionally not run for this generated flow",
                    "context": context,
                }
            )
        if not row["build_pass"]:
            assertions.append(
                {
                    "status": "fail",
                    "check": "build_proof",
                    "message": f"build_status={row['build_status']}",
                    "context": context,
                }
            )
        elif row["build_status"] == "not-run":
            assertions.append(
                {
                    "status": "warn",
                    "check": "build_proof_not_run",
                    "message": "build proof was not requested for this run",
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
        "mapping_pass_count": mapping_pass_count,
        "semantic_pass_count": semantic_pass_count,
    }


def run(args: argparse.Namespace, cases: list[dict[str, str]], repos: dict[str, Path]) -> int:
    output = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    for row in cases:
        repo = repos[row["repo"]]
        result = execute_case(row, repo, args.studio_timeout, args.build_timeout, args.run_build_proofs)
        base = safe_name(f"{row['repo']}_{row['case_id']}")
        semantic_stdout_path = raw_dir / f"{base}.semantic.stdout"
        semantic_stderr_path = raw_dir / f"{base}.semantic.stderr"
        build_stdout_path = raw_dir / f"{base}.build.stdout"
        build_stderr_path = raw_dir / f"{base}.build.stderr"
        semantic_stdout_path.write_text(str(result["semantic_result"]["stdout"]))
        semantic_stderr_path.write_text(str(result["semantic_result"]["stderr"]))
        build_stdout_path.write_text(str(result["build_result"]["stdout"]))
        build_stderr_path.write_text(str(result["build_result"]["stderr"]))
        evaluation = result["evaluation"]
        rows.append(
            {
                "case_id": row["case_id"],
                "repo": row["repo"],
                "project": row["project"],
                "flow_type": row["flow_type"],
                "expected_semantic_status": row["expected_semantic_status"],
                "classification": evaluation["classification"],
                "discovery_pass": evaluation["discovery_pass"],
                "mapping_pass": evaluation["mapping_pass"],
                "semantic_classification": evaluation["semantic_classification"],
                "semantic_status": evaluation["semantic_status"],
                "semantic_pass": evaluation["semantic_pass"],
                "build_status": evaluation["build_status"],
                "build_pass": evaluation["build_pass"],
                "source_exists": evaluation["source_exists"],
                "generated_exists": evaluation["generated_exists"],
                "usage_exists": evaluation["usage_exists"],
                "source_pattern_found": evaluation["source_pattern_found"],
                "generated_symbol_found": evaluation["generated_symbol_found"],
                "usage_pattern_found": evaluation["usage_pattern_found"],
                "semantic_paths_json": json.dumps(evaluation["semantic_paths"]),
                "expected_declaration_file": row["expected_declaration_file"],
                "expected_declaration_found": evaluation["expected_declaration_found"],
                "source_surface": row["source_surface"],
                "generated_file": row["generated_file"],
                "usage_file": row["usage_file"],
                "semantic_symbol": row["semantic_symbol"],
                "build_task": row["build_task"],
                "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                "byte_count": int(result["semantic_result"]["byte_count"]) + int(result["build_result"]["byte_count"]),
                "estimated_tokens": int(result["semantic_result"]["estimated_tokens"]) + int(result["build_result"]["estimated_tokens"]),
                "semantic_stdout_path": str(semantic_stdout_path),
                "semantic_stderr_path": str(semantic_stderr_path),
                "build_stdout_path": str(build_stdout_path),
                "build_stderr_path": str(build_stderr_path),
                "semantic_argv_json": json.dumps(result["semantic_result"]["argv"]),
                "build_argv_json": json.dumps(result["build_result"]["argv"]),
                "purpose": row["purpose"],
            }
        )

    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / f"android-generated-semantic-mapping-{run_id}.tsv"
    summary_path = output / f"android-generated-semantic-mapping-summary-{run_id}.json"
    assertions_path = output / f"android-generated-semantic-mapping-assertions-{run_id}.json"
    fieldnames = list(rows[0].keys()) if rows else []
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    assertion_payload = build_assertions(rows, args.min_mapping_pass, args.min_semantic_pass)
    walls = [float(row["wall_seconds"]) for row in rows]
    summary = {
        "schema": "agent-code-router-kit.android-generated-semantic-mapping.v1",
        "date_utc": utc_now(),
        "case_count": len(rows),
        "mapping_pass_count": assertion_payload["mapping_pass_count"],
        "semantic_pass_count": assertion_payload["semantic_pass_count"],
        "classification_counts": {
            key: sum(1 for row in rows if row["classification"] == key)
            for key in sorted({row["classification"] for row in rows})
        },
        "semantic_classification_counts": {
            key: sum(1 for row in rows if row["semantic_classification"] == key)
            for key in sorted({row["semantic_classification"] for row in rows})
        },
        "build_proofs_requested": args.run_build_proofs,
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
                "schema": "agent-code-router-kit.android-generated-semantic-mapping-assertions.v1",
                "date_utc": utc_now(),
                "summary": assertion_payload["summary"],
                "mapping_pass_count": assertion_payload["mapping_pass_count"],
                "semantic_pass_count": assertion_payload["semantic_pass_count"],
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
    print(
        "Assertions: "
        f"pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}; "
        f"mapping_pass={assertion_payload['mapping_pass_count']}; "
        f"semantic_pass={assertion_payload['semantic_pass_count']}"
    )
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Map Android generated-source surfaces to generated files and semantics.")
    parser.add_argument("--cases", default="benchmarks/android/generated-semantic-mapping.sample-b2b.tsv")
    parser.add_argument("--repo", action="append", default=[], help="Repo mapping name=/path")
    parser.add_argument("--output", default="results/android/generated-semantic-mapping")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--studio-timeout", type=float, default=60.0)
    parser.add_argument("--build-timeout", type=float, default=240.0)
    parser.add_argument("--run-build-proofs", action="store_true")
    parser.add_argument("--min-mapping-pass", type=int, default=5)
    parser.add_argument("--min-semantic-pass", type=int, default=2)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.studio_timeout <= 0 or args.build_timeout <= 0:
        parser.error("timeouts must be > 0")
    if args.min_mapping_pass < 0 or args.min_semantic_pass < 0:
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
