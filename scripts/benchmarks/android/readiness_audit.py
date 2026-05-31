#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def latest_file(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern))
    return matches[-1] if matches else None


def lifecycle_artifact_is_qualified(path: Path) -> bool:
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError):
        return False
    transports = set(payload.get("transports", []))
    process_delta = payload.get("process_delta", {})
    assertions = summary_counts(payload)
    cases = payload.get("cases", [])
    return (
        int(payload.get("case_count", 0)) >= 8
        and {"stdio", "streamable-http"} <= transports
        and all_zero(process_delta)
        and assertions["fail"] == 0
        and bool(cases)
        and all(str(case.get("status")) == "pass" for case in cases)
    )


def latest_qualified_lifecycle_file(root: Path) -> Path | None:
    matches = sorted(root.glob("android-serena-mcp-lifecycle-summary-*.json"))
    for path in reversed(matches):
        if lifecycle_artifact_is_qualified(path):
            return path
    return matches[-1] if matches else None


def load_json(path: Path | None) -> Any:
    if path is None:
        return None
    return json.loads(path.read_text())


def summary_counts(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {"pass": 0, "warn": 0, "fail": 0}
    raw = payload.get("summary") or payload.get("assertions") or {}
    if isinstance(raw, dict) and "summary" in raw and isinstance(raw["summary"], dict):
        raw = raw["summary"]
    if not isinstance(raw, dict):
        raw = {}
    return {
        "pass": int(raw.get("pass", 0)),
        "warn": int(raw.get("warn", 0)),
        "fail": int(raw.get("fail", 0)),
    }


def all_zero(values: dict[str, Any] | None) -> bool:
    return all(int(value) == 0 for value in (values or {}).values())


def count_statuses(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key, ""))
        counts[value] = counts.get(value, 0) + 1
    return counts


def artifact_paths(results_root: Path) -> dict[str, Path | None]:
    return {
        "sample_b2b_operational": latest_file(results_root / "operational", "android-operational-summary-*.json"),
        "project_aware_process": latest_file(
            results_root / "process-state-stable-project-aware-allowed-other",
            "android-process-state-summary-*.json",
        ),
        "process_scope_acceptance": latest_file(
            results_root / "process-scope-acceptance",
            "android-process-scope-acceptance-summary-*.json",
        ),
        "serena_reference_triage": latest_file(
            results_root / "serena-mcp-reference-triage-stdio-expanded",
            "android-serena-mcp-reference-triage-summary-*.json",
        )
        or latest_file(
            results_root / "serena-mcp-reference-triage",
            "android-serena-mcp-reference-triage-summary-*.json",
        ),
        "studio_matrix": latest_file(
            results_root / "studio-symbol-matrix",
            "android-studio-symbol-matrix-summary-*.json",
        ),
        "generated_mapping": latest_file(
            results_root / "generated-semantic-mapping",
            "android-generated-semantic-mapping-summary-*.json",
        ),
        "high_fanout": latest_file(
            results_root / "high-fanout-summary-sample_b2b-stable-expanded",
            "android-high-fanout-summary-*.json",
        )
        or latest_file(results_root / "high-fanout-summary", "android-high-fanout-summary-*.json"),
        "mcp_lifecycle": latest_qualified_lifecycle_file(results_root / "serena-mcp-lifecycle"),
        "transport_recommendation": latest_file(
            results_root / "transport-recommendation",
            "android-transport-recommendation-summary-*.json",
        ),
        "kotlin_memory": latest_file(
            results_root / "kotlin-lsp-memory-matrix",
            "android-kotlin-lsp-memory-matrix-summary-*.json",
        ),
        "agent_behavior": latest_file(
            results_root / "agent-behavior",
            "android-agent-behavior-summary-*.json",
        ),
        "sample_retail_followup": latest_file(
            results_root / "sample_retail-followup",
            "android-sample_retail-followup-summary-*.json",
        ),
    }


def gate(
    gate_id: str,
    requirement: str,
    status: str,
    stable_gate: str,
    readiness: str,
    evidence_path: Path | None,
    details: dict[str, Any],
    next_action: str,
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "requirement": requirement,
        "status": status,
        "stable_gate": stable_gate,
        "readiness": readiness,
        "evidence": str(evidence_path) if evidence_path else "",
        "details": details,
        "next_action": next_action,
    }


def missing_gate(gate_id: str, requirement: str, next_action: str) -> dict[str, Any]:
    return gate(gate_id, requirement, "missing", "missing", "blocked", None, {}, next_action)


def build_gates(paths: dict[str, Path | None], payloads: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []

    operational = payloads["sample_b2b_operational"]
    if operational is None:
        gates.append(
            missing_gate(
                "sample_b2b_operational_gate",
                "Sample B2B operational gate records semantic, generated, build, install, and launch smoke proof.",
                "Run the Sample B2B stable operational gate.",
            )
        )
    else:
        counts = summary_counts(operational)
        manifest_counts = summary_counts(operational.get("manifest_policy", {}))
        ok = operational.get("overall_status") == "pass" and counts["fail"] == 0 and manifest_counts["fail"] == 0
        gates.append(
            gate(
                "sample_b2b_operational_gate",
                "Sample B2B operational gate records semantic, generated, build, install, and launch smoke proof.",
                "pass" if ok else "blocker",
                "achieved" if ok else "blocked",
                "satisfied_for_sample_b2b" if ok else "blocked",
                paths["sample_b2b_operational"],
                {
                    "overall_status": operational.get("overall_status"),
                    "summary": counts,
                    "manifest_policy": manifest_counts,
                    "boundary": operational.get("boundary", ""),
                },
                "Keep launch smoke scoped to runtime readiness; do not claim business-flow correctness.",
            )
        )

    process = payloads["project_aware_process"]
    if process is None:
        gates.append(
            missing_gate(
                "clean_process_state",
                "Process strictness distinguishes target-project stale sessions from unrelated Serena sessions.",
                "Run the project-aware process-state probe.",
            )
        )
    else:
        target_count = int(process.get("target_serena_mcp_count", 0))
        other_count = int(process.get("other_project_serena_mcp_count", 0))
        unknown_count = int(process.get("unknown_serena_mcp_count", 0))
        project_clean = process.get("status") == "clean" and target_count <= 1 and unknown_count == 0
        clean_room = project_clean and other_count == 0
        scope_acceptance = payloads.get("process_scope_acceptance") or {}
        accepted_project_aware = bool(
            project_clean
            and scope_acceptance.get("status") == "accepted"
            and scope_acceptance.get("accepted_project_aware_strictness") is True
            and int((scope_acceptance.get("assertions") or {}).get("fail", 0)) == 0
        )
        readiness_state = (
            "satisfied"
            if clean_room
            else "satisfied_by_project_aware_acceptance"
            if accepted_project_aware
            else "pending_clean_room_or_project_aware_acceptance"
        )
        next_action = (
            "Clean-room process strictness is satisfied."
            if clean_room
            else "Project-aware strictness is explicitly accepted; keep other-project sessions classified."
            if accepted_project_aware
            else "Run a clean-room strict pass, or record explicit project-aware strictness acceptance with other-project sessions allowed."
        )
        gates.append(
            gate(
                "clean_process_state",
                "Process strictness distinguishes target-project stale sessions from unrelated Serena sessions.",
                "pass" if clean_room or accepted_project_aware else "warn" if project_clean else "blocker",
                "achieved" if project_clean else "blocked",
                readiness_state,
                paths["project_aware_process"],
                {
                    "status": process.get("status"),
                    "counts": process.get("counts", {}),
                    "target_serena_mcp_count": target_count,
                    "other_project_serena_mcp_count": other_count,
                    "unknown_serena_mcp_count": unknown_count,
                    "classification_counts": process.get("classification_counts", {}),
                    "process_scope_acceptance": scope_acceptance,
                },
                next_action,
            )
        )

    references = payloads["serena_reference_triage"]
    if references is None:
        gates.append(
            missing_gate(
                "serena_reference_disagreement",
                "Serena empty-reference behavior is fixed or replaced by Android Studio usages for affected patterns.",
                "Run direct MCP reference triage.",
            )
        )
    else:
        counts = summary_counts(references)
        classifications = references.get("classification_counts", {})
        named_boundary = int(classifications.get("serena-reference-empty-boundary", 0)) > 0
        process_stable = all_zero(references.get("process_delta", {}))
        studio = payloads.get("studio_matrix") or {}
        sample_retail = payloads.get("sample_retail_followup") or {}
        studio_replacement = bool(
            named_boundary
            and process_stable
            and bool(studio.get("trusted_studio_layer"))
            and sample_retail.get("status") == "followup-operational-equivalent"
            and bool((sample_retail.get("studio_matrix") or {}).get("trusted_studio_layer"))
        )
        ok = counts["fail"] == 0 and named_boundary and process_stable
        gates.append(
            gate(
                "serena_reference_disagreement",
                "Serena empty-reference behavior is fixed or replaced by Android Studio usages for affected patterns.",
                "pass" if ok and studio_replacement else "warn" if ok else "blocker",
                "achieved_with_named_boundary" if ok else "blocked",
                "satisfied_by_studio_replacement_for_affected_patterns"
                if ok and studio_replacement
                else "pending_or_studio_replacement_for_affected_patterns"
                if ok
                else "blocked",
                paths["serena_reference_triage"],
                {
                    "case_count": references.get("case_count"),
                    "assertions": counts,
                    "classification_counts": classifications,
                    "transports": references.get("transports", []),
                    "process_delta": references.get("process_delta", {}),
                    "studio_replacement_accepted": studio_replacement,
                },
                "Use Android Studio usages as the reference proof layer for affected class-level patterns unless Serena references are fixed.",
            )
        )

    studio = payloads["studio_matrix"]
    if studio is None:
        gates.append(
            missing_gate(
                "android_studio_symbol_matrix",
                "Android Studio declaration/usages matrix proves more than one smoke symbol.",
                "Run the Studio symbol matrix.",
            )
        )
    else:
        trusted = bool(studio.get("trusted_studio_layer"))
        declaration_passes = int(studio.get("declaration_pass_count", 0))
        usage_passes = int(studio.get("usage_pass_count", 0))
        ok = trusted and declaration_passes >= 8 and usage_passes >= 7
        sample_retail = payloads.get("sample_retail_followup") or {}
        sample_retail_studio_trusted = bool((sample_retail.get("studio_matrix") or {}).get("trusted_studio_layer"))
        studio_readiness = "satisfied_for_sample_b2b_and_sample_retail" if ok and sample_retail_studio_trusted else "satisfied_for_sample_b2b_pending_second_repo"
        studio_next = (
            "Keep matrix coverage current when adding Android repos."
            if sample_retail_studio_trusted
            else "Rerun the same matrix for Sample Retail or another Android repo before broad readiness."
        )
        gates.append(
            gate(
                "android_studio_symbol_matrix",
                "Android Studio declaration/usages matrix proves more than one smoke symbol.",
                "pass" if ok else "blocker",
                "achieved" if ok else "blocked",
                studio_readiness,
                paths["studio_matrix"],
                {
                    "case_count": studio.get("case_count"),
                    "trusted_studio_layer": trusted,
                    "declaration_pass_count": declaration_passes,
                    "usage_pass_count": usage_passes,
                    "sample_retail_trusted_studio_layer": sample_retail_studio_trusted,
                    "classification_counts": studio.get("classification_counts", {}),
                },
                studio_next,
            )
        )

    generated = payloads["generated_mapping"]
    if generated is None:
        gates.append(
            missing_gate(
                "generated_semantic_mapping",
                "Generated-source flows separate discovery, mapping, semantic proof, and build proof.",
                "Run generated-source semantic mapping.",
            )
        )
    else:
        mapping_passes = int(generated.get("mapping_pass_count", 0))
        semantic_passes = int(generated.get("semantic_pass_count", 0))
        ok = mapping_passes >= 3
        gates.append(
            gate(
                "generated_semantic_mapping",
                "Generated-source flows separate discovery, mapping, semantic proof, and build proof.",
                "pass" if ok else "blocker",
                "achieved" if ok else "blocked",
                "satisfied",
                paths["generated_mapping"],
                {
                    "case_count": generated.get("case_count"),
                    "mapping_pass_count": mapping_passes,
                    "semantic_pass_count": semantic_passes,
                    "classification_counts": generated.get("classification_counts", {}),
                    "semantic_classification_counts": generated.get("semantic_classification_counts", {}),
                },
                "Do not reclassify build-proven generated boundaries as LSP semantic success.",
            )
        )

    high_fanout = payloads["high_fanout"]
    if high_fanout is None:
        gates.append(
            missing_gate(
                "high_fanout_budget",
                "High-fanout symbols use grouped summaries and output budgets, never raw dumps.",
                "Run the high-fanout summary probe.",
            )
        )
    else:
        counts = summary_counts(high_fanout)
        patterns = high_fanout.get("patterns", [])
        ok = counts["fail"] == 0 and high_fanout.get("mode") == "summary_only" and len(patterns) >= 6
        gates.append(
            gate(
                "high_fanout_budget",
                "High-fanout symbols use grouped summaries and output budgets, never raw dumps.",
                "pass" if ok else "blocker",
                "achieved" if ok else "blocked",
                "satisfied",
                paths["high_fanout"],
                {
                    "mode": high_fanout.get("mode"),
                    "pattern_count": len(patterns),
                    "assertions": counts,
                    "patterns": [
                        {
                            "pattern": item.get("pattern"),
                            "file_count": item.get("file_count"),
                            "total_matches": item.get("total_matches"),
                            "budget_status": (item.get("budget") or {}).get("status"),
                        }
                        for item in patterns
                    ],
                },
                "Keep broad symbols summary-only; use focused semantic proof only after narrowing.",
            )
        )

    lifecycle = payloads["mcp_lifecycle"]
    transport_recommendation = payloads.get("transport_recommendation")
    if lifecycle is None:
        gates.append(
            missing_gate(
                "serena_mcp_lifecycle",
                "Direct Serena MCP lifecycle works across stdio and streamable HTTP without process growth.",
                "Run the direct MCP lifecycle probe.",
            )
        )
    else:
        transports = set(lifecycle.get("transports", []))
        ok = int(lifecycle.get("case_count", 0)) >= 8 and {"stdio", "streamable-http"} <= transports and all_zero(lifecycle.get("process_delta", {}))
        recommendation_status = str((transport_recommendation or {}).get("recommendation_status", ""))
        recommendation_readiness_satisfied = recommendation_status == "daily_recommendation"
        readiness_state = "satisfied" if recommendation_readiness_satisfied else "pending_daily_transport_recommendation"
        status = "pass" if ok and recommendation_readiness_satisfied else "warn" if ok else "blocker"
        next_action = (
            "Keep daily transport recommendation current as real-task evidence changes."
            if recommendation_readiness_satisfied
            else "Collect enough real-task transport observations before promoting the lifecycle candidate to daily default."
        )
        gates.append(
            gate(
                "serena_mcp_lifecycle",
                "Direct Serena MCP lifecycle works across stdio and streamable HTTP without process growth.",
                status,
                "achieved_with_timeout_boundary" if ok else "blocked",
                readiness_state,
                paths["mcp_lifecycle"],
                {
                    "case_count": lifecycle.get("case_count"),
                    "transports": sorted(transports),
                    "process_delta": lifecycle.get("process_delta", {}),
                    "assertions": summary_counts(lifecycle),
                    "transport_performance": lifecycle.get("transport_performance", {}),
                    "transport_recommendation": transport_recommendation or {},
                },
                next_action,
            )
        )

    memory = payloads["kotlin_memory"]
    if memory is None:
        gates.append(
            missing_gate(
                "kotlin_lsp_memory_matrix",
                "Kotlin LSP memory setting is chosen from measured 2G/4G/6G results.",
                "Run Kotlin LSP memory matrix.",
            )
        )
    else:
        values = memory.get("values", [])
        recommended = memory.get("recommended_jvm_options", "")
        ok = bool(recommended) and len(values) >= 3 and all(int((item.get("assertions") or {}).get("fail", 0)) == 0 for item in values)
        gates.append(
            gate(
                "kotlin_lsp_memory_matrix",
                "Kotlin LSP memory setting is chosen from measured 2G/4G/6G results.",
                "pass" if ok else "blocker",
                "achieved" if ok else "blocked",
                "satisfied",
                paths["kotlin_memory"],
                {
                    "recommended_jvm_options": recommended,
                    "values": [
                        {
                            "jvm_options": item.get("jvm_options"),
                            "median_wall_seconds": item.get("median_wall_seconds"),
                            "p95_wall_seconds": item.get("p95_wall_seconds"),
                            "process_delta": item.get("process_delta", {}),
                            "assertions": item.get("assertions", {}),
                        }
                        for item in values
                    ],
                },
                "Keep the lowest stable memory setting unless broader MCP runs produce timeouts.",
            )
        )

    behavior = payloads["agent_behavior"]
    if behavior is None:
        gates.append(
            missing_gate(
                "agent_behavior_policy_gate",
                "Mixed Android tasks are scored for correct first-tool routing.",
                "Run the agent behavior policy-proxy gate.",
            )
        )
    else:
        counts = summary_counts(behavior)
        observed_count = int(behavior.get("observed_case_count", 0))
        min_observed_for_readiness = int(behavior.get("minimum_observed_cases_for_readiness", 10))
        ok = counts["fail"] == 0 and int(behavior.get("case_count", 0)) >= 40
        observed_ok = observed_count >= min_observed_for_readiness
        gates.append(
            gate(
                "agent_behavior_policy_gate",
                "Mixed Android tasks are scored for correct first-tool routing.",
                "pass" if ok and observed_ok else "warn" if ok else "blocker",
                "achieved_as_policy_proxy" if ok else "blocked",
                "satisfied" if observed_ok else "pending_live_agent_evidence",
                paths["agent_behavior"],
                {
                    "case_count": behavior.get("case_count"),
                    "observed_case_count": observed_count,
                    "minimum_observed_cases_for_readiness": min_observed_for_readiness,
                    "assertions": counts,
                    "first_tool_counts": behavior.get("first_tool_counts", {}),
                },
                f"Feed at least {min_observed_for_readiness} live Codex first-tool observations through --observed-log before calling readiness behavior complete.",
            )
        )

    sample_retail = payloads["sample_retail_followup"]
    if sample_retail is None:
        gates.append(
            missing_gate(
                "second_repo_operational_scope",
                "Sample Retail or another Android repo has equivalent operational proof, or single-repo scope is accepted.",
                "Run Sample Retail follow-up audit at minimum; run equivalent operational gate for readiness.",
            )
        )
    else:
        counts = summary_counts(sample_retail)
        equivalent = sample_retail.get("status") == "followup-operational-equivalent" and counts["fail"] == 0
        followup_ok = sample_retail.get("status") in {"followup-pass-with-boundaries", "followup-operational-equivalent"} and counts["fail"] == 0
        next_action = (
            "Keep Sample Retail equivalent proof current when operational gates change."
            if equivalent
            else "Run Sample Retail Android Studio matrix plus build/install/launch smoke, or explicitly scope readiness to Sample B2B."
        )
        gates.append(
            gate(
                "second_repo_operational_scope",
                "Sample Retail or another Android repo has equivalent operational proof, or single-repo scope is accepted.",
                "pass" if equivalent else "warn" if followup_ok else "blocker",
                "equivalent_operational_evidence" if equivalent else "followup_evidence_only" if followup_ok else "blocked",
                "satisfied" if equivalent else "blocked_until_equivalent_operational_gate_or_scope_decision",
                paths["sample_retail_followup"],
                {
                    "status": sample_retail.get("status"),
                    "assertions": counts,
                    "serena_stats": sample_retail.get("serena_stats", {}),
                    "process_counts": sample_retail.get("process_counts", {}),
                    "studio_matrix": sample_retail.get("studio_matrix", {}),
                    "runtime_smoke": sample_retail.get("runtime_smoke", {}),
                },
                next_action,
            )
        )

    return gates


def audit(args: argparse.Namespace) -> dict[str, Any]:
    results_root = Path(args.results_root).expanduser().resolve()
    paths = artifact_paths(results_root)
    payloads = {key: load_json(path) for key, path in paths.items()}
    gates = build_gates(paths, payloads)

    stable_counts = count_statuses(gates, "stable_gate")
    readiness_counts = count_statuses(gates, "readiness")
    status_counts = count_statuses(gates, "status")
    hard_blockers = [
        item
        for item in gates
        if str(item["readiness"]).startswith("blocked") or item["status"] in {"blocker", "missing"}
    ]
    pending = [item for item in gates if str(item["readiness"]).startswith("pending")]

    stable_status = "blocked" if any(item["stable_gate"] in {"blocked", "missing"} for item in gates) else "achieved_with_named_boundaries"
    if hard_blockers:
        readiness_status = "not_ready"
    elif pending:
        readiness_status = "pending_acceptance_or_live_evidence"
    else:
        readiness_status = "ready"

    return {
        "schema": "agent-code-router-kit.android-readiness.v1",
        "date_utc": utc_now(),
        "results_root": str(results_root),
        "stable_status": stable_status,
        "readiness_status": readiness_status,
        "status_counts": status_counts,
        "stable_counts": stable_counts,
        "readiness_counts": readiness_counts,
        "blocker_count": len(hard_blockers),
        "pending_count": len(pending),
        "source_artifacts": {key: str(path) if path else "" for key, path in paths.items()},
        "gates": gates,
    }


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def render_markdown(data: dict[str, Any]) -> str:
    rows = [
        [item["status"], item["stable_gate"], item["readiness"], item["gate_id"], item["next_action"]]
        for item in data["gates"]
    ]
    lines = [
        f"# Android Readiness Audit - {data['date_utc']}",
        "",
        f"stable status: `{data['stable_status']}`",
        f"readiness status: `{data['readiness_status']}`",
        "",
        markdown_table(["Status", "stable", "readiness", "Gate", "Next Action"], rows),
        "",
        "## Blockers And Pending Gates",
        "",
    ]
    blockers = [
        item
        for item in data["gates"]
        if item["status"] in {"blocker", "missing"} or str(item["readiness"]).startswith("pending") or str(item["readiness"]).startswith("blocked")
    ]
    if not blockers:
        lines.append("- None.")
    else:
        for item in blockers:
            lines.append(f"- `{item['gate_id']}` `{item['status']}` / readiness `{item['readiness']}`: {item['next_action']}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Android evidence against readiness operational-completion gates.")
    parser.add_argument("--results-root", default="results/android")
    parser.add_argument("--output", default="results/android/readiness")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    parser.add_argument("--enforce-stable", action="store_true", help="Exit non-zero if stable gates are blocked.")
    parser.add_argument("--enforce-readiness", action="store_true", help="Exit non-zero if readiness is not ready.")
    args = parser.parse_args()

    data = audit(args)
    output_root = Path(args.output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    json_path = Path(args.output_json).expanduser().resolve() if args.output_json else output_root / f"android-readiness-summary-{run_id}.json"
    md_path = Path(args.output_md).expanduser().resolve() if args.output_md else output_root / f"android-readiness-{run_id}.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(data))
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"stable status: {data['stable_status']}")
    print(f"readiness status: {data['readiness_status']}")
    print(f"Status counts: {data['status_counts']}")

    if args.enforce_stable and data["stable_status"] == "blocked":
        return 3
    if args.enforce_readiness and data["readiness_status"] != "ready":
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
