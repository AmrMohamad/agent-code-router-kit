#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = [
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

VALID_FIRST_TOOLS = {
    "serena_kotlin_lsp",
    "serena_json_lsp",
    "android_studio_usages",
    "grouped_summary",
    "rg_fd",
    "graphql_workbench_rg_fd",
    "fd_rg_gradle_mapping",
    "ast_grep",
    "gradle_android_runtime",
    "rg_fd_then_semantic_disambiguation",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise SystemExit(f"schema mismatch: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise SystemExit("case manifest is empty")
    return rows


def validate_cases(cases: list[dict[str, str]]) -> list[str]:
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
        if row.get("expected_first_tool") not in VALID_FIRST_TOOLS:
            errors.append(f"line {index}: invalid expected_first_tool {row.get('expected_first_tool')!r}")
        try:
            forbidden = json.loads(row.get("forbidden_first_tools_json", ""))
        except json.JSONDecodeError as exc:
            errors.append(f"line {index}: invalid forbidden_first_tools_json: {exc}")
        else:
            if not isinstance(forbidden, list) or not all(isinstance(item, str) for item in forbidden):
                errors.append(f"line {index}: forbidden_first_tools_json must decode to a list of strings")
    return errors


def load_observed_log(path: Path) -> dict[str, dict[str, str]]:
    if path.suffix == ".json":
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            data = data.get("observations", data.get("rows", []))
        if not isinstance(data, list):
            raise SystemExit("observed JSON must be a list or an object with observations/rows")
        rows = data
    else:
        with path.open(newline="") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))

    observed: dict[str, dict[str, str]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise SystemExit(f"observed row {index}: expected object")
        case_id = str(row.get("case_id", ""))
        first_tool = str(row.get("observed_first_tool", ""))
        if not case_id:
            raise SystemExit(f"observed row {index}: missing case_id")
        if not first_tool:
            raise SystemExit(f"observed row {index}: missing observed_first_tool")
        if first_tool not in VALID_FIRST_TOOLS:
            raise SystemExit(f"observed row {index}: invalid observed_first_tool {first_tool!r}")
        observed[case_id] = {
            "observed_first_tool": first_tool,
            "observed_notes": str(row.get("observed_notes", "")),
        }
    return observed


def classify_prompt(prompt: str) -> dict[str, str]:
    lowered = prompt.lower()
    broad_symbols = (
        "usecase",
        "viewmodel",
        "repository",
        "manager",
        "service",
        "module",
        "provider",
        "graphqlclient",
        "mapper",
        "navigator",
        "route",
        "state",
        "event",
        "dao",
    )
    known_symbols = (
        "samplefeatureviewmodel",
        "samplegraphqlclient",
        "graphqlclient",
        "samplecontentviewmodel",
        "samplepushservice",
        "cartviewmodel",
        "productdetailsviewmodel",
        "fetchnotificationsusecase",
        "handlenotificationclick",
        "baseviewmodel",
        "brandsdao",
    )

    if "serena references returned empty" in lowered and "studio" in lowered:
        return {
            "intent": "semantic_disagreement",
            "first_tool": "android_studio_usages",
            "proof_layer": "reference_proof",
            "summary_mode": "focused_symbol",
        }
    if "studio usage" in lowered or "studio find-usages" in lowered or "android studio usages" in lowered:
        return {
            "intent": "studio_semantic_comparison",
            "first_tool": "android_studio_usages",
            "proof_layer": "reference_proof",
            "summary_mode": "focused_symbol",
        }
    if any(
        token in lowered
        for token in (
            "assemble",
            "install",
            "launch",
            "emulator",
            "adb",
            "apk builds",
            "logcat",
            "crash",
            "unit test",
            "connectedandroidtest",
            "screenshot",
        )
    ):
        return {
            "intent": "build_runtime",
            "first_tool": "gradle_android_runtime",
            "proof_layer": "build_proof" if "assemble" in lowered or "build" in lowered or "unit test" in lowered else "runtime_proof",
            "summary_mode": "not_applicable",
        }
    if any(
        token in lowered
        for token in (
            "@composable",
            ".collect",
            "pattern",
            "migration scope",
            "matching",
            "@inject",
            "@hiltviewmodel",
            "plugins {",
            "gradle plugin block",
            "withcontext(dispatchers.main)",
            "koin module",
            "module {",
        )
    ):
        return {
            "intent": "structural_pattern",
            "first_tool": "ast_grep",
            "proof_layer": "structural_scope",
            "summary_mode": "grouped_counts",
        }
    if any(token in lowered for token in ("graphql operation", "validate the graphql", "graphql schema", "graphql query", "graphql mutation", "graphql fragment")):
        return {
            "intent": "graphql_surface",
            "first_tool": "graphql_workbench_rg_fd",
            "proof_layer": "query_schema_proof",
            "summary_mode": "focused_ranges",
        }
    if "json" in lowered and any(token in lowered for token in ("diagnostic", "diagnostics", "schema", "structure", "validate json")):
        return {
            "intent": "json_structure",
            "first_tool": "serena_json_lsp",
            "proof_layer": "json_diagnostics",
            "summary_mode": "focused_ranges",
        }
    if "proguard" in lowered or "r8" in lowered:
        return {
            "intent": "literal_resource",
            "first_tool": "rg_fd",
            "proof_layer": "discovery",
            "summary_mode": "focused_ranges",
        }
    if any(
        token in lowered
        for token in (
            "generated",
            "buildconfig",
            "ksp",
            "kapt",
            "hilt",
            "room",
            "apollo generated",
            "generated r",
            "r class",
            "safe args",
            "viewbinding",
            "data binding",
        )
    ):
        return {
            "intent": "generated_surface",
            "first_tool": "fd_rg_gradle_mapping",
            "proof_layer": "generated_mapping",
            "summary_mode": "focused_ranges",
        }
    if any(
        token in lowered
        for token in (
            "xml",
            "layout",
            "resource",
            "manifest",
            "deep link",
            "string",
            "analytics key",
            "feature flag",
            "localization",
            "navigation graph",
            "sharedpreferences",
            "shared preferences",
            "datastore",
            "version catalog",
            "libs.versions.toml",
            "permission",
        )
    ):
        return {
            "intent": "literal_resource",
            "first_tool": "rg_fd",
            "proof_layer": "discovery",
            "summary_mode": "focused_ranges",
        }
    if any(symbol in lowered for symbol in broad_symbols) and any(token in lowered for token in ("all usages", "where", "across", "understand")):
        return {
            "intent": "high_fanout_symbol",
            "first_tool": "grouped_summary",
            "proof_layer": "review_scope",
            "summary_mode": "grouped_counts",
        }
    if any(symbol in lowered for symbol in known_symbols):
        proof_layer = "semantic_diagnostics" if "diagnostic" in lowered else "semantic_identity"
        if "implementation" in lowered or "implementations" in lowered:
            proof_layer = "semantic_implementation"
        return {
            "intent": "known_symbol",
            "first_tool": "serena_kotlin_lsp",
            "proof_layer": proof_layer,
            "summary_mode": "focused_symbol",
        }
    return {
        "intent": "vague_discovery",
        "first_tool": "rg_fd_then_semantic_disambiguation",
        "proof_layer": "discovery_then_semantic",
        "summary_mode": "focused_ranges",
    }


def build_assertions(rows: list[dict[str, Any]], *, require_observed: bool = False) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []

    def add(status: str, check: str, message: str, case_id: str) -> None:
        assertions.append({"status": status, "check": check, "message": message, "context": {"case_id": case_id}})

    for row in rows:
        case_id = row["case_id"]
        add(
            "pass" if row["actual_intent"] == row["expected_intent"] else "fail",
            "intent",
            f"expected={row['expected_intent']} actual={row['actual_intent']}",
            case_id,
        )
        add(
            "pass" if row["actual_first_tool"] == row["expected_first_tool"] else "fail",
            "first_tool",
            f"expected={row['expected_first_tool']} actual={row['actual_first_tool']}",
            case_id,
        )
        add(
            "pass" if row["actual_proof_layer"] == row["expected_proof_layer"] else "fail",
            "proof_layer",
            f"expected={row['expected_proof_layer']} actual={row['actual_proof_layer']}",
            case_id,
        )
        add(
            "pass" if row["actual_summary_mode"] == row["expected_summary_mode"] else "fail",
            "summary_mode",
            f"expected={row['expected_summary_mode']} actual={row['actual_summary_mode']}",
            case_id,
        )
        forbidden = set(json.loads(row["forbidden_first_tools_json"]))
        add(
            "pass" if row["actual_first_tool"] not in forbidden else "fail",
            "forbidden_first_tool_absent",
            f"actual={row['actual_first_tool']} forbidden={sorted(forbidden)}",
            case_id,
        )
        observed_first_tool = row.get("observed_first_tool", "")
        if observed_first_tool:
            add(
                "pass" if observed_first_tool == row["expected_first_tool"] else "fail",
                "observed_first_tool",
                f"expected={row['expected_first_tool']} observed={observed_first_tool}",
                case_id,
            )
        elif require_observed:
            add(
                "fail",
                "observed_first_tool_present",
                "missing observed_first_tool for live behavior scoring",
                case_id,
            )

    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions}


def run(args: argparse.Namespace, cases: list[dict[str, str]]) -> int:
    observed = load_observed_log(Path(args.observed_log).expanduser().resolve()) if args.observed_log else {}
    rows: list[dict[str, Any]] = []
    for row in cases:
        prediction = classify_prompt(row["task_prompt"])
        observed_row = observed.get(row["case_id"], {})
        rows.append(
            {
                **row,
                "actual_intent": prediction["intent"],
                "actual_first_tool": prediction["first_tool"],
                "actual_proof_layer": prediction["proof_layer"],
                "actual_summary_mode": prediction["summary_mode"],
                "observed_first_tool": observed_row.get("observed_first_tool", ""),
                "observed_notes": observed_row.get("observed_notes", ""),
            }
        )

    assertions = build_assertions(rows, require_observed=args.require_observed)
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    rows_path = output / f"android-agent-behavior-{run_id}.tsv"
    summary_path = output / f"android-agent-behavior-summary-{run_id}.json"
    assertions_path = output / f"android-agent-behavior-assertions-{run_id}.json"
    with rows_path.open("w", newline="") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    first_tool_counts: dict[str, int] = {}
    for row in rows:
        first_tool_counts[row["actual_first_tool"]] = first_tool_counts.get(row["actual_first_tool"], 0) + 1
    summary = {
        "schema": "agent-code-router-kit.android-agent-behavior.v1",
        "date_utc": utc_now(),
        "scope": "Policy-proxy Android routing behavior gate; not live Codex model proof.",
        "case_count": len(rows),
        "observed_case_count": sum(1 for row in rows if row.get("observed_first_tool")),
        "minimum_observed_cases_for_readiness": int(args.min_observed_cases_for_readiness),
        "observed_required": bool(args.require_observed),
        "assertions": assertions["summary"],
        "first_tool_counts": first_tool_counts,
        "rows_path": str(rows_path),
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n")
    counts = assertions["summary"]
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}; first_tools={first_tool_counts}")
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Android routing behavior policy-proxy gate.")
    parser.add_argument("--cases", default="benchmarks/android/agent-behavior.sample-b2b.tsv")
    parser.add_argument("--output", default="results/android/agent-behavior")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--enforce-assertions", action="store_true")
    parser.add_argument("--observed-log", help="Optional JSON/TSV live-agent first-tool observations keyed by case_id.")
    parser.add_argument("--require-observed", action="store_true", help="Fail if any case lacks an observed_first_tool.")
    parser.add_argument("--min-observed-cases-for-readiness", type=int, default=10, help="Minimum live observations before readiness audit can treat behavior evidence as readiness-satisfied.")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    cases = load_cases(Path(args.cases))
    errors = validate_cases(cases)
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases")
    if args.run:
        return run(args, cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
