#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def latest(path: Path, pattern: str) -> Path:
    matches = sorted(path.glob(pattern))
    if not matches:
        raise SystemExit(f"no files match {path / pattern}")
    return matches[-1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def token_proxy(byte_count: int) -> int:
    return (byte_count + 3) // 4


def assertion_summary(path: Path) -> dict[str, int]:
    data = load_json(path)
    return dict(data.get("summary", {}))


def assertion_warning_breakdown(path: Path) -> list[dict[str, Any]]:
    data = load_json(path)
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for assertion in data.get("assertions", []):
        if assertion.get("status") != "warn":
            continue
        check = str(assertion.get("check", "-"))
        message = str(assertion.get("message", "-"))
        key = (check, message)
        item = grouped.setdefault(
            key,
            {
                "check": check,
                "message": message,
                "count": 0,
                "cases": set(),
                "repos": set(),
            },
        )
        item["count"] += 1
        context = assertion.get("context", {})
        if isinstance(context, dict):
            if context.get("case_id"):
                item["cases"].add(str(context["case_id"]))
            if context.get("repo"):
                item["repos"].add(str(context["repo"]))
    rows: list[dict[str, Any]] = []
    for item in grouped.values():
        rows.append(
            {
                "check": item["check"],
                "message": item["message"],
                "count": item["count"],
                "cases": sorted(item["cases"]),
                "repos": sorted(item["repos"]),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["count"]), str(row["check"]), str(row["message"])))


def render_warning_breakdown(paths_by_layer: list[tuple[str, Path]]) -> str:
    rows: list[list[Any]] = []
    for layer, path in paths_by_layer:
        for warning in assertion_warning_breakdown(path):
            cases = ", ".join(f"`{case}`" for case in warning["cases"][:4])
            if len(warning["cases"]) > 4:
                cases += f", +{len(warning['cases']) - 4} more"
            repos = ", ".join(f"`{repo}`" for repo in warning["repos"]) or "-"
            rows.append(
                [
                    layer,
                    warning["check"],
                    warning["count"],
                    warning["message"],
                    repos,
                    cases or "-",
                ]
            )
    if not rows:
        return "\n".join(["## Warning / Blocker Breakdown", "", "No assertion warnings in the selected artifacts."])
    return "\n".join(
        [
            "## Warning / Blocker Breakdown",
            "",
            "Warnings are not benchmark failures. They mark capability boundaries or intentionally large baseline outputs that should not be used as live-agent context dumps.",
            "",
            markdown_table(["Layer", "Warning", "Count", "Message", "Repos", "Cases"], rows),
        ]
    )


def top_by_bytes(rows: list[dict[str, Any]], repo: str, limit: int = 10) -> list[dict[str, Any]]:
    filtered = [row for row in rows if row.get("repo") == repo]
    return sorted(filtered, key=lambda row: int(row.get("last_byte_count", 0)), reverse=True)[:limit]


def known_symbol_rows(rows: list[dict[str, Any]], repo: str) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in rows
        if row.get("repo") == repo
        and row.get("category") in {"known_kotlin_symbol", "known_java_symbol"}
        and "high_fanout" not in str(row.get("case_id", ""))
    ]
    return sorted(filtered, key=lambda row: str(row.get("case_id", "")))


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(out)


def fmt_seconds(value: Any) -> str:
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return "-"


def fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def by_case_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("case_id")): row for row in rows}


def render_direct_comparison(default_rows: list[dict[str, Any]], serena_project_rows: list[dict[str, Any]]) -> str:
    default_by_case = by_case_id(default_rows)
    serena_by_case = by_case_id(serena_project_rows)
    comparisons = [
        (
            "Sample B2B SampleFeatureViewModel",
            "known_symbol_notifications_viewmodel_files",
            "serena_project_find_sample_b2b_notifications_viewmodel",
            "Text search is tiny, but LSP returns owning class structure and child symbol ranges.",
        ),
        (
            "Sample B2B SampleFeatureViewModel references",
            "known_symbol_notifications_viewmodel_files",
            "serena_project_refs_sample_b2b_notifications_viewmodel",
            "LSP proves semantic references instead of only matching the ViewModel name text.",
        ),
        (
            "Sample B2B SampleContentViewModel",
            "known_symbol_dynamic_content_viewmodel_files",
            "serena_project_find_sample_b2b_dynamic_content_viewmodel",
            "Both are small; LSP adds symbol kind, owning file, and body range.",
        ),
        (
            "Sample B2B SampleContentViewModel references",
            "known_symbol_dynamic_content_viewmodel_files",
            "serena_project_refs_sample_b2b_dynamic_content_viewmodel",
            "Reference lookup stays bounded and proves semantic callers/owners.",
        ),
        (
            "Sample B2B SamplePushService",
            "known_symbol_push_service_files",
            "serena_project_find_sample_b2b_push_service",
            "Text search discovers service files; LSP proves the Android service symbol.",
        ),
        (
            "Sample B2B IUseCase",
            "known_symbol_iusecase_files",
            "serena_project_find_sample_b2b_iusecase",
            "A high-fanout base interface should be identified semantically before broad reference expansion.",
        ),
        (
            "Sample Retail BaseViewModel definition",
            "known_symbol_base_viewmodel_files",
            "serena_project_find_sample_retail_base_viewmodel",
            "LSP is smaller than the text file list and returns the exact class body range plus members.",
        ),
        (
            "Sample Retail BaseViewModel references",
            "known_symbol_base_viewmodel_files",
            "serena_project_refs_sample_retail_base_viewmodel",
            "LSP returns semantic referencing symbols with a bounded high-fanout response.",
        ),
        (
            "Sample Retail MainActivity",
            "known_symbol_main_activity_files",
            "serena_project_find_sample_retail_main_activity",
            "Text search is faster; LSP proves the class identity and child structure.",
        ),
        (
            "Sample Retail MainNavHost",
            "known_symbol_main_nav_host_files",
            "serena_project_find_sample_retail_main_nav_host",
            "Compose function lookup can be tiny through either route; LSP proves the function body range.",
        ),
        (
            "Sample Retail CartItemsDao definition",
            "known_symbol_cart_items_dao_files",
            "serena_project_find_sample_retail_cart_items_dao",
            "DAO text hits are not enough to distinguish generated/cache roles; LSP identifies the source symbol.",
        ),
        (
            "Sample Retail CartItemsDao references",
            "known_symbol_cart_items_dao_files",
            "serena_project_refs_sample_retail_cart_items_dao",
            "LSP returns semantic referencing symbols for the DAO without reading every text hit.",
        ),
        (
            "Sample Retail SamplePushService",
            "known_symbol_push_service_files",
            "serena_project_find_sample_retail_push_service",
            "Text search is smallest; LSP adds service symbol identity and range.",
        ),
    ]
    rows = []
    for label, search_id, lsp_id, verdict in comparisons:
        search = default_by_case.get(search_id)
        lsp = serena_by_case.get(lsp_id)
        if not search or not lsp:
            continue
        rows.append(
            [
                label,
                f"`{search_id}`",
                fmt_int(search.get("last_estimated_tokens", token_proxy(int(search.get("last_byte_count", 0))))),
                fmt_seconds(search.get("median_wall_seconds")),
                f"`{lsp_id}`",
                fmt_int(lsp.get("last_estimated_tokens")),
                fmt_seconds(lsp.get("median_wall_seconds")),
                verdict,
            ]
        )
    return "\n".join(
        [
            "## Direct Search vs LSP Comparison",
            "",
            "These rows compare the normal-search baseline with the closest semantic Serena ProjectServer probe for the same Android symbol family.",
            "",
            markdown_table(
                [
                    "Symbol family",
                    "Search case",
                    "Search tokens",
                    "Search seconds",
                    "LSP case",
                    "LSP tokens",
                    "LSP seconds",
                    "Interpretation",
                ],
                rows,
            ),
            "",
            "Direct comparison rule: `rg/fd` often wins on raw speed and sometimes on size, but only the LSP layer proves Kotlin symbol identity, owning ranges, members, and semantic references.",
        ]
    )


def render_capability_matrix(
    default_counts: dict[str, int],
    semantic_rows: list[dict[str, Any]],
    serena_rows: list[dict[str, Any]],
    serena_project_rows: list[dict[str, Any]],
    process_state_counts: dict[str, int],
    project_rows: list[dict[str, Any]],
) -> str:
    studio_ready = sum(
        1
        for row in semantic_rows
        if row.get("command_type") in {"check", "analyze-file"} and "pass" in row.get("statuses", [])
    )
    studio_no_result = sum(
        1
        for row in semantic_rows
        if row.get("command_type") in {"find-declaration", "find-usages"} and "no-result" in row.get("statuses", [])
    )
    source_symbol_pass = sum(1 for row in serena_rows if "pass" in row.get("statuses", []))
    project_server_pass = sum(1 for row in serena_project_rows if "pass" in row.get("statuses", []))
    project_server_boundary = sum(
        1
        for row in serena_project_rows
        if row.get("tool_name") == "find_implementations" and "error" in row.get("statuses", [])
    )
    project_server_measured = sum(
        int(row.get("measured_pass_count", 1))
        for row in serena_project_rows
        if "pass" in row.get("statuses", [])
    )
    missing_keys = sorted({key for row in project_rows for key in row.get("missing_local_properties", [])})
    return "\n".join(
        [
            "## Android Semantic Capability Matrix",
            "",
            markdown_table(
                ["Layer", "Current proof", "Boundary"],
                [
                    [
                        "Default `fd` / `rg` / `ast-grep`",
                        f"{default_counts.get('pass', 0)} assertion passes with expected high-output warnings",
                        "Discovery and structural evidence only; not symbol identity proof.",
                    ],
                    [
                        "Android Studio Preview / Quail CLI",
                        f"{studio_ready} readiness/file-analysis passes; {studio_no_result} declaration/usages probes still no-result",
                        "Use for readiness and diagnostics until declaration/usages smoke tests pass.",
                    ],
                    [
                        "Serena source-symbol",
                        f"{source_symbol_pass} real `.kt` source-symbol passes",
                        "Proves Kotlin symbol extraction, not full runtime/project-model correctness.",
                    ],
                    [
                        "Serena ProjectServer",
                        f"{project_server_pass} functional semantic cases across {project_server_measured} measured passes; {project_server_boundary} expected implementation-boundary cases",
                        "Best current Android semantic proof layer outside the broken Codex MCP transport; implementation lookup is an explicit unsupported boundary.",
                    ],
                    [
                        "Serena/Android process state",
                        f"{process_state_counts.get('pass', 0)} clean-process assertions passed",
                        "Keeps stale LSP/JDTLS sessions from being mistaken for semantic failures.",
                    ],
                    [
                        "Gradle / Android runtime",
                        "Preflight only; missing local keys: " + (", ".join(f"`{key}`" for key in missing_keys) or "-"),
                        "No build, install, emulator, device, or runtime proof is claimed.",
                    ],
                ],
            ),
        ]
    )


def render_default_search(default_rows: list[dict[str, Any]], repo: str) -> str:
    top_rows = top_by_bytes(default_rows, repo)
    known_rows = known_symbol_rows(default_rows, repo)
    lines = [f"## {repo} Default Search Highlights", ""]
    lines.append(
        markdown_table(
            ["Case", "Command", "Bytes", "Token proxy", "Lines", "Files", "Median seconds"],
            [
                [
                    f"`{row['case_id']}`",
                    f"`{row['command_label']}`",
                    fmt_int(row.get("last_byte_count")),
                    fmt_int(token_proxy(int(row.get("last_byte_count", 0)))),
                    fmt_int(row.get("last_line_count")),
                    fmt_int(row.get("last_unique_file_count")),
                    fmt_seconds(row.get("median_wall_seconds")),
                ]
                for row in top_rows
            ],
        )
    )
    lines.extend(["", "Known-symbol text baselines:", ""])
    lines.append(
        markdown_table(
            ["Case", "Bytes", "Token proxy", "Files", "Matches", "Median seconds"],
            [
                [
                    f"`{row['case_id']}`",
                    fmt_int(row.get("last_byte_count")),
                    fmt_int(token_proxy(int(row.get("last_byte_count", 0)))),
                    fmt_int(row.get("last_unique_file_count")),
                    fmt_int(row.get("last_match_count")),
                    fmt_seconds(row.get("median_wall_seconds")),
                ]
                for row in known_rows
            ],
        )
    )
    return "\n".join(lines)


def render_semantic(semantic_rows: list[dict[str, Any]]) -> str:
    rows = sorted(semantic_rows, key=lambda row: (str(row.get("repo", "")), str(row.get("case_id", ""))))
    return "\n".join(
        [
            "## Android Studio Semantic Probe",
            "",
            markdown_table(
                ["Repo", "Case", "Command", "Symbol", "Status", "Bytes", "Token proxy", "Median seconds"],
                [
                    [
                        f"`{row['repo']}`",
                        f"`{row['case_id']}`",
                        f"`{row['command_type']}`",
                        f"`{row.get('symbol') or '-'}`",
                        f"`{','.join(row.get('statuses', []))}`",
                        fmt_int(row.get("last_byte_count")),
                        fmt_int(row.get("last_estimated_tokens")),
                        fmt_seconds(row.get("median_wall_seconds")),
                    ]
                    for row in rows
                ],
            ),
        ]
    )


def render_serena_source(serena_rows: list[dict[str, Any]]) -> str:
    rows = sorted(serena_rows, key=lambda row: (str(row.get("repo", "")), str(row.get("case_id", ""))))
    return "\n".join(
        [
            "## Serena / Kotlin LSP Source-Symbol Probe",
            "",
            markdown_table(
                ["Repo", "Case", "Source file", "Status", "Symbols", "Bytes", "Token proxy", "Median seconds"],
                [
                    [
                        f"`{row['repo']}`",
                        f"`{row['case_id']}`",
                        f"`{row.get('source_file', '-')}`",
                        f"`{','.join(row.get('statuses', []))}`",
                        fmt_int(row.get("last_symbol_count")),
                        fmt_int(row.get("last_byte_count")),
                        fmt_int(row.get("last_estimated_tokens")),
                        fmt_seconds(row.get("median_wall_seconds")),
                    ]
                    for row in rows
                ],
            ),
        ]
    )


def render_serena_project(serena_rows: list[dict[str, Any]]) -> str:
    rows = sorted(serena_rows, key=lambda row: (str(row.get("repo", "")), str(row.get("case_id", ""))))
    return "\n".join(
        [
            "## Serena / ProjectServer Semantic Probe",
            "",
            "This layer exercises read-only Serena semantic tools through the local ProjectServer, outside the Codex MCP transport.",
            "",
            markdown_table(
                ["Repo", "Case", "Tool", "Status", "Measured passes", "Bytes", "Token proxy", "Median seconds"],
                [
                    [
                        f"`{row['repo']}`",
                        f"`{row['case_id']}`",
                        f"`{row['tool_name']}`",
                        f"`{','.join(row.get('statuses', []))}`",
                        fmt_int(row.get("measured_pass_count", 1)),
                        fmt_int(row.get("last_byte_count")),
                        fmt_int(row.get("last_estimated_tokens")),
                        fmt_seconds(row.get("median_wall_seconds")),
                    ]
                    for row in rows
                ],
            ),
        ]
    )


def render_process_state(process_state: dict[str, Any]) -> str:
    counts = dict(process_state.get("counts", {}))
    guidance = dict(process_state.get("guidance", {}))
    return "\n".join(
        [
            "## Serena / Android Process State",
            "",
            markdown_table(
                ["Process kind", "Count"],
                [
                    ["Serena MCP", fmt_int(counts.get("serena_mcp", 0))],
                    ["Kotlin LSP", fmt_int(counts.get("kotlin_lsp", 0))],
                    ["JSON LSP", fmt_int(counts.get("json_lsp", 0))],
                    ["Java/JDTLS", fmt_int(counts.get("java_jdtls", 0))],
                ],
            ),
            "",
            f"Status: `{process_state.get('status', '-')}`",
            "",
            "Cleanup commands:",
            "",
            "```bash",
            guidance.get("dry_run", "scripts/setup/repair-serena-android-sessions.sh --dry-run"),
            guidance.get("explicit_kill", "scripts/setup/repair-serena-android-sessions.sh --kill"),
            "```",
        ]
    )


def render_project_model(project_rows: list[dict[str, Any]]) -> str:
    rows = sorted(project_rows, key=lambda row: str(row.get("repo", "")))
    return "\n".join(
        [
            "## Android Project-Model Readiness",
            "",
            markdown_table(
                ["Repo", "Status", "Gradle distribution", "Wrapper status", "Command source", "Missing local keys", "Ran Gradle"],
                [
                    [
                        f"`{row['repo']}`",
                        f"`{','.join(row.get('statuses', []))}`",
                        f"`{row.get('gradle_distribution', '-')}`",
                        f"`{row.get('gradle_wrapper_status', '-')}`",
                        f"`{row.get('selected_command_source', '-')}`",
                        ", ".join(f"`{key}`" for key in row.get("missing_local_properties", [])) or "-",
                        str(row.get("ran_gradle", False)).lower(),
                    ]
                    for row in rows
                ],
            ),
        ]
    )


def render(args: argparse.Namespace) -> str:
    root = Path(args.results_root).expanduser().resolve()
    default_summary = Path(args.default_summary) if args.default_summary else latest(root / "default-search", "summary-*.json")
    default_assertions = (
        Path(args.default_assertions)
        if args.default_assertions
        else latest(root / "default-search", "policy-assertions-*.json")
    )
    semantic_summary = (
        Path(args.semantic_summary)
        if args.semantic_summary
        else latest(root / "android-studio-semantic", "android-studio-semantic-summary-*.json")
    )
    semantic_assertions = (
        Path(args.semantic_assertions)
        if args.semantic_assertions
        else latest(root / "android-studio-semantic", "android-studio-semantic-assertions-*.json")
    )
    serena_summary = (
        Path(args.serena_summary)
        if args.serena_summary
        else latest(root / "serena-source-symbol", "serena-source-symbol-summary-*.json")
    )
    serena_assertions = (
        Path(args.serena_assertions)
        if args.serena_assertions
        else latest(root / "serena-source-symbol", "serena-source-symbol-assertions-*.json")
    )
    serena_project_summary = (
        Path(args.serena_project_summary)
        if args.serena_project_summary
        else latest(root / "serena-project-server", "serena-project-server-summary-*.json")
    )
    serena_project_assertions = (
        Path(args.serena_project_assertions)
        if args.serena_project_assertions
        else latest(root / "serena-project-server", "serena-project-server-assertions-*.json")
    )
    process_state_summary = (
        Path(args.process_state_summary)
        if args.process_state_summary
        else latest(root / "process-state", "android-process-state-summary-*.json")
    )
    process_state_assertions = (
        Path(args.process_state_assertions)
        if args.process_state_assertions
        else latest(root / "process-state", "android-process-state-assertions-*.json")
    )
    project_summary = (
        Path(args.project_model_summary)
        if args.project_model_summary
        else latest(root / "project-model", "android-project-model-summary-*.json")
    )
    project_assertions = (
        Path(args.project_model_assertions)
        if args.project_model_assertions
        else latest(root / "project-model", "android-project-model-assertions-*.json")
    )

    default_rows = load_json(default_summary)
    semantic_rows = load_json(semantic_summary)
    serena_rows = load_json(serena_summary)
    serena_project_rows = load_json(serena_project_summary)
    process_state = load_json(process_state_summary)
    project_rows = load_json(project_summary)
    default_counts = assertion_summary(default_assertions)
    semantic_counts = assertion_summary(semantic_assertions)
    serena_counts = assertion_summary(serena_assertions)
    serena_project_counts = assertion_summary(serena_project_assertions)
    process_state_counts = assertion_summary(process_state_assertions)
    project_counts = assertion_summary(project_assertions)

    now = datetime.now().strftime("%Y-%m-%d")
    lines = [
        f"# Android LSP vs Default Search Benchmark - {now}",
        "",
        "Generated benchmark report for Android/Kotlin routing over the configured Android repos.",
        "",
        "Raw outputs are intentionally kept under ignored `results/` and should not be published without sanitizing.",
        "",
        "## Scope",
        "",
        "- Default search benchmark: manifest-driven `fd` / `rg` / `ast-grep` cases.",
        "- Android Studio semantic probe: manifest-driven `android studio` readiness and symbol probes.",
        "- Serena source-symbol probe: manifest-driven `serena project index-file` checks on real `.kt` files.",
        "- Serena ProjectServer probe: manifest-driven `find_symbol`, `find_referencing_symbols`, `get_symbols_overview`, and `get_diagnostics_for_file` semantic checks.",
        "- Serena/Android process-state probe: live MCP/LSP/JDTLS process counts for LSP stability.",
        "- Android project-model probe: Gradle/local-config preflight before trusting semantic lookup.",
        "- No emulator, device, app install, UI, or runtime behavior proof is claimed.",
        "",
        "## Source Artifacts",
        "",
        markdown_table(
            ["Layer", "Summary", "Assertions"],
            [
                ["Default search", f"`{default_summary}`", f"`{default_assertions}`"],
                ["Android Studio semantic", f"`{semantic_summary}`", f"`{semantic_assertions}`"],
                ["Serena source-symbol", f"`{serena_summary}`", f"`{serena_assertions}`"],
                ["Serena ProjectServer", f"`{serena_project_summary}`", f"`{serena_project_assertions}`"],
                ["Process state", f"`{process_state_summary}`", f"`{process_state_assertions}`"],
                ["Project model", f"`{project_summary}`", f"`{project_assertions}`"],
            ],
        ),
        "",
        "## Assertion Summary",
        "",
        markdown_table(
            ["Layer", "Pass", "Warn", "Fail"],
            [
                ["Default search", default_counts.get("pass", 0), default_counts.get("warn", 0), default_counts.get("fail", 0)],
                ["Android Studio semantic", semantic_counts.get("pass", 0), semantic_counts.get("warn", 0), semantic_counts.get("fail", 0)],
                ["Serena source-symbol", serena_counts.get("pass", 0), serena_counts.get("warn", 0), serena_counts.get("fail", 0)],
                ["Serena ProjectServer", serena_project_counts.get("pass", 0), serena_project_counts.get("warn", 0), serena_project_counts.get("fail", 0)],
                ["Process state", process_state_counts.get("pass", 0), process_state_counts.get("warn", 0), process_state_counts.get("fail", 0)],
                ["Project model", project_counts.get("pass", 0), project_counts.get("warn", 0), project_counts.get("fail", 0)],
            ],
        ),
        "",
        render_warning_breakdown(
            [
                ("Default search", default_assertions),
                ("Android Studio semantic", semantic_assertions),
                ("Serena source-symbol", serena_assertions),
                ("Serena ProjectServer", serena_project_assertions),
                ("Process state", process_state_assertions),
                ("Project model", project_assertions),
            ]
        ),
        "",
        render_capability_matrix(
            default_counts,
            semantic_rows,
            serena_rows,
            serena_project_rows,
            process_state_counts,
            project_rows,
        ),
        "",
        render_direct_comparison(default_rows, serena_project_rows),
        "",
        render_default_search(default_rows, "sample_b2b_android"),
        "",
        render_default_search(default_rows, "sample_retail_android"),
        "",
        render_semantic(semantic_rows),
        "",
        render_serena_source(serena_rows),
        "",
        render_serena_project(serena_project_rows),
        "",
        render_process_state(process_state),
        "",
        render_project_model(project_rows),
        "",
        "## Current Interpretation",
        "",
        "The current Android result is operational for the requested routing benchmark, with explicit boundaries where Android Studio or Gradle cannot yet be used as proof.",
        "",
        "- `rg` / `fd` / `ast-grep` are stable and fast for discovery, literal/resource lookup, and structural patterns.",
        "- Android Studio Preview/Quail is connected and `analyze-file` works on real Kotlin files.",
        "- `find-declaration` and `find-usages` are still not usable as proof because they return `no-result` on the tested simple and fully qualified symbols.",
        "- Serena/Kotlin LSP source-symbol extraction works in both ExampleCo Android repos after stale sessions are cleaned.",
        "- Serena ProjectServer semantic queries can find Kotlin symbols, references, file-level symbol overviews, and diagnostics through read-only LSP tools outside the broken Codex MCP transport, with one warmup plus repeated measured passes per case.",
        "- Serena ProjectServer `find_implementations` is recorded as an expected unsupported boundary for the current Kotlin LSP handler, not as a live proof tool.",
        "- Process-state evidence must stay clean before treating future Kotlin LSP failures as semantic failures.",
        "- The project-model probe records the runtime/build boundary: both repos are missing required machine-local `local.properties` keys, and Sample B2B also has wrapper metadata without a checked-in `gradlew` script.",
        "- Because no build/runtime parity is claimed, those machine-local Gradle inputs are recorded as boundaries, not as LSP/search benchmark failures.",
        "",
        "## Routing Policy",
        "",
        "```text",
        "Known Kotlin/Java symbol:",
        "  Use a proven semantic layer only after source-symbol smoke tests pass.",
        "",
        "High-fanout symbol:",
        "  Summary/counts first; never raw dump.",
        "",
        "Literal/resource/XML/GraphQL/generated:",
        "  rg/fd and GraphQL tools first.",
        "",
        "Structural Kotlin/Gradle pattern:",
        "  ast-grep first.",
        "",
        "Build/runtime truth:",
        "  Gradle, Android Studio, emulator/device, adb, or CI only.",
        "```",
        "",
        "## Next Gate",
        "",
        "First clean stale Serena/LSP sessions only when it is safe to reconnect active agents, then prove process state:",
        "",
        "```bash",
        "scripts/setup/repair-serena-android-sessions.sh --dry-run",
        "scripts/setup/repair-serena-android-sessions.sh --kill",
        "python3 scripts/benchmarks/android/process_state_probe.py --validate --run \\",
        "  --require-clean --enforce-assertions \\",
        "  --output results/android/process-state",
        "```",
        "",
        "Only when you need build/runtime proof, add the real team-approved `local.properties` values, repair or restore Sample B2B's `gradlew` script, rerun Gradle sync, and rerun:",
        "",
        "```bash",
        "python3 scripts/benchmarks/android/run_benchmark_suite.py \\",
        "  --require-clean-process-state --enforce-assertions \\",
        "  --sample-b2b-repo /path/to/sample-b2b-android-app \\",
        "  --sample-retail-repo /path/to/sample-retail-android-app",
        "```",
        "",
        "For focused layer debugging, rerun the individual probes:",
        "",
        "```bash",
        "python3 scripts/benchmarks/android/project_model_probe.py --validate --run \\",
        "  --cases benchmarks/android/project-model-cases.sample.tsv \\",
        "  --repo sample_b2b_android=/path/to/sample-b2b-android-app \\",
        "  --repo sample_retail_android=/path/to/sample-retail-android-app \\",
        "  --output results/android/project-model",
        "",
        "python3 scripts/benchmarks/android/studio_semantic_probe.py --validate --run \\",
        "  --cases benchmarks/android/studio-semantic-cases.sample.tsv \\",
        "  --repo sample_b2b_android=/path/to/sample-b2b-android-app \\",
        "  --repo sample_retail_android=/path/to/sample-retail-android-app \\",
        "  --output results/android/android-studio-semantic",
        "",
        "python3 scripts/benchmarks/android/serena_source_symbol_probe.py --validate --run \\",
        "  --cases benchmarks/android/serena-source-symbol-cases.sample.tsv \\",
        "  --repo sample_b2b_android=/path/to/sample-b2b-android-app \\",
        "  --repo sample_retail_android=/path/to/sample-retail-android-app \\",
        "  --output results/android/serena-source-symbol",
        "```",
    ]
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a combined Android routing benchmark report.")
    parser.add_argument("--results-root", default="results/android")
    parser.add_argument("--output", default="")
    parser.add_argument("--default-summary", default="")
    parser.add_argument("--default-assertions", default="")
    parser.add_argument("--semantic-summary", default="")
    parser.add_argument("--semantic-assertions", default="")
    parser.add_argument("--serena-summary", default="")
    parser.add_argument("--serena-assertions", default="")
    parser.add_argument("--serena-project-summary", default="")
    parser.add_argument("--serena-project-assertions", default="")
    parser.add_argument("--process-state-summary", default="")
    parser.add_argument("--process-state-assertions", default="")
    parser.add_argument("--project-model-summary", default="")
    parser.add_argument("--project-model-assertions", default="")
    args = parser.parse_args()
    text = render(args)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
        print(f"Wrote {output}")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
