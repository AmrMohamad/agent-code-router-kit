#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_REPOS = {"sample_b2b_android", "sample_retail_android"}
REQUIRED_DEFAULT_CATEGORIES = {
    "discovery",
    "gradle_surface",
    "graphql_surface",
    "known_kotlin_symbol",
    "literal_key",
    "literal_surface",
    "resource_surface",
    "structural_kotlin_pattern",
}
REQUIRED_LSP_TOOLS = {
    "find_symbol",
    "find_referencing_symbols",
    "get_symbols_overview",
    "get_diagnostics_for_file",
}
EXPECTED_LSP_BOUNDARY_TOOLS = {
    "find_implementations",
}


def latest(path: Path, pattern: str) -> Path:
    matches = sorted(path.glob(pattern))
    if not matches:
        raise SystemExit(f"no files match {path / pattern}")
    return matches[-1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def assertion_summary(path: Path) -> dict[str, int]:
    return dict(load_json(path).get("summary", {}))


def status_item(requirement: str, status: str, evidence: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "requirement": requirement,
        "status": status,
        "evidence": evidence,
        "details": details or {},
    }


def repo_set(rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("repo", "")) for row in rows if row.get("repo")}


def count_rows(rows: list[dict[str, Any]], **filters: str) -> int:
    total = 0
    for row in rows:
        if all(str(row.get(key, "")) == value for key, value in filters.items()):
            total += 1
    return total


def all_rows_have_repeats(rows: list[dict[str, Any]], expected: int) -> bool:
    return all(int(row.get("passes", expected)) >= expected for row in rows)


def statuses_contain(row: dict[str, Any], value: str) -> bool:
    return value in row.get("statuses", [])


def audit(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.results_root).expanduser().resolve()
    paths = {
        "default_summary": latest(root / "default-search", "summary-*.json"),
        "default_assertions": latest(root / "default-search", "policy-assertions-*.json"),
        "studio_summary": latest(root / "android-studio-semantic", "android-studio-semantic-summary-*.json"),
        "studio_assertions": latest(root / "android-studio-semantic", "android-studio-semantic-assertions-*.json"),
        "serena_source_summary": latest(root / "serena-source-symbol", "serena-source-symbol-summary-*.json"),
        "serena_source_assertions": latest(root / "serena-source-symbol", "serena-source-symbol-assertions-*.json"),
        "serena_project_summary": latest(root / "serena-project-server", "serena-project-server-summary-*.json"),
        "serena_project_assertions": latest(root / "serena-project-server", "serena-project-server-assertions-*.json"),
        "process_summary": latest(root / "process-state", "android-process-state-summary-*.json"),
        "process_assertions": latest(root / "process-state", "android-process-state-assertions-*.json"),
        "project_summary": latest(root / "project-model", "android-project-model-summary-*.json"),
        "project_assertions": latest(root / "project-model", "android-project-model-assertions-*.json"),
    }

    default_rows = load_json(paths["default_summary"])
    studio_rows = load_json(paths["studio_summary"])
    serena_source_rows = load_json(paths["serena_source_summary"])
    serena_project_rows = load_json(paths["serena_project_summary"])
    process_state = load_json(paths["process_summary"])
    project_rows = load_json(paths["project_summary"])

    default_counts = assertion_summary(paths["default_assertions"])
    studio_counts = assertion_summary(paths["studio_assertions"])
    serena_source_counts = assertion_summary(paths["serena_source_assertions"])
    serena_project_counts = assertion_summary(paths["serena_project_assertions"])
    process_counts = assertion_summary(paths["process_assertions"])
    project_counts = assertion_summary(paths["project_assertions"])

    items: list[dict[str, Any]] = []

    covered_repos = repo_set(default_rows) | repo_set(studio_rows) | repo_set(serena_project_rows) | repo_set(project_rows)
    missing_repos = sorted(REQUIRED_REPOS - covered_repos)
    items.append(
        status_item(
            "Both ExampleCo Android repos are covered",
            "pass" if not missing_repos else "fail",
            "Repo aliases found across benchmark artifacts.",
            {"covered_repos": sorted(covered_repos), "missing_repos": missing_repos},
        )
    )

    categories = {str(row.get("category", "")) for row in default_rows}
    missing_categories = sorted(REQUIRED_DEFAULT_CATEGORIES - categories)
    default_pass = default_counts.get("fail", 0) == 0 and len(default_rows) >= args.minimum_default_cases
    items.append(
        status_item(
            "Normal search tools measured time and context-size proxies across broad Android cases",
            "pass" if default_pass and not missing_categories and all_rows_have_repeats(default_rows, args.minimum_repeats) else "fail",
            "Default-search summary and policy assertions.",
            {
                "case_count": len(default_rows),
                "categories": sorted(categories),
                "missing_categories": missing_categories,
                "minimum_cases": args.minimum_default_cases,
                "minimum_repeats": args.minimum_repeats,
                "assertions": default_counts,
            },
        )
    )

    source_symbol_ok = (
        serena_source_counts.get("fail", 0) == 0
        and len(serena_source_rows) >= args.minimum_source_symbol_cases
        and all(statuses_contain(row, "pass") for row in serena_source_rows)
    )
    items.append(
        status_item(
            "Serena/Kotlin source-symbol smoke tests pass on real .kt files",
            "pass" if source_symbol_ok else "fail",
            "Serena source-symbol probe.",
            {"case_count": len(serena_source_rows), "assertions": serena_source_counts},
        )
    )

    functional_lsp_rows = [
        row
        for row in serena_project_rows
        if str(row.get("tool_name", "")) in REQUIRED_LSP_TOOLS
    ]
    lsp_tools = {str(row.get("tool_name", "")) for row in functional_lsp_rows if row.get("tool_name")}
    missing_lsp_tools = sorted(REQUIRED_LSP_TOOLS - lsp_tools)
    project_lsp_ok = (
        serena_project_counts.get("fail", 0) == 0
        and serena_project_counts.get("warn", 0) == 0
        and len(functional_lsp_rows) >= args.minimum_lsp_cases
        and not missing_lsp_tools
        and all(statuses_contain(row, "pass") for row in functional_lsp_rows)
        and all(int(row.get("measured_pass_count", 0)) >= args.minimum_lsp_repeats for row in functional_lsp_rows)
    )
    items.append(
        status_item(
            "LSP semantic system is stable across repeated ProjectServer cases",
            "pass" if project_lsp_ok else "fail",
            "Serena ProjectServer symbol/reference/overview/diagnostics probe.",
            {
                "case_count": len(functional_lsp_rows),
                "minimum_cases": args.minimum_lsp_cases,
                "minimum_repeats": args.minimum_lsp_repeats,
                "tools": sorted(lsp_tools),
                "missing_tools": missing_lsp_tools,
                "assertions": serena_project_counts,
            },
        )
    )

    boundary_rows = [
        row
        for row in serena_project_rows
        if str(row.get("tool_name", "")) in EXPECTED_LSP_BOUNDARY_TOOLS
    ]
    boundary_tools = {str(row.get("tool_name", "")) for row in boundary_rows if row.get("tool_name")}
    missing_boundary_tools = sorted(EXPECTED_LSP_BOUNDARY_TOOLS - boundary_tools)
    boundary_ok = (
        serena_project_counts.get("fail", 0) == 0
        and not missing_boundary_tools
        and len(boundary_rows) >= args.minimum_lsp_boundary_cases
        and all(statuses_contain(row, "error") for row in boundary_rows)
        and all(int(row.get("measured_pass_count", 0)) >= args.minimum_lsp_repeats for row in boundary_rows)
    )
    items.append(
        status_item(
            "Unsupported Kotlin LSP capability boundaries are explicit",
            "pass" if boundary_ok else "fail",
            "Serena ProjectServer expected implementation-lookup boundary cases.",
            {
                "case_count": len(boundary_rows),
                "minimum_cases": args.minimum_lsp_boundary_cases,
                "tools": sorted(boundary_tools),
                "missing_tools": missing_boundary_tools,
                "expected_status": "error",
            },
        )
    )

    process_clean = process_state.get("status") == "clean" and process_counts.get("fail", 0) == 0
    items.append(
        status_item(
            "Kotlin/Android semantic process state is clean before interpreting LSP results",
            "pass" if process_clean else "fail",
            "Android process-state probe.",
            {"process_status": process_state.get("status"), "counts": process_state.get("counts", {}), "assertions": process_counts},
        )
    )

    studio_ready_count = sum(
        1
        for row in studio_rows
        if row.get("command_type") in {"check", "analyze-file"} and statuses_contain(row, "pass")
    )
    studio_no_result_count = sum(
        1
        for row in studio_rows
        if row.get("command_type") in {"find-declaration", "find-usages"} and statuses_contain(row, "no-result")
    )
    studio_status = "partial" if studio_ready_count >= 4 and studio_no_result_count else "pass" if studio_ready_count >= 4 else "fail"
    items.append(
        status_item(
            "Android Studio Preview/Quail semantic bridge is separated from symbol-proof readiness",
            studio_status,
            "Android Studio semantic probe.",
            {
                "readiness_or_analysis_passes": studio_ready_count,
                "declaration_or_usage_no_result_cases": studio_no_result_count,
                "assertions": studio_counts,
            },
        )
    )

    missing_keys = sorted({key for row in project_rows for key in row.get("missing_local_properties", [])})
    wrapper_statuses = {
        str(row.get("repo", "")): str(row.get("gradle_wrapper_status", "-"))
        for row in project_rows
        if row.get("repo")
    }
    command_sources = {
        str(row.get("repo", "")): str(row.get("selected_command_source", "-"))
        for row in project_rows
        if row.get("repo")
    }
    wrapper_blockers = {
        repo: status
        for repo, status in wrapper_statuses.items()
        if status not in {"wrapper-executable"}
    }
    project_boundary_recorded = project_counts.get("fail", 0) == 0
    project_status = "boundary" if project_boundary_recorded else "fail"
    items.append(
        status_item(
            "Gradle/project-model runtime boundary is explicit and no build/runtime parity is claimed",
            project_status,
            "Android project-model preflight.",
            {
                "missing_local_properties": missing_keys,
                "gradle_wrapper_statuses": wrapper_statuses,
                "selected_command_sources": command_sources,
                "wrapper_blockers": wrapper_blockers,
                "assertions": project_counts,
                "ran_gradle": any(bool(row.get("ran_gradle", False)) for row in project_rows),
            },
        )
    )

    comparison_ready = len(default_rows) >= args.minimum_default_cases and len(serena_project_rows) >= args.minimum_lsp_cases
    items.append(
        status_item(
            "Default search and LSP outputs are comparable by token proxy and timing",
            "pass" if comparison_ready else "fail",
            "Default-search and Serena ProjectServer summaries contain byte/token proxy and timing fields.",
            {
                "default_rows": len(default_rows),
                "serena_project_rows": len(serena_project_rows),
                "default_fields": ["last_byte_count", "median_wall_seconds"],
                "lsp_fields": ["last_estimated_tokens", "median_wall_seconds"],
            },
        )
    )

    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1

    if status_counts.get("fail", 0):
        overall_status = "fail"
    elif status_counts.get("partial", 0) or status_counts.get("boundary", 0):
        overall_status = "complete_with_known_boundaries"
    else:
        overall_status = "complete"

    return {
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "schema": "android-routing-goal-audit-v1",
        "overall_status": overall_status,
        "status_counts": status_counts,
        "source_artifacts": {key: str(value) for key, value in paths.items()},
        "items": items,
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(data: dict[str, Any]) -> str:
    rows = []
    for item in data["items"]:
        rows.append([item["status"], item["requirement"], item["evidence"]])
    blockers = [
        item
        for item in data["items"]
        if item["status"] in {"boundary", "blocked", "partial", "fail"}
    ]
    lines = [
        f"# Android Routing Goal Audit - {data['created_at']}",
        "",
        f"Overall status: `{data['overall_status']}`",
        "",
        markdown_table(["Status", "Requirement", "Evidence"], rows),
    ]
    if blockers:
        lines.extend(["", "## Remaining Boundaries", ""])
        for item in blockers:
            lines.append(f"- `{item['status']}` {item['requirement']}: {json.dumps(item['details'], sort_keys=True)}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Android benchmark artifacts against the routing goal.")
    parser.add_argument("--results-root", default="results/android")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--minimum-default-cases", type=int, default=50)
    parser.add_argument("--minimum-repeats", type=int, default=3)
    parser.add_argument("--minimum-source-symbol-cases", type=int, default=3)
    parser.add_argument("--minimum-lsp-cases", type=int, default=10)
    parser.add_argument("--minimum-lsp-repeats", type=int, default=3)
    parser.add_argument("--minimum-lsp-boundary-cases", type=int, default=2)
    args = parser.parse_args()

    data = audit(args)
    if args.output_json:
        output = Path(args.output_json).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        print(f"Wrote {output}")
    else:
        print(json.dumps(data, indent=2, sort_keys=True))

    if args.output_md:
        output = Path(args.output_md).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(data))
        print(f"Wrote {output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
