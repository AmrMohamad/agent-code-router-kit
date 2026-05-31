#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(SCRIPT_DIR))
import studio_semantic_probe as studio_probe  # noqa: E402
import serena_project_server_probe as serena_probe  # noqa: E402


REQUIRED_COLUMNS = [
    "case_id",
    "repo",
    "serena_project",
    "studio_project",
    "symbol_label",
    "find_symbol_params_json",
    "reference_params_json",
    "studio_symbol",
    "studio_context_file",
    "expected_classification",
    "expected_studio_files_json",
    "purpose",
]
VALID_CLASSIFICATIONS = {
    "probe",
    "fixed",
    "query-shape issue",
    "stale-index issue",
    "transport/process issue",
    "kotlin-lsp limitation",
    "serena-tool limitation",
    "serena-reference-empty-boundary",
    "studio over-reporting",
    "studio-probe unavailable",
    "unclassified disagreement",
}


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


def validate(cases: list[dict[str, str]], repos: dict[str, Path], require_repos: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(cases, start=2):
        for column in REQUIRED_COLUMNS:
            if column not in row or row[column] == "":
                errors.append(f"line {index}: missing {column}")
        case_id = row.get("case_id", "")
        if case_id in seen:
            errors.append(f"line {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        if row.get("expected_classification") not in VALID_CLASSIFICATIONS:
            errors.append(f"line {index}: invalid expected_classification {row.get('expected_classification')!r}")
        for json_column in ["find_symbol_params_json", "reference_params_json"]:
            try:
                decoded = json.loads(row.get(json_column, ""))
            except json.JSONDecodeError as exc:
                errors.append(f"line {index}: invalid {json_column}: {exc}")
                continue
            if not isinstance(decoded, dict):
                errors.append(f"line {index}: {json_column} must decode to an object")
        try:
            expected_files = json.loads(row.get("expected_studio_files_json", ""))
            if not isinstance(expected_files, list) or not all(isinstance(item, str) for item in expected_files):
                errors.append(f"line {index}: expected_studio_files_json must decode to a list of strings")
        except json.JSONDecodeError as exc:
            errors.append(f"line {index}: invalid expected_studio_files_json: {exc}")
        if require_repos:
            repo = row.get("repo", "")
            if repo not in repos:
                errors.append(f"line {index}: repo {repo!r} not provided")
            elif not repos[repo].exists():
                errors.append(f"line {index}: repo path missing: {repos[repo]}")
            else:
                for json_column in ["find_symbol_params_json", "reference_params_json"]:
                    params = json.loads(row[json_column])
                    relative_path = params.get("relative_path")
                    if isinstance(relative_path, str) and not (repos[repo] / relative_path).exists():
                        errors.append(f"line {index}: {json_column} relative_path missing: {repos[repo] / relative_path}")
                context_file = row.get("studio_context_file", "")
                if context_file and not (repos[repo] / context_file).exists():
                    errors.append(f"line {index}: studio_context_file missing: {repos[repo] / context_file}")
    return errors


def text_is_empty_semantic_result(text: str) -> bool:
    stripped = text.strip()
    if stripped in {"", "{}", "[]", "null"}:
        return True
    lowered = stripped.lower()
    return "no references found" in lowered or "no result" in lowered


def extract_paths(text: str, repo: Path) -> set[str]:
    paths: set[str] = set()
    repo_text = str(repo)
    absolute_pattern = re.compile(re.escape(repo_text) + r"/[A-Za-z0-9_./@+~-]+\.kt")
    for match in absolute_pattern.finditer(text):
        paths.add(str(Path(match.group(0)).relative_to(repo)))
    relative_pattern = re.compile(r"(?<![A-Za-z0-9_./-])([A-Za-z0-9_./@+~-]+\.kt)")
    for match in relative_pattern.finditer(text):
        raw = match.group(1).strip("./")
        if raw and (repo / raw).exists():
            paths.add(raw)
    return paths


def status_text(result: dict[str, Any]) -> str:
    return f"{result.get('stdout', '')}\n{result.get('stderr', '')}"


def run_serena_tool(
    project: str,
    tool_name: str,
    params: dict[str, Any],
    port: int,
    timeout: float,
) -> dict[str, Any]:
    row = {
        "project": project,
        "tool_name": tool_name,
        "tool_params_json": json.dumps(params),
        "min_byte_count": "1",
    }
    return serena_probe.execute(row, port, timeout)


def run_studio_usages(row: dict[str, str], repo: Path, timeout: float) -> dict[str, Any]:
    studio_row = {
        "case_id": row["case_id"],
        "repo": row["repo"],
        "project": row["studio_project"],
        "command_type": "find-usages",
        "symbol": row["studio_symbol"],
        "context_file": row["studio_context_file"],
        "expected_status": "probe",
        "purpose": row["purpose"],
    }
    return studio_probe.execute(studio_row, repo, timeout)


def normalized_studio_status(result: dict[str, Any]) -> str:
    text = status_text(result)
    if "No running Android Studio instance has project" in text:
        return "error"
    if text.lstrip().startswith("Error:") or "\nError:" in text:
        return "error"
    return str(result["status"])


def classify_case(
    find_result: dict[str, Any],
    reference_result: dict[str, Any],
    studio_result: dict[str, Any],
    serena_reference_paths: set[str],
    studio_paths: set[str],
) -> str:
    find_status = str(find_result["status"])
    ref_status = str(reference_result["status"])
    studio_status = str(studio_result["status"])
    ref_text = status_text(reference_result)
    overlap = serena_reference_paths & studio_paths

    if ref_status == "timeout" or find_status == "timeout":
        return "transport/process issue"
    if ref_status == "error":
        text = ref_text.lower()
        if "no symbol matching" in text or "missing 1 required positional argument" in text:
            return "query-shape issue"
        if "notundercontentroot" in text or "textdocument/references" in text:
            return "kotlin-lsp limitation"
        if "unsupported" in text or "not implemented" in text:
            return "serena-tool limitation"
        return "transport/process issue"
    if studio_status in {"timeout", "error", "no-result", "empty"}:
        return "studio-probe unavailable"
    if ref_status == "pass" and not text_is_empty_semantic_result(ref_text) and overlap:
        return "fixed"
    if ref_status == "pass" and not text_is_empty_semantic_result(ref_text) and not overlap:
        return "unclassified disagreement"
    if find_status != "pass":
        return "query-shape issue"
    if studio_status == "pass" and text_is_empty_semantic_result(ref_text):
        return "serena-reference-empty-boundary"
    return "unclassified disagreement"


def execute_case(
    row: dict[str, str],
    repo: Path,
    port: int,
    serena_timeout: float,
    studio_timeout: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    find_params = json.loads(row["find_symbol_params_json"])
    ref_params = json.loads(row["reference_params_json"])
    find_result = run_serena_tool(row["serena_project"], "find_symbol", find_params, port, serena_timeout)
    reference_result = run_serena_tool(row["serena_project"], "find_referencing_symbols", ref_params, port, serena_timeout)
    studio_result = run_studio_usages(row, repo, studio_timeout)
    studio_result["status"] = normalized_studio_status(studio_result)
    wall = time.perf_counter() - started

    find_text = status_text(find_result)
    reference_text = status_text(reference_result)
    studio_text = status_text(studio_result)
    serena_find_paths = extract_paths(find_text, repo)
    serena_reference_paths = extract_paths(reference_text, repo)
    studio_paths = extract_paths(studio_text, repo)
    expected_studio_files = set(json.loads(row["expected_studio_files_json"]))
    classification = classify_case(find_result, reference_result, studio_result, serena_reference_paths, studio_paths)

    return {
        "wall_seconds": wall,
        "find_result": find_result,
        "reference_result": reference_result,
        "studio_result": studio_result,
        "serena_find_paths": sorted(serena_find_paths),
        "serena_reference_paths": sorted(serena_reference_paths),
        "studio_paths": sorted(studio_paths),
        "overlap_paths": sorted(serena_reference_paths & studio_paths),
        "expected_studio_files_found": sorted(expected_studio_files & studio_paths),
        "expected_studio_files_missing": sorted(expected_studio_files - studio_paths),
        "classification": classification,
        "estimated_tokens": estimate_tokens(find_text + reference_text + studio_text),
        "byte_count": len((find_text + reference_text + studio_text).encode()),
    }


def build_assertions(rows: list[dict[str, Any]]) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    for row in rows:
        expected = str(row["expected_classification"])
        classification = str(row["classification"])
        expected_ok = expected == "probe" or expected == classification
        assertions.append(
            {
                "status": "pass" if expected_ok else "fail",
                "check": "expected_classification",
                "message": f"expected={expected} actual={classification}",
                "context": {"case_id": row["case_id"]},
            }
        )
        assertions.append(
            {
                "status": "pass" if row["studio_status"] == "pass" else "warn",
                "check": "studio_usages_available",
                "message": f"status={row['studio_status']}",
                "context": {"case_id": row["case_id"]},
            }
        )
        assertions.append(
            {
                "status": "pass" if not row["expected_studio_files_missing"] else "warn",
                "check": "expected_studio_file_overlap",
                "message": f"missing={','.join(row['expected_studio_files_missing']) or 'none'}",
                "context": {"case_id": row["case_id"]},
            }
        )
        if row["classification"] == "serena-reference-empty-boundary":
            assertions.append(
                {
                    "status": "warn",
                    "check": "serena_reference_empty_boundary",
                    "message": "Serena references returned empty while Studio usages found expected files.",
                    "context": {"case_id": row["case_id"]},
                }
            )
        elif row["classification"] == "unclassified disagreement":
            assertions.append(
                {
                    "status": "warn",
                    "check": "serena_studio_disagreement",
                    "message": "Serena references did not overlap Studio usages.",
                    "context": {"case_id": row["case_id"]},
                }
            )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions}


def overall_classification(rows: list[dict[str, Any]]) -> str:
    classifications = {str(row["classification"]) for row in rows}
    if "fixed" in classifications:
        return "fixed"
    if "transport/process issue" in classifications and len(classifications) == 1:
        return "transport/process issue"
    if "query-shape issue" in classifications and len(classifications) == 1:
        return "query-shape issue"
    if "serena-tool limitation" in classifications and len(classifications) == 1:
        return "serena-tool limitation"
    if "serena-reference-empty-boundary" in classifications and len(classifications) == 1:
        return "serena-reference-empty-boundary"
    if "studio-probe unavailable" in classifications and len(classifications) == 1:
        return "studio-probe unavailable"
    return "unclassified disagreement"


def run(args: argparse.Namespace, cases: list[dict[str, str]], repos: dict[str, Path]) -> int:
    output = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    server = serena_probe.start_server(args.port, args.startup_timeout)
    rows: list[dict[str, Any]] = []
    try:
        for row in cases:
            repo = repos[row["repo"]]
            result = execute_case(row, repo, args.port, args.serena_timeout, args.studio_timeout)
            base = safe_name(f"{row['repo']}_{row['case_id']}")
            find_stdout_path = raw_dir / f"{base}.serena-find.stdout"
            find_stderr_path = raw_dir / f"{base}.serena-find.stderr"
            reference_stdout_path = raw_dir / f"{base}.serena-references.stdout"
            reference_stderr_path = raw_dir / f"{base}.serena-references.stderr"
            studio_stdout_path = raw_dir / f"{base}.studio-usages.stdout"
            studio_stderr_path = raw_dir / f"{base}.studio-usages.stderr"
            find_stdout_path.write_text(str(result["find_result"]["stdout"]))
            find_stderr_path.write_text(str(result["find_result"]["stderr"]))
            reference_stdout_path.write_text(str(result["reference_result"]["stdout"]))
            reference_stderr_path.write_text(str(result["reference_result"]["stderr"]))
            studio_stdout_path.write_text(str(result["studio_result"]["stdout"]))
            studio_stderr_path.write_text(str(result["studio_result"]["stderr"]))
            rows.append(
                {
                    "case_id": row["case_id"],
                    "repo": row["repo"],
                    "serena_project": row["serena_project"],
                    "studio_project": row["studio_project"],
                    "symbol_label": row["symbol_label"],
                    "studio_symbol": row["studio_symbol"],
                    "expected_classification": row["expected_classification"],
                    "classification": result["classification"],
                    "find_symbol_status": result["find_result"]["status"],
                    "reference_status": result["reference_result"]["status"],
                    "studio_status": result["studio_result"]["status"],
                    "serena_reference_path_count": len(result["serena_reference_paths"]),
                    "studio_path_count": len(result["studio_paths"]),
                    "overlap_path_count": len(result["overlap_paths"]),
                    "expected_studio_files_missing": result["expected_studio_files_missing"],
                    "serena_reference_paths_json": json.dumps(result["serena_reference_paths"]),
                    "studio_paths_json": json.dumps(result["studio_paths"]),
                    "overlap_paths_json": json.dumps(result["overlap_paths"]),
                    "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                    "byte_count": result["byte_count"],
                    "estimated_tokens": result["estimated_tokens"],
                    "find_stdout_path": str(find_stdout_path),
                    "find_stderr_path": str(find_stderr_path),
                    "reference_stdout_path": str(reference_stdout_path),
                    "reference_stderr_path": str(reference_stderr_path),
                    "studio_stdout_path": str(studio_stdout_path),
                    "studio_stderr_path": str(studio_stderr_path),
                    "purpose": row["purpose"],
                }
            )
    finally:
        serena_probe.stop_server(server)

    output.mkdir(parents=True, exist_ok=True)
    rows_path = output / f"android-serena-reference-triage-{run_id}.tsv"
    summary_path = output / f"android-serena-reference-triage-summary-{run_id}.json"
    assertions_path = output / f"android-serena-reference-triage-assertions-{run_id}.json"
    fieldnames = list(rows[0].keys()) if rows else []
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    walls = [float(row["wall_seconds"]) for row in rows]
    summary = {
        "schema": "agent-code-router-kit.android-serena-reference-triage.v1",
        "date_utc": utc_now(),
        "overall_classification": overall_classification(rows),
        "case_count": len(rows),
        "classification_counts": {key: sum(1 for row in rows if row["classification"] == key) for key in sorted({row["classification"] for row in rows})},
        "best_wall_seconds": min(walls) if walls else 0,
        "median_wall_seconds": median(walls) if walls else 0,
        "avg_wall_seconds": mean(walls) if walls else 0,
        "rows_path": str(rows_path),
        "raw_dir": str(raw_dir),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertion_payload = build_assertions(rows)
    assertions_path.write_text(json.dumps(assertion_payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    counts = assertion_payload["summary"]
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}")
    print(f"Overall classification: {summary['overall_classification']}")
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Triage Serena references against Android Studio usages for Sample B2B stable.")
    parser.add_argument("--cases", default="benchmarks/android/serena-reference-triage.sample-b2b.tsv")
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--output", default="results/android/serena-reference-triage")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--port", type=int, default=24592)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--serena-timeout", type=float, default=180)
    parser.add_argument("--studio-timeout", type=float, default=60)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.startup_timeout <= 0 or args.serena_timeout <= 0 or args.studio_timeout <= 0:
        parser.error("timeouts must be > 0")
    if args.port <= 0:
        parser.error("--port must be > 0")

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
