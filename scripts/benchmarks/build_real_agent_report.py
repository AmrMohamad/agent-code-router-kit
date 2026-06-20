from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file


def load_runs(path: str | Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_json(path: str | Path) -> dict[str, object]:
    payload_path = Path(path)
    if not payload_path.exists():
        return {}
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_jsonl(path: str | Path) -> list[dict[str, object]]:
    payload_path = Path(path)
    if not payload_path.exists():
        return []
    rows: list[dict[str, object]] = []
    with payload_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                payload = json.loads(line)
                if isinstance(payload, dict):
                    rows.append(payload)
    return rows


def load_missing_plan(path: str | Path | None) -> dict[str, object] | None:
    if not path:
        return None
    plan_path = Path(path)
    if not plan_path.exists():
        return None
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def terminal_control_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    mode_counts: dict[str, int] = defaultdict(int)
    prompt_sent_count = 0
    sentinel_observed_count = 0
    closed_or_exited_count = 0
    capture_changed_count = 0
    run_rows: list[dict[str, object]] = []
    for row in rows:
        run_dir = Path(str(row.get("run_dir", ""))).expanduser()
        launch_plan = load_json(run_dir / "launch-plan.json") if run_dir else {}
        telemetry = load_jsonl(run_dir / "telemetry.jsonl") if run_dir else []
        events = [str(event.get("event", "")) for event in telemetry]
        event_set = set(events)
        terminal_mode = str(launch_plan.get("terminal_mode") or row.get("terminal_mode") or "unknown")
        prompt_sent = "prompt_sent" in event_set
        sentinel_observed = "sentinel_observed" in event_set or row.get("completion_reason") == "sentinel"
        closed_or_exited = bool(event_set.intersection({"process_exited", "process_timeout", "tmux_session_closed"}))
        capture_changed = "terminal_capture_changed" in event_set or "process_output_chunk" in event_set
        mode_counts[terminal_mode] += 1
        prompt_sent_count += int(prompt_sent)
        sentinel_observed_count += int(sentinel_observed)
        closed_or_exited_count += int(closed_or_exited)
        capture_changed_count += int(capture_changed)
        run_rows.append(
            {
                "run_id": row.get("run_id"),
                "agent": row.get("agent"),
                "profile": row.get("profile"),
                "task_id": row.get("task_id"),
                "repo": row.get("repo"),
                "repeat_index": row.get("repeat_index"),
                "terminal_mode": terminal_mode,
                "prompt_sent": prompt_sent,
                "sentinel_observed": sentinel_observed,
                "closed_or_exited": closed_or_exited,
                "capture_changed": capture_changed,
                "event_count": len(events),
                "events": events,
            }
        )
    return {
        "runs": len(rows),
        "terminal_modes": dict(sorted(mode_counts.items())),
        "prompt_sent_count": prompt_sent_count,
        "sentinel_observed_count": sentinel_observed_count,
        "closed_or_exited_count": closed_or_exited_count,
        "capture_changed_count": capture_changed_count,
        "rows": run_rows,
    }


def route_policy_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    blocked_tool_violation_count = 0
    required_first_tool_violation_count = 0
    checkable_required_first_tool_violation_count = 0
    output_budget_violation_count = 0
    run_rows: list[dict[str, object]] = []
    for row in rows:
        run_dir = Path(str(row.get("run_dir", ""))).expanduser()
        route_isolation = load_json(run_dir / "route-isolation.json") if run_dir else {}
        env = route_isolation.get("env") if isinstance(route_isolation.get("env"), dict) else {}
        violations = [str(item) for item in row.get("policy_violations", []) or []]
        blocked_tool_violations = [item for item in violations if item.startswith("blocked_tool_used:")]
        required_first_tool_violation = "required_first_tool_not_used" in violations
        output_budget_violation = "tool_output_over_budget" in violations
        controlled_failure = str(row.get("completion_reason", "")) in {
            "output_budget_exceeded",
            "timeout",
            "process_timeout",
            "terminal_idle_timeout",
        } or output_budget_violation
        blocked_tool_violation_count += len(blocked_tool_violations)
        required_first_tool_violation_count += int(required_first_tool_violation)
        checkable_required_first_tool_violation_count += int(required_first_tool_violation and not controlled_failure)
        output_budget_violation_count += int(output_budget_violation)
        run_rows.append(
            {
                "run_id": row.get("run_id"),
                "agent": row.get("agent"),
                "profile": row.get("profile"),
                "task_id": row.get("task_id"),
                "repo": row.get("repo"),
                "repeat_index": row.get("repeat_index"),
                "allowed_tools": str(env.get("RARB_ALLOWED_TOOLS", "")).split(",")
                if env.get("RARB_ALLOWED_TOOLS")
                else [],
                "blocked_tools": str(env.get("RARB_BLOCKED_TOOLS", "")).split(",")
                if env.get("RARB_BLOCKED_TOOLS")
                else [],
                "observed_task_tools": row.get("observed_task_tools", []),
                "blocked_tool_violations": blocked_tool_violations,
                "required_first_tool_violation": required_first_tool_violation,
                "output_budget_violation": output_budget_violation,
                "controlled_failure": controlled_failure,
            }
        )
    return {
        "runs": len(rows),
        "blocked_tool_violation_count": blocked_tool_violation_count,
        "required_first_tool_violation_count": required_first_tool_violation_count,
        "checkable_required_first_tool_violation_count": checkable_required_first_tool_violation_count,
        "output_budget_violation_count": output_budget_violation_count,
        "rows": run_rows,
    }


def filter_runs(rows: list[dict[str, object]], filters: dict[str, str]) -> list[dict[str, object]]:
    if not filters:
        return rows
    selected = []
    for row in rows:
        if all(str(row.get(key, "")) == value for key, value in filters.items() if value):
            selected.append(row)
    return selected


def median_int(values: list[int]) -> int:
    return sorted(values)[len(values) // 2] if values else 0


def compact_token_summary(items: list[dict[str, object]]) -> dict[str, object]:
    exact_totals = [int(item.get("exact_total_tokens", 0) or 0) for item in items if item.get("exact_total_tokens")]
    exact_uncached_totals = []
    for item in items:
        if item.get("exact_uncached_total_tokens"):
            exact_uncached_totals.append(int(item.get("exact_uncached_total_tokens", 0) or 0))
            continue
        if item.get("exact_total_tokens") and item.get("exact_cached_input_tokens") is not None:
            exact_uncached_totals.append(
                max(int(item.get("exact_total_tokens", 0) or 0) - int(item.get("exact_cached_input_tokens", 0) or 0), 0)
            )
    reported_totals = [
        int(item.get("agent_reported_total_tokens", 0) or 0)
        for item in items
        if item.get("agent_reported_total_tokens")
    ]
    proxy_totals = [int(item.get("model_visible_proxy_tokens", 0) or 0) for item in items]
    return {
        "median_exact_total_tokens": median_int(exact_totals),
        "median_exact_uncached_total_tokens": median_int(exact_uncached_totals),
        "median_agent_reported_total_tokens": median_int(reported_totals),
        "median_model_visible_proxy_tokens": median_int(proxy_totals),
        "exact_run_count": len(exact_totals),
        "exact_uncached_run_count": len(exact_uncached_totals),
        "agent_reported_run_count": len(reported_totals),
        "proxy_run_count": len(proxy_totals),
    }


def compact_proof_layer_summary(items: list[dict[str, object]]) -> dict[str, object]:
    true_count = sum(1 for item in items if item.get("expected_proof_layer_seen") is True)
    false_count = sum(1 for item in items if item.get("expected_proof_layer_seen") is False)
    missing_count = len(items) - true_count - false_count
    return {
        "expected_proof_layer_seen": true_count,
        "expected_proof_layer_missing": false_count + missing_count,
        "expected_proof_layer_missing_field": missing_count,
    }


def compact_route_isolation_summary(items: list[dict[str, object]]) -> dict[str, object]:
    modes: dict[str, int] = defaultdict(int)
    hard_controls: dict[str, int] = defaultdict(int)
    weak_controls: dict[str, int] = defaultdict(int)
    rows_with_hard_controls = 0
    rows_with_weak_controls = 0
    for item in items:
        modes[str(item.get("route_isolation_mode", "unknown"))] += 1
        row_hard_controls = [str(control) for control in item.get("route_hard_controls", []) or [] if str(control)]
        row_weak_controls = [str(control) for control in item.get("route_weak_controls", []) or [] if str(control)]
        if row_hard_controls:
            rows_with_hard_controls += 1
        if row_weak_controls:
            rows_with_weak_controls += 1
        for control in row_hard_controls:
            hard_controls[control] += 1
        for control in row_weak_controls:
            weak_controls[control] += 1
    return {
        "route_isolation_modes": dict(sorted(modes.items())),
        "route_hard_control_counts": dict(sorted(hard_controls.items())),
        "route_weak_control_counts": dict(sorted(weak_controls.items())),
        "runs_with_route_hard_controls": rows_with_hard_controls,
        "runs_with_route_weak_controls": rows_with_weak_controls,
    }


def summarize_group(rows: list[dict[str, object]], key: str) -> dict[str, object]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key, ""))].append(row)
    summary: dict[str, object] = {}
    for group, items in sorted(grouped.items()):
        correctness_counts: dict[str, int] = defaultdict(int)
        policy_counts: dict[str, int] = defaultdict(int)
        token_sources: dict[str, int] = defaultdict(int)
        evidence_sources: dict[str, int] = defaultdict(int)
        for item in items:
            correctness_counts[str(item.get("correctness_status", "unknown"))] += 1
            policy_counts[str(item.get("policy_adherence", "unknown"))] += 1
            token_sources[str(item.get("token_source", "unknown"))] += 1
            evidence_sources[str(item.get("tool_evidence_source", "unknown"))] += 1
        summary[group] = {
            "runs": len(items),
            **compact_token_summary(items),
            **compact_proof_layer_summary(items),
            **compact_route_isolation_summary(items),
            "median_wall_seconds": median_int([int(float(item.get("wall_seconds", 0) or 0)) for item in items]),
            "total_raw_dump_incidents": sum(int(item.get("raw_dump_incidents", 0) or 0) for item in items),
            "total_tool_output_bytes": sum(int(item.get("tool_output_bytes", 0) or 0) for item in items),
            "total_policy_violations": sum(len(item.get("policy_violations", []) or []) for item in items),
            "correctness": dict(correctness_counts),
            "policy_adherence": dict(policy_counts),
            "token_sources": dict(token_sources),
            "tool_evidence_sources": dict(evidence_sources),
        }
    return summary


def profile_pair_comparisons(
    rows: list[dict[str, object]],
    *,
    baseline_profile: str = "A-search-only",
    treatment_profile: str = "D-full-router",
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str, str], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        key = (
            str(row.get("agent", "")),
            str(row.get("task_id", "")),
            str(row.get("repo", "")),
            str(row.get("repeat_index", "")),
        )
        grouped[key][str(row.get("profile", ""))] = row
    comparisons: list[dict[str, object]] = []
    for (agent, task_id, repo, repeat_index), profiles in sorted(grouped.items()):
        baseline = profiles.get(baseline_profile)
        treatment = profiles.get(treatment_profile)
        if not baseline or not treatment:
            continue

        def int_field(row: dict[str, object], field: str) -> int:
            return int(row.get(field, 0) or 0)

        baseline_exact = int_field(baseline, "exact_total_tokens")
        treatment_exact = int_field(treatment, "exact_total_tokens")
        baseline_agent_reported = int_field(baseline, "agent_reported_total_tokens")
        treatment_agent_reported = int_field(treatment, "agent_reported_total_tokens")
        baseline_exact_uncached = int_field(baseline, "exact_uncached_total_tokens")
        treatment_exact_uncached = int_field(treatment, "exact_uncached_total_tokens")
        if not baseline_exact_uncached and baseline_exact and baseline.get("exact_cached_input_tokens") is not None:
            baseline_exact_uncached = max(baseline_exact - int_field(baseline, "exact_cached_input_tokens"), 0)
        if not treatment_exact_uncached and treatment_exact and treatment.get("exact_cached_input_tokens") is not None:
            treatment_exact_uncached = max(treatment_exact - int_field(treatment, "exact_cached_input_tokens"), 0)
        baseline_cached = int_field(baseline, "exact_cached_input_tokens")
        treatment_cached = int_field(treatment, "exact_cached_input_tokens")
        baseline_cache_creation = int_field(baseline, "exact_cache_creation_input_tokens")
        treatment_cache_creation = int_field(treatment, "exact_cache_creation_input_tokens")
        baseline_cache_read = int_field(baseline, "exact_cache_read_input_tokens")
        treatment_cache_read = int_field(treatment, "exact_cache_read_input_tokens")
        baseline_reasoning = int_field(baseline, "exact_reasoning_output_tokens")
        treatment_reasoning = int_field(treatment, "exact_reasoning_output_tokens")
        baseline_proxy = int_field(baseline, "model_visible_proxy_tokens")
        treatment_proxy = int_field(treatment, "model_visible_proxy_tokens")
        baseline_wall = float(baseline.get("wall_seconds", 0) or 0)
        treatment_wall = float(treatment.get("wall_seconds", 0) or 0)
        row = {
            "agent": agent,
            "task_id": task_id,
            "repo": repo,
            "repeat_index": repeat_index,
            "baseline_profile": baseline_profile,
            "treatment_profile": treatment_profile,
            "baseline_correctness": baseline.get("correctness_status"),
            "treatment_correctness": treatment.get("correctness_status"),
            "baseline_token_source": baseline.get("token_source"),
            "treatment_token_source": treatment.get("token_source"),
            "baseline_exact_total_tokens": baseline_exact or None,
            "treatment_exact_total_tokens": treatment_exact or None,
            "baseline_agent_reported_total_tokens": baseline_agent_reported or None,
            "treatment_agent_reported_total_tokens": treatment_agent_reported or None,
            "baseline_exact_uncached_total_tokens": baseline_exact_uncached or None,
            "treatment_exact_uncached_total_tokens": treatment_exact_uncached or None,
            "baseline_exact_cached_input_tokens": baseline_cached or None,
            "treatment_exact_cached_input_tokens": treatment_cached or None,
            "cached_input_token_delta": (treatment_cached - baseline_cached) if baseline_cached or treatment_cached else None,
            "baseline_exact_cache_creation_input_tokens": baseline_cache_creation or None,
            "treatment_exact_cache_creation_input_tokens": treatment_cache_creation or None,
            "cache_creation_input_token_delta": (treatment_cache_creation - baseline_cache_creation)
            if baseline_cache_creation or treatment_cache_creation
            else None,
            "baseline_exact_cache_read_input_tokens": baseline_cache_read or None,
            "treatment_exact_cache_read_input_tokens": treatment_cache_read or None,
            "cache_read_input_token_delta": (treatment_cache_read - baseline_cache_read)
            if baseline_cache_read or treatment_cache_read
            else None,
            "baseline_exact_reasoning_output_tokens": baseline_reasoning or None,
            "treatment_exact_reasoning_output_tokens": treatment_reasoning or None,
            "reasoning_output_token_delta": (treatment_reasoning - baseline_reasoning)
            if baseline_reasoning or treatment_reasoning
            else None,
            "exact_total_token_delta": (treatment_exact - baseline_exact) if baseline_exact and treatment_exact else None,
            "exact_total_token_savings_percent": round(
                ((baseline_exact - treatment_exact) / baseline_exact) * 100,
                2,
            )
            if baseline_exact and treatment_exact
            else None,
            "exact_uncached_total_token_delta": (treatment_exact_uncached - baseline_exact_uncached)
            if baseline_exact_uncached and treatment_exact_uncached
            else None,
            "exact_uncached_total_token_savings_percent": round(
                ((baseline_exact_uncached - treatment_exact_uncached) / baseline_exact_uncached) * 100,
                2,
            )
            if baseline_exact_uncached and treatment_exact_uncached
            else None,
            "agent_reported_total_token_delta": (treatment_agent_reported - baseline_agent_reported)
            if baseline_agent_reported and treatment_agent_reported
            else None,
            "agent_reported_total_token_savings_percent": round(
                ((baseline_agent_reported - treatment_agent_reported) / baseline_agent_reported) * 100,
                2,
            )
            if baseline_agent_reported and treatment_agent_reported
            else None,
            "baseline_model_visible_proxy_tokens": baseline_proxy,
            "treatment_model_visible_proxy_tokens": treatment_proxy,
            "model_visible_proxy_token_delta": treatment_proxy - baseline_proxy,
            "model_visible_proxy_token_savings_percent": round(
                ((baseline_proxy - treatment_proxy) / baseline_proxy) * 100,
                2,
            )
            if baseline_proxy
            else None,
            "baseline_wall_seconds": baseline_wall,
            "treatment_wall_seconds": treatment_wall,
            "wall_seconds_delta": round(treatment_wall - baseline_wall, 6),
        }
        comparisons.append(row)
    return comparisons


def route_claim_readiness(comparisons: list[dict[str, object]]) -> dict[str, object]:
    """Gate route-effect claims separately from measurement readiness.

    A paired comparison can prove that the benchmark measured two runs without
    proving that the treatment saved tokens. Reports should make that
    difference machine-readable so docs and downstream summaries do not turn a
    paired measurement into a savings claim.
    """

    rows: list[dict[str, object]] = []
    for comparison in comparisons:
        exact_savings = comparison.get("exact_total_token_savings_percent")
        exact_uncached_savings = comparison.get("exact_uncached_total_token_savings_percent")
        agent_reported_savings = comparison.get("agent_reported_total_token_savings_percent")
        proxy_savings = comparison.get("model_visible_proxy_token_savings_percent")
        correctness_ok = (
            comparison.get("baseline_correctness") == "pass"
            and comparison.get("treatment_correctness") == "pass"
        )
        exact_token_sources_match = (
            comparison.get("baseline_token_source") == comparison.get("treatment_token_source") == "exact"
        )
        agent_reported_token_sources_match = (
            comparison.get("baseline_token_source") == comparison.get("treatment_token_source") == "agent_reported"
        )
        exact_savings_ok = (
            correctness_ok
            and exact_token_sources_match
            and isinstance(exact_savings, (int, float))
            and exact_savings > 0
        )
        exact_uncached_savings_ok = (
            correctness_ok
            and exact_token_sources_match
            and isinstance(exact_uncached_savings, (int, float))
            and exact_uncached_savings > 0
        )
        agent_reported_savings_ok = (
            correctness_ok
            and agent_reported_token_sources_match
            and isinstance(agent_reported_savings, (int, float))
            and agent_reported_savings > 0
        )
        proxy_savings_ok = correctness_ok and isinstance(proxy_savings, (int, float)) and proxy_savings > 0
        rows.append(
            {
                "agent": comparison.get("agent"),
                "task_id": comparison.get("task_id"),
                "repo": comparison.get("repo"),
                "repeat_index": comparison.get("repeat_index"),
                "correctness_ok": correctness_ok,
                "exact_token_savings_claim_supported": exact_savings_ok,
                "exact_uncached_token_savings_claim_supported": exact_uncached_savings_ok,
                "agent_reported_token_savings_claim_supported": agent_reported_savings_ok,
                "model_visible_proxy_savings_claim_supported": proxy_savings_ok,
                "exact_token_savings_percent": exact_savings,
                "exact_uncached_token_savings_percent": exact_uncached_savings,
                "agent_reported_token_savings_percent": agent_reported_savings,
                "model_visible_proxy_token_savings_percent": proxy_savings,
                "baseline_exact_uncached_total_tokens": comparison.get("baseline_exact_uncached_total_tokens"),
                "treatment_exact_uncached_total_tokens": comparison.get("treatment_exact_uncached_total_tokens"),
                "exact_uncached_total_token_delta": comparison.get("exact_uncached_total_token_delta"),
                "baseline_agent_reported_total_tokens": comparison.get("baseline_agent_reported_total_tokens"),
                "treatment_agent_reported_total_tokens": comparison.get("treatment_agent_reported_total_tokens"),
                "agent_reported_total_token_delta": comparison.get("agent_reported_total_token_delta"),
                "exact_claim_blockers": [
                    blocker
                    for blocker, present in (
                        ("correctness_not_pass_pass", not correctness_ok),
                        ("exact_token_sources_not_matched", not exact_token_sources_match),
                        ("exact_token_savings_not_positive", not (isinstance(exact_savings, (int, float)) and exact_savings > 0)),
                    )
                    if present
                ],
                "proxy_claim_blockers": [
                    blocker
                    for blocker, present in (
                        ("correctness_not_pass_pass", not correctness_ok),
                        ("model_visible_proxy_savings_not_positive", not (isinstance(proxy_savings, (int, float)) and proxy_savings > 0)),
                    )
                    if present
                ],
                "agent_reported_claim_blockers": [
                    blocker
                    for blocker, present in (
                        ("correctness_not_pass_pass", not correctness_ok),
                        ("agent_reported_token_sources_not_matched", not agent_reported_token_sources_match),
                        (
                            "agent_reported_token_savings_not_positive",
                            not (isinstance(agent_reported_savings, (int, float)) and agent_reported_savings > 0),
                        ),
                    )
                    if present
                ],
                "exact_uncached_claim_blockers": [
                    blocker
                    for blocker, present in (
                        ("correctness_not_pass_pass", not correctness_ok),
                        ("exact_token_sources_not_matched", not exact_token_sources_match),
                        (
                            "exact_uncached_token_savings_not_positive",
                            not (isinstance(exact_uncached_savings, (int, float)) and exact_uncached_savings > 0),
                        ),
                    )
                    if present
                ],
            }
        )
    return {
        "paired_comparisons": len(rows),
        "exact_token_savings_claims_supported": sum(
            1 for row in rows if row["exact_token_savings_claim_supported"]
        ),
        "exact_uncached_token_savings_claims_supported": sum(
            1 for row in rows if row["exact_uncached_token_savings_claim_supported"]
        ),
        "agent_reported_token_savings_claims_supported": sum(
            1 for row in rows if row["agent_reported_token_savings_claim_supported"]
        ),
        "model_visible_proxy_savings_claims_supported": sum(
            1 for row in rows if row["model_visible_proxy_savings_claim_supported"]
        ),
        "rows": rows,
    }


def matrix_completion_summary(missing_plan: dict[str, object] | None) -> dict[str, object] | None:
    if not missing_plan:
        return None
    execution_plan = (
        missing_plan.get("execution_plan")
        if isinstance(missing_plan.get("execution_plan"), dict)
        else {}
    )
    return {
        "status": execution_plan.get("status", "unknown"),
        "can_resume_now": execution_plan.get("can_resume_now", False),
        "completion_boundary": execution_plan.get("completion_boundary", ""),
        "missing_cell_count": missing_plan.get("missing_cell_count", 0),
        "runnable_missing_cell_count": missing_plan.get("runnable_missing_cell_count", 0),
        "blocked_agents": missing_plan.get("blocked_agents", []),
        "unknown_agents": missing_plan.get("unknown_agents", []),
        "missing_by_agent": execution_plan.get("missing_by_agent", {}),
        "blocked_actions": execution_plan.get("blocked_actions", []),
        "missing_repo_map_entries": missing_plan.get("missing_repo_map_entries", []),
    }


def summarize_runs(
    rows: list[dict[str, object]],
    *,
    missing_plan: dict[str, object] | None = None,
) -> dict[str, object]:
    by_profile: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        by_profile[str(row.get("profile", ""))].append(row)
    profiles: dict[str, object] = {}
    for profile, items in sorted(by_profile.items()):
        profiles[profile] = {
            "runs": len(items),
            **compact_token_summary(items),
            **compact_proof_layer_summary(items),
            **compact_route_isolation_summary(items),
            "total_raw_dump_incidents": sum(int(item.get("raw_dump_incidents", 0) or 0) for item in items),
            "total_tool_output_bytes": sum(int(item.get("tool_output_bytes", 0) or 0) for item in items),
            "total_policy_violations": sum(len(item.get("policy_violations", []) or []) for item in items),
            "correctness": defaultdict(int),
            "tool_evidence_sources": defaultdict(int),
        }
        correctness_counts: dict[str, int] = defaultdict(int)
        evidence_counts: dict[str, int] = defaultdict(int)
        for item in items:
            correctness_counts[str(item.get("correctness_status", "unknown"))] += 1
            evidence_counts[str(item.get("tool_evidence_source", "unknown"))] += 1
        profiles[profile]["correctness"] = dict(correctness_counts)
        profiles[profile]["tool_evidence_sources"] = dict(evidence_counts)
    comparisons = profile_pair_comparisons(rows)
    terminal_summary = terminal_control_summary(rows)
    route_policy = route_policy_summary(rows)
    return {
        "runs": len(rows),
        "profiles": profiles,
        "agents": summarize_group(rows, "agent"),
        "task_families": summarize_group(rows, "task_family"),
        "token_sources": summarize_group(rows, "token_source"),
        "route_comparisons": comparisons,
        "route_claim_readiness": route_claim_readiness(comparisons),
        "matrix_completion": matrix_completion_summary(missing_plan),
        "terminal_control": terminal_summary,
        "route_policy": route_policy,
    }


def build_markdown(summary: dict[str, object]) -> str:
    lines = ["# Real Agent Routing Benchmark Report", ""]
    lines.append(f"Total runs: {summary['runs']}")
    matrix_completion = summary.get("matrix_completion")
    if isinstance(matrix_completion, dict):
        lines.extend(
            [
                "",
                "## Matrix Completion",
                "",
                f"- Status: `{matrix_completion.get('status', 'unknown')}`",
                f"- Missing cells: `{matrix_completion.get('missing_cell_count', 0)}`",
                f"- Runnable missing cells now: `{matrix_completion.get('runnable_missing_cell_count', 0)}`",
                f"- Can resume now: `{str(matrix_completion.get('can_resume_now', False)).lower()}`",
                f"- Completion boundary: {matrix_completion.get('completion_boundary', '')}",
            ]
        )
        blocked_agents = matrix_completion.get("blocked_agents")
        if blocked_agents:
            lines.append(f"- Blocked agents: `{','.join(str(agent) for agent in blocked_agents)}`")
        if int(matrix_completion.get("missing_cell_count", 0) or 0) > 0:
            lines.append("")
            lines.append(
                "This report is not a full requested-agent matrix; route and savings claims must be scoped to the completed rows."
            )
    lines.append("")
    terminal_control = summary.get("terminal_control")
    if isinstance(terminal_control, dict):
        lines.extend(
            [
                "## Terminal Control",
                "",
                f"- Terminal modes: `{json.dumps(terminal_control.get('terminal_modes', {}), sort_keys=True)}`",
                f"- Prompt sent: `{terminal_control.get('prompt_sent_count', 0)} / {terminal_control.get('runs', 0)}`",
                f"- Sentinel observed: `{terminal_control.get('sentinel_observed_count', 0)} / {terminal_control.get('runs', 0)}`",
                f"- Process/session closed: `{terminal_control.get('closed_or_exited_count', 0)} / {terminal_control.get('runs', 0)}`",
                "",
            ]
        )
    route_policy = summary.get("route_policy")
    if isinstance(route_policy, dict):
        lines.extend(
            [
                "## Route Policy",
                "",
                f"- Blocked-tool violations: `{route_policy.get('blocked_tool_violation_count', 0)}`",
                f"- Required-first-tool violations: `{route_policy.get('required_first_tool_violation_count', 0)}`",
                f"- Checkable required-first-tool violations: `{route_policy.get('checkable_required_first_tool_violation_count', 0)}`",
                f"- Output-budget violations: `{route_policy.get('output_budget_violation_count', 0)}`",
                "",
            ]
        )
    lines.append("| Profile | Runs | Median exact tokens | Median uncached exact tokens | Median reported tokens | Median visible proxy tokens | Proof layers seen | Hard-isolated runs | Weak-isolated runs | Tool output bytes | Raw dumps | Policy violations | Correctness | Tool evidence |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
    for profile, data in summary["profiles"].items():  # type: ignore[index,union-attr]
        lines.append(
            f"| {profile} | {data['runs']} | {data.get('median_exact_total_tokens', 0)} | "
            f"{data.get('median_exact_uncached_total_tokens', 0)} | "
            f"{data.get('median_agent_reported_total_tokens', 0)} | "
            f"{data['median_model_visible_proxy_tokens']} | "
            f"{data.get('expected_proof_layer_seen', 0)}/{data.get('runs', 0)} | "
            f"{data.get('runs_with_route_hard_controls', 0)} | "
            f"{data.get('runs_with_route_weak_controls', 0)} | "
            f"{data.get('total_tool_output_bytes', 0)} | {data['total_raw_dump_incidents']} | "
            f"{data.get('total_policy_violations', 0)} | {json.dumps(data['correctness'], sort_keys=True)} | "
            f"{json.dumps(data.get('tool_evidence_sources', {}), sort_keys=True)} |"
        )
    lines.append("")
    lines.append("Token values are proxy tokens unless exact token fields are explicitly present in run artifacts.")
    comparisons = summary.get("route_comparisons", [])
    if comparisons:
        claim_readiness = summary.get("route_claim_readiness", {})
        lines.extend(
            [
                "",
                "## Paired Route Comparisons",
                "",
                "| Agent | Task | Repeat | Exact token delta | Exact savings % | Uncached exact delta | Uncached exact savings % | Agent-reported delta | Agent-reported savings % | Proxy token delta | Proxy savings % | Wall seconds delta |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        comparison_rows = comparisons if isinstance(comparisons, list) else []
        for row in comparison_rows:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"| {row.get('agent', '')} | {row.get('task_id', '')} | {row.get('repeat_index', '')} | "
                f"{row.get('exact_total_token_delta', '')} | {row.get('exact_total_token_savings_percent', '')} | "
                f"{row.get('exact_uncached_total_token_delta', '')} | "
                f"{row.get('exact_uncached_total_token_savings_percent', '')} | "
                f"{row.get('agent_reported_total_token_delta', '')} | "
                f"{row.get('agent_reported_total_token_savings_percent', '')} | "
                f"{row.get('model_visible_proxy_token_delta', '')} | "
                f"{row.get('model_visible_proxy_token_savings_percent', '')} | "
                f"{row.get('wall_seconds_delta', '')} |"
            )
        if isinstance(claim_readiness, dict):
            lines.extend(
                [
                    "",
                    "## Claim Readiness",
                    "",
                    f"- Exact-token savings claims supported: {claim_readiness.get('exact_token_savings_claims_supported', 0)} / {claim_readiness.get('paired_comparisons', 0)}",
                    f"- Uncached exact-token savings claims supported: {claim_readiness.get('exact_uncached_token_savings_claims_supported', 0)} / {claim_readiness.get('paired_comparisons', 0)}",
                    f"- Agent-reported token savings claims supported: {claim_readiness.get('agent_reported_token_savings_claims_supported', 0)} / {claim_readiness.get('paired_comparisons', 0)}",
                    f"- Model-visible proxy savings claims supported: {claim_readiness.get('model_visible_proxy_savings_claims_supported', 0)} / {claim_readiness.get('paired_comparisons', 0)}",
                    "",
                    "A paired comparison proves measurement coverage. A savings claim also requires pass/pass correctness, comparable token sources, and a positive savings delta for the metric being claimed.",
                ]
            )
    return "\n".join(lines) + "\n"


def build_codex_tui_summary(
    summary: dict[str, object],
    *,
    out_dir: str | Path | None = None,
    dry_run: bool | None = None,
) -> str:
    profiles = summary.get("profiles", {})
    profile_count = len(profiles) if isinstance(profiles, dict) else 0
    run_count = int(summary.get("runs", 0) or 0)
    mode_label = "dry-run" if dry_run is True else "live" if dry_run is False else "benchmark"
    lines = [
        f"• Ran real-agent routing benchmark ({mode_label}) across {profile_count} profiles",
        f"  └ {run_count} runs recorded",
        "",
        "• Updated Plan",
        "  ✓ Build task packets, transcripts, telemetry, metrics, and judge records.",
        "  ✓ Summarize profile-level correctness and context proxy tokens.",
        "  ✓ Keep route-effect claims separate from harness execution proof.",
        "",
        "-" * 96,
        "",
        f"Benchmark {mode_label} completed.",
        "",
        "Evidence:",
    ]
    if isinstance(profiles, dict):
        for profile, data in profiles.items():
            if not isinstance(data, dict):
                continue
            correctness = data.get("correctness", {})
            pass_count = correctness.get("pass", correctness.get("dry_run_contract_pass", 0)) if isinstance(correctness, dict) else 0
            lines.append(
                f"- {profile}: {data.get('runs', 0)} runs, {pass_count} pass, "
                f"{data.get('expected_proof_layer_seen', 0)}/{data.get('runs', 0)} proof layers seen, "
                f"{data.get('runs_with_route_hard_controls', 0)} hard-isolated runs, "
                f"{data.get('runs_with_route_weak_controls', 0)} weak-isolated runs, "
                f"{data.get('total_raw_dump_incidents', 0)} raw dump incidents, "
                f"{data.get('total_policy_violations', 0)} policy violations, "
                f"median visible proxy tokens {data.get('median_model_visible_proxy_tokens', 0)}"
            )
    if out_dir is not None:
        lines.append(f"- Artifacts: {Path(out_dir)}")
    lines.extend(
        [
            "",
            (
                "This proves live harness execution and artifact generation."
                if dry_run is False
                else "Dry-run output proves harness shape only; it does not prove live-agent token savings."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def write_report(
    *,
    runs_jsonl: str | Path,
    out_dir: str | Path,
    dry_run: bool | None = None,
    filters: dict[str, str] | None = None,
    missing_plan: str | Path | dict[str, object] | None = None,
) -> dict[str, object]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = filter_runs(load_runs(runs_jsonl), filters or {})
    missing_plan_payload = (
        missing_plan
        if isinstance(missing_plan, dict)
        else load_missing_plan(missing_plan)
    )
    summary = summarize_runs(rows, missing_plan=missing_plan_payload)
    to_json_file(out / "metrics-summary.json", summary)
    if summary.get("matrix_completion") is not None:
        to_json_file(out / "matrix-completion-summary.json", summary["matrix_completion"])
    to_json_file(out / "terminal-control-summary.json", summary.get("terminal_control", {}))
    to_json_file(out / "route-policy-summary.json", summary.get("route_policy", {}))
    to_json_file(out / "route-comparisons.json", summary.get("route_comparisons", []))
    to_json_file(out / "route-claim-readiness.json", summary.get("route_claim_readiness", {}))
    to_json_file(
        out / "proof-layer-summary.json",
        {
            "profiles": {
                profile: {
                    "runs": data.get("runs", 0),
                    "expected_proof_layer_seen": data.get("expected_proof_layer_seen", 0),
                    "expected_proof_layer_missing": data.get("expected_proof_layer_missing", 0),
                    "expected_proof_layer_missing_field": data.get("expected_proof_layer_missing_field", 0),
                }
                for profile, data in summary.get("profiles", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
            "agents": {
                agent: {
                    "runs": data.get("runs", 0),
                    "expected_proof_layer_seen": data.get("expected_proof_layer_seen", 0),
                    "expected_proof_layer_missing": data.get("expected_proof_layer_missing", 0),
                    "expected_proof_layer_missing_field": data.get("expected_proof_layer_missing_field", 0),
                }
                for agent, data in summary.get("agents", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
            "task_families": {
                family: {
                    "runs": data.get("runs", 0),
                    "expected_proof_layer_seen": data.get("expected_proof_layer_seen", 0),
                    "expected_proof_layer_missing": data.get("expected_proof_layer_missing", 0),
                    "expected_proof_layer_missing_field": data.get("expected_proof_layer_missing_field", 0),
                }
                for family, data in summary.get("task_families", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
        },
    )
    to_json_file(
        out / "route-isolation-summary.json",
        {
            "profiles": {
                profile: {
                    "runs": data.get("runs", 0),
                    "route_isolation_modes": data.get("route_isolation_modes", {}),
                    "route_hard_control_counts": data.get("route_hard_control_counts", {}),
                    "route_weak_control_counts": data.get("route_weak_control_counts", {}),
                    "runs_with_route_hard_controls": data.get("runs_with_route_hard_controls", 0),
                    "runs_with_route_weak_controls": data.get("runs_with_route_weak_controls", 0),
                }
                for profile, data in summary.get("profiles", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
            "agents": {
                agent: {
                    "runs": data.get("runs", 0),
                    "route_isolation_modes": data.get("route_isolation_modes", {}),
                    "route_hard_control_counts": data.get("route_hard_control_counts", {}),
                    "route_weak_control_counts": data.get("route_weak_control_counts", {}),
                    "runs_with_route_hard_controls": data.get("runs_with_route_hard_controls", 0),
                    "runs_with_route_weak_controls": data.get("runs_with_route_weak_controls", 0),
                }
                for agent, data in summary.get("agents", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
            "task_families": {
                family: {
                    "runs": data.get("runs", 0),
                    "route_isolation_modes": data.get("route_isolation_modes", {}),
                    "route_hard_control_counts": data.get("route_hard_control_counts", {}),
                    "route_weak_control_counts": data.get("route_weak_control_counts", {}),
                    "runs_with_route_hard_controls": data.get("runs_with_route_hard_controls", 0),
                    "runs_with_route_weak_controls": data.get("runs_with_route_weak_controls", 0),
                }
                for family, data in summary.get("task_families", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
        },
    )
    to_json_file(
        out / "policy-violations.json",
        [
            {
                "run_id": row.get("run_id"),
                "agent": row.get("agent"),
                "profile": row.get("profile"),
                "task_id": row.get("task_id"),
                "violations": row.get("policy_violations", []),
            }
            for row in rows
            if row.get("policy_violations")
        ],
    )
    to_json_file(
        out / "correctness-summary.json",
        {
            "profiles": {
                profile: data.get("correctness", {})
                for profile, data in summary.get("profiles", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
            "task_families": {
                family: data.get("correctness", {})
                for family, data in summary.get("task_families", {}).items()  # type: ignore[union-attr]
                if isinstance(data, dict)
            },
        },
    )
    (out / "token-savings-report.md").write_text(build_markdown(summary), encoding="utf-8")
    (out / "codex-tui-summary.md").write_text(
        build_codex_tui_summary(summary, out_dir=out, dry_run=dry_run),
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a RARB summary report from runs.jsonl.")
    parser.add_argument("--runs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--agent", default="")
    parser.add_argument("--profile", default="")
    parser.add_argument("--task-family", default="")
    parser.add_argument("--repeat-index", default="")
    parser.add_argument("--token-source", default="")
    parser.add_argument("--tool-evidence-source", default="")
    parser.add_argument("--correctness-status", default="")
    parser.add_argument("--policy-adherence", default="")
    parser.add_argument("--missing-plan", help="Optional missing-run plan JSON to include matrix completion status.")
    args = parser.parse_args(argv)
    filters = {
        "agent": args.agent,
        "profile": args.profile,
        "task_family": args.task_family,
        "repeat_index": args.repeat_index,
        "token_source": args.token_source,
        "tool_evidence_source": args.tool_evidence_source,
        "correctness_status": args.correctness_status,
        "policy_adherence": args.policy_adherence,
    }
    summary = write_report(runs_jsonl=args.runs, out_dir=args.out, filters=filters, missing_plan=args.missing_plan)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
