from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import RouteProfile, TaskSpec, load_route_profile, to_json_file
from scripts.lib.transcript_parser import parse_benchmark_response


FALSE_RUNTIME_PATTERNS = (
    "business flow works",
    "runtime behavior is correct",
    "app works end to end",
)
SHELL_PLUMBING_TOOLS = {"pwd", "printf", "echo", "true", "false", "test"}
SEMANTIC_TOOL_ALIASES = {
    "find_symbol",
    "find_referencing_symbols",
    "get_symbols_overview",
    "find_declaration",
    "find_references",
    "hover",
    "semsearch",
    "semantic_search",
    "studio_usages",
    "android_studio_usages",
}


def normalize_tool_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def blocked_tool_used(tools_used: list[str], blocked_tools: list[str]) -> list[str]:
    normalized_used = [normalize_tool_name(tool) for tool in tools_used]
    violations: list[str] = []
    for blocked in blocked_tools:
        normalized_blocked = normalize_tool_name(blocked)
        blocked_terms = {term for term in normalized_blocked.split("_") if term}
        semantic_policy = any(
            term in normalized_blocked
            for term in ("semantic", "serena", "lsp", "android_studio", "studio")
        )
        for used in normalized_used:
            if normalized_blocked and normalized_blocked in used:
                violations.append(blocked)
                break
            if blocked_terms and blocked_terms.issubset(set(used.split("_"))):
                violations.append(blocked)
                break
            if semantic_policy and used in SEMANTIC_TOOL_ALIASES:
                violations.append(blocked)
                break
    return sorted(set(violations))


def required_first_tool_matches(required: str, tools_used: list[str]) -> bool:
    if not required:
        return True
    substantive_tools = [
        tool for tool in tools_used if normalize_tool_name(tool) not in SHELL_PLUMBING_TOOLS
    ]
    if not substantive_tools:
        return False
    first = normalize_tool_name(substantive_tools[0])
    required = normalize_tool_name(required)
    if required in {"rg_or_fd", "grouped_search"}:
        return first in {"rg", "fd", "grouped_counts", "grouped_search", "ast_grep"}
    if required == "semantic_for_known_symbol":
        return any(term in first for term in ("serena", "lsp", "android_studio", "studio_usages"))
    if required == "intent_router":
        return True
    return required in first


def has_expected_signal(transcript: str, expected_success_signal: str) -> bool:
    if not expected_success_signal:
        return False
    lowered = transcript.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", expected_success_signal.lower()) if len(token) > 3]
    if not tokens:
        return False
    if "definition" in expected_success_signal.lower():
        symbol_tokens = [
            token
            for token in tokens
            if token not in {"definition", "reported", "report", "file", "path"}
        ]
        symbol_seen = not symbol_tokens or any(token in lowered for token in symbol_tokens)
        definition_seen = any(term in lowered for term in ("definition", "defined", "class ", "interface ", "object ", "fun "))
        path_seen = any(term in lowered for term in (".kt", ".java", "/src/", " file"))
        return symbol_seen and definition_seen and path_seen
    if "grouped" in expected_success_signal.lower() or "summary" in expected_success_signal.lower():
        subject_tokens = [
            token
            for token in tokens
            if token not in {"grouped", "summary", "reported", "report"}
        ]
        subject_seen = not subject_tokens or any(token in lowered for token in subject_tokens)
        grouping_seen = any(term in lowered for term in ("summary", "group", "cluster", "concentrat", "module", "package", "directory"))
        count_seen = any(term in lowered for term in ("count", "files", "matches", "occurrences", "about "))
        return subject_seen and grouping_seen and count_seen
    return all(token in lowered for token in tokens[:3])


def tool_or_count_seen(*, tools: list[str], metrics: dict[str, object], terms: tuple[str, ...], count_fields: tuple[str, ...] = ()) -> bool:
    normalized_tools = [normalize_tool_name(tool) for tool in tools]
    if any(any(term in tool for term in terms) for tool in normalized_tools):
        return True
    return any(int(metrics.get(field, 0) or 0) > 0 for field in count_fields)


def expected_proof_layer_seen(
    *,
    proof_layer: str,
    transcript: str,
    route_profile: RouteProfile | None,
    observed_tools: list[str],
    metrics: dict[str, object],
) -> bool:
    if not proof_layer:
        return False
    layer = normalize_tool_name(proof_layer)
    lowered = transcript.lower()
    search_seen = tool_or_count_seen(
        tools=observed_tools,
        metrics=metrics,
        terms=("rg", "fd", "grep", "glob", "read"),
        count_fields=("search_count",),
    )
    semantic_seen = tool_or_count_seen(
        tools=observed_tools,
        metrics=metrics,
        terms=("serena", "lsp", "android_studio", "studio_usages"),
        count_fields=("semantic_tool_count",),
    )
    ast_seen = tool_or_count_seen(
        tools=observed_tools,
        metrics=metrics,
        terms=("ast_grep", "ast-grep"),
        count_fields=("ast_grep_count",),
    )
    runtime_seen = tool_or_count_seen(
        tools=observed_tools,
        metrics=metrics,
        terms=("gradle", "adb", "emulator", "install", "launch"),
        count_fields=("runtime_tool_count",),
    )
    graphql_seen = "graphql" in lowered or tool_or_count_seen(
        tools=observed_tools,
        metrics=metrics,
        terms=("graphql",),
    )
    if layer == "semantic_identity_or_search_labeled":
        if semantic_seen:
            return True
        search_only = bool(route_profile and route_profile.blocked_tools and not semantic_seen)
        return search_seen and (not search_only or "search evidence" in lowered or "search-only" in lowered)
    if layer == "reference_proof_or_search_labeled":
        if semantic_seen:
            return True
        search_only = bool(route_profile and route_profile.blocked_tools and not semantic_seen)
        return search_seen and "reference" in lowered and (not search_only or "search evidence" in lowered or "search-only" in lowered)
    if layer == "semantic_disagreement_boundary":
        return semantic_seen and all(term in lowered for term in ("serena", "studio", "boundary"))
    if layer == "high_fanout_summary":
        grouping_seen = any(term in lowered for term in ("summary", "group", "cluster", "concentrat", "module", "package", "directory"))
        count_seen = any(term in lowered for term in ("count", "files", "matches", "occurrences", "about "))
        return grouping_seen and count_seen
    if layer == "rg_fd_resource_discovery":
        return search_seen and any(term in lowered for term in ("resource", "xml", "layout", "drawable", "string"))
    if layer == "graphql_discovery_then_generated_mapping":
        return graphql_seen and "generated" in lowered
    if layer == "build_generated_boundary":
        return "generated" in lowered and any(term in lowered for term in ("build", "boundary", "source"))
    if layer == "ast_grep_structural_pattern":
        return ast_seen and any(term in lowered for term in ("structural", "pattern", "syntax"))
    if layer == "android_studio_matrix_proof":
        return semantic_seen and "studio" in lowered and "boundary" in lowered
    if layer == "gradle_adb_runtime_smoke":
        return runtime_seen and any(term in lowered for term in ("runtime", "smoke", "install", "launch", "boundary"))
    return proof_layer.lower() in lowered


def judge_transcript(
    transcript: str,
    *,
    sentinel: str = "BENCHMARK_DONE",
    max_raw_dump_incidents: int = 0,
    forbidden_claims: str = "",
    route_profile: RouteProfile | None = None,
    task: TaskSpec | None = None,
    metrics: dict[str, object] | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    parsed = parse_benchmark_response(transcript, sentinel=sentinel)
    evaluation_text = parsed.redacted_text
    violations: list[str] = []
    observed_tools = [
        str(tool)
        for tool in (metrics or {}).get("observed_task_tools", (metrics or {}).get("observed_tools", []))
        if str(tool)
    ]
    metric_values = metrics or {}
    tool_evidence_source = str((metrics or {}).get("tool_evidence_source", "missing"))
    policy_tools = observed_tools or parsed.tools_used
    if not parsed.done:
        violations.append("missing_done_sentinel")
    if not parsed.contract_present:
        violations.append("missing_response_contract")
    if parsed.status not in {"pass", "partial", "fail", "blocked"}:
        violations.append("missing_status")
    if parsed.policy_adherence is None:
        violations.append("missing_policy_adherence")
    if parsed.raw_dump_incidents > max_raw_dump_incidents:
        violations.append("raw_dump_incident")
    if parsed.policy_adherence == "fail":
        violations.append("policy_adherence_failed")
    if route_profile is not None and not dry_run:
        if tool_evidence_source != "observed":
            violations.append("tool_evidence_not_observed")
        blocked = blocked_tool_used(policy_tools, route_profile.blocked_tools)
        for tool in blocked:
            violations.append(f"blocked_tool_used:{tool}")
        if not required_first_tool_matches(route_profile.required_first_tool, policy_tools):
            violations.append("required_first_tool_not_used")
        output_bytes = int(metric_values.get("tool_output_bytes", 0) or 0)
        if output_bytes > route_profile.max_raw_output_bytes:
            violations.append("tool_output_over_budget")
        if (
            task is not None
            and task.task_family.startswith("high_fanout")
            and "summary_first" in route_profile.high_fanout_policy
            and not expected_proof_layer_seen(
                proof_layer="high_fanout_summary",
                transcript=evaluation_text,
                route_profile=route_profile,
                observed_tools=observed_tools,
                metrics=metric_values,
            )
        ):
            violations.append("missing_high_fanout_summary")
    lowered = evaluation_text.lower()
    for phrase in FALSE_RUNTIME_PATTERNS:
        if phrase in lowered:
            violations.append("possible_false_runtime_claim")
            break
    if forbidden_claims and forbidden_claims.lower() in lowered:
        violations.append("forbidden_claim_echoed")
    expected_signal_seen = False
    proof_layer_seen = False
    if task is not None:
        expected_signal_seen = has_expected_signal(evaluation_text, task.expected_success_signal)
        if parsed.status == "pass" and not dry_run and not expected_signal_seen:
            violations.append("expected_success_signal_missing")
        proof_layer_seen = expected_proof_layer_seen(
            proof_layer=task.expected_proof_layer,
            transcript=evaluation_text,
            route_profile=route_profile,
            observed_tools=observed_tools,
            metrics=metric_values,
        )
        if parsed.status == "pass" and not dry_run and not proof_layer_seen:
            violations.append("expected_proof_layer_missing")
    correctness_status = "not_evaluated"
    if dry_run and parsed.status == "pass" and not violations:
        correctness_status = "dry_run_contract_pass"
    elif parsed.status == "pass" and not violations and expected_signal_seen:
        correctness_status = "pass"
    elif parsed.status in {"partial", "blocked"}:
        correctness_status = parsed.status
    elif violations:
        correctness_status = "fail"
    return {
        "contract_valid": parsed.contract_present and parsed.done,
        "policy_adherence": parsed.policy_adherence or "unknown",
        "correctness_status": correctness_status,
        "violations": violations,
        "raw_dump_incidents": parsed.raw_dump_incidents,
        "tools_used": parsed.tools_used,
        "observed_tools": observed_tools,
        "tool_evidence_source": tool_evidence_source,
        "files_opened": parsed.files_opened,
        "expected_success_signal_seen": expected_signal_seen,
        "expected_proof_layer_seen": proof_layer_seen,
        "status": parsed.status,
    }


def judge_file(
    transcript_path: str | Path,
    *,
    sentinel: str = "BENCHMARK_DONE",
    forbidden_claims: str = "",
    route_profile: RouteProfile | None = None,
    task: TaskSpec | None = None,
    metrics: dict[str, object] | None = None,
    dry_run: bool = False,
    out: str | Path | None = None,
) -> dict[str, object]:
    text = Path(transcript_path).read_text(encoding="utf-8")
    result = judge_transcript(
        text,
        sentinel=sentinel,
        forbidden_claims=forbidden_claims,
        route_profile=route_profile,
        task=task,
        metrics=metrics,
        dry_run=dry_run,
    )
    if out:
        to_json_file(out, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge a real-agent benchmark transcript.")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--sentinel", default="BENCHMARK_DONE")
    parser.add_argument("--forbidden-claims", default="")
    parser.add_argument("--route-profile")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    route_profile = load_route_profile(args.route_profile) if args.route_profile else None
    result = judge_file(
        args.transcript,
        sentinel=args.sentinel,
        forbidden_claims=args.forbidden_claims,
        route_profile=route_profile,
        dry_run=args.dry_run,
        out=args.out,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["contract_valid"] and result["correctness_status"] != "fail" else 2


if __name__ == "__main__":
    raise SystemExit(main())
