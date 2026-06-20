from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
import re

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.build_real_agent_report import load_runs
from scripts.benchmarks.run_real_agent_benchmark import profile_path
from scripts.lib.agent_session import to_json_file, utc_now

SERENA_PROCESS_STATE_WARNING_CODES = {
    "multiple_serena_mcp_processes",
    "multiple_kotlin_lsp_processes",
    "multiple_json_lsp_processes",
}
from scripts.lib.agent_session import load_route_profile


GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
CONTROLLED_FAILURE_REASONS = {
    "output_budget_exceeded",
    "timeout",
    "process_timeout",
    "terminal_idle_timeout",
}
REQUIRED_RUN_ARTIFACTS = {
    "task-packet.md",
    "transcript.txt",
    "telemetry.jsonl",
    "metrics.normalized.json",
    "judge.json",
    "route-isolation.json",
}
DEMO_TASK_MANIFEST_MARKERS = (".sample.", ".example.")


def load_json(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_jsonl(path: str | Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def has_non_proxy_token_totals(row: dict[str, object]) -> bool:
    token_source = str(row.get("token_source") or row.get("probe_token_source") or "")
    if token_source == "exact":
        return (row.get("exact_total_tokens") if "exact_total_tokens" in row else row.get("probe_exact_total_tokens")) is not None
    if token_source == "agent_reported":
        return (
            row.get("agent_reported_total_tokens")
            if "agent_reported_total_tokens" in row
            else row.get("probe_agent_reported_total_tokens")
        ) is not None
    return False


def is_demo_task_manifest(path: str) -> bool:
    name = Path(path).name.lower()
    return any(marker in name for marker in DEMO_TASK_MANIFEST_MARKERS)


def normalized_path(value: object) -> str:
    if not value:
        return ""
    return str(Path(str(value)).expanduser().resolve())


def adapter_rows(paths: list[str | Path] | None) -> list[dict[str, object]]:
    if not paths:
        return []
    merged: list[dict[str, object]] = []
    for path in paths:
        candidate = Path(path)
        if candidate.is_dir():
            probe_summary = candidate / "adapter-probe-summary.json"
            doctor_summary = candidate / "adapter-doctor-summary.json"
            candidate = probe_summary if probe_summary.exists() else doctor_summary
        if not candidate.exists():
            continue
        payload = load_json(candidate)
        rows = payload.get("rows", [])
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                normalized = dict(row)
                if "completion_reason" not in normalized and "probe_completion_reason" in normalized:
                    normalized["completion_reason"] = normalized.get("probe_completion_reason")
                if "reason" not in normalized and "probe_reason" in normalized:
                    normalized["reason"] = normalized.get("probe_reason")
                merged.append(normalized)
    return merged


def add_issue(issues: list[dict[str, object]], severity: str, check: str, message: str, **details: object) -> None:
    issues.append({"severity": severity, "check": check, "message": message, **details})


def requirement_status(
    *,
    issues: list[dict[str, object]],
    key: str,
    label: str,
    checks: set[str],
    requested: bool,
    evidence: dict[str, object],
) -> dict[str, object]:
    blockers = [
        str(issue.get("message", ""))
        for issue in issues
        if issue.get("severity") == "fail" and str(issue.get("check", "")) in checks
    ]
    if not requested:
        status = "not_requested"
    elif blockers:
        status = "fail"
    else:
        status = "pass"
    return {
        "key": key,
        "label": label,
        "status": status,
        "checks": sorted(checks),
        "evidence": evidence,
        "blockers": blockers,
    }


def run_matrix(rows: list[dict[str, object]]) -> dict[tuple[str, str], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row.get("agent", "")), str(row.get("profile", "")))].append(row)
    return grouped


def is_controlled_failure(row: dict[str, object]) -> bool:
    completion_reason = str(row.get("completion_reason", ""))
    if completion_reason in CONTROLLED_FAILURE_REASONS:
        return True
    violations = row.get("policy_violations")
    if isinstance(violations, list) and "tool_output_over_budget" in violations:
        return True
    return False


def rows_to_check(items: list[dict[str, object]], *, allow_controlled_failures: bool) -> list[dict[str, object]]:
    if not allow_controlled_failures:
        return items
    return [item for item in items if not is_controlled_failure(item)]


def run_dir_is_under_root(*, run_dir: Path, root: Path) -> bool:
    try:
        run_dir.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def load_route_comparisons(root: Path) -> list[dict[str, object]]:
    path = root / "route-comparisons.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def load_route_claim_readiness(root: Path) -> dict[str, object]:
    path = root / "route-claim-readiness.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_matrix_completion(root: Path) -> dict[str, object]:
    path = root / "matrix-completion-summary.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_terminal_control_summary(root: Path) -> dict[str, object]:
    path = root / "terminal-control-summary.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_route_policy_summary(root: Path) -> dict[str, object]:
    path = root / "route-policy-summary.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def run_pair_matrix(rows: list[dict[str, object]]) -> dict[tuple[str, str, str, str], set[str]]:
    grouped: dict[tuple[str, str, str, str], set[str]] = defaultdict(set)
    for row in rows:
        key = (
            str(row.get("agent", "")),
            str(row.get("task_id", "")),
            str(row.get("repo", "")),
            str(row.get("repeat_index", "")),
        )
        grouped[key].add(str(row.get("profile", "")))
    return grouped


def observed_task_repeat_keys(rows: list[dict[str, object]]) -> list[tuple[str, str, str]]:
    keys = {
        (
            str(row.get("task_id", "")),
            str(row.get("repo", "")),
            str(row.get("repeat_index", "")),
        )
        for row in rows
        if row.get("task_id") is not None and row.get("repeat_index") is not None
    }
    return sorted(keys)


def audit(
    *,
    benchmark_out: str | Path,
    adapter_probe: list[str | Path] | None,
    expected_agents: list[str],
    expected_profiles: list[str],
    min_tasks: int,
    require_live: bool,
    require_clean_repos: bool,
    require_all_adapters: bool,
    require_all_pass: bool,
    require_observed_tools: bool,
    require_non_proxy_tokens: bool,
    require_no_weak_route_controls: bool,
    require_hard_isolation_for_blocked_tools: bool,
    require_paired_route_comparisons: bool,
    required_savings_claim: str = "",
    require_live_lifecycle_telemetry: bool = False,
    require_fresh_sessions: bool = False,
    require_randomized_order: bool = False,
    require_repo_snapshots: bool = False,
    require_repo_metadata: bool = False,
    require_real_task_manifest: bool = False,
    require_balanced_matrix: bool = False,
    require_self_contained_artifacts: bool = False,
    require_clean_serena_process_state: bool = False,
    require_expected_proof_layer: bool = False,
    require_matrix_completion_report: bool = False,
    require_terminal_control_summary: bool = False,
    require_route_policy_summary: bool = False,
    missing_plan: str | Path | None = None,
    allow_controlled_failures: bool = False,
    min_supported_savings_pairs: int = 0,
) -> dict[str, object]:
    root = Path(benchmark_out)
    issues: list[dict[str, object]] = []
    manifest_path = root / "run-manifest.json"
    runs_path = root / "runs.jsonl"
    if not manifest_path.exists():
        add_issue(issues, "fail", "manifest_exists", "run-manifest.json is missing", path=str(manifest_path))
        manifest: dict[str, object] = {}
    else:
        manifest = load_json(manifest_path)
    if not runs_path.exists():
        add_issue(issues, "fail", "runs_exist", "runs.jsonl is missing", path=str(runs_path))
        rows: list[dict[str, object]] = []
    else:
        rows = load_runs(runs_path)

    if require_live and manifest.get("live") is not True:
        add_issue(issues, "fail", "live_mode", "benchmark manifest is not a live run")
    if require_fresh_sessions and manifest.get("fresh_session_per_run") is not True:
        add_issue(issues, "fail", "fresh_sessions", "manifest does not prove fresh session per run")
    if require_fresh_sessions and rows:
        seen_session_identities: dict[str, str] = {}
        for row in rows:
            run_id = str(row.get("run_id", ""))
            telemetry_path = Path(str(row.get("run_dir", ""))).expanduser() / "telemetry.jsonl"
            if not telemetry_path.exists():
                add_issue(
                    issues,
                    "fail",
                    "fresh_sessions",
                    f"fresh-session proof is missing telemetry.jsonl for run {run_id}",
                    run_id=run_id,
                    path=str(telemetry_path),
                )
                continue
            telemetry_events = load_jsonl(telemetry_path)
            identity = ""
            for event in telemetry_events:
                event_name = str(event.get("event", ""))
                if event_name == "tmux_session_started" and event.get("session"):
                    identity = f"tmux:{event.get('session')}"
                    break
                if event_name == "process_spawned" and event.get("pid") is not None:
                    identity = f"pid:{event.get('pid')}"
                    break
            if not identity:
                add_issue(
                    issues,
                    "fail",
                    "fresh_sessions",
                    f"fresh-session proof has no tmux session or process pid for run {run_id}",
                    run_id=run_id,
                    path=str(telemetry_path),
                )
                continue
            previous_run = seen_session_identities.get(identity)
            if previous_run:
                add_issue(
                    issues,
                    "fail",
                    "fresh_sessions",
                    f"fresh-session proof reused terminal/process identity for run {run_id}",
                    run_id=run_id,
                    previous_run_id=previous_run,
                    identity=identity,
                )
            else:
                seen_session_identities[identity] = run_id
    if require_randomized_order and manifest.get("order_randomized") is not True:
        add_issue(issues, "fail", "randomized_order", "manifest does not prove randomized run order")
    if int(manifest.get("task_count", 0) or 0) < min_tasks:
        add_issue(
            issues,
            "fail",
            "task_count",
            f"benchmark has fewer tasks than required: {manifest.get('task_count', 0)} < {min_tasks}",
            actual=manifest.get("task_count", 0),
            required=min_tasks,
        )
    if require_real_task_manifest:
        task_manifest = str(manifest.get("task_manifest") or "")
        if not task_manifest:
            add_issue(issues, "fail", "real_task_manifest", "manifest has no task_manifest")
        elif is_demo_task_manifest(task_manifest):
            add_issue(
                issues,
                "fail",
                "real_task_manifest",
                "task manifest is a sample/example manifest",
                task_manifest=task_manifest,
            )
        elif not Path(task_manifest).exists():
            add_issue(
                issues,
                "fail",
                "real_task_manifest",
                "task manifest path does not exist",
                task_manifest=task_manifest,
            )
    if require_clean_serena_process_state:
        if manifest.get("require_clean_serena_process_state") is not True:
            add_issue(
                issues,
                "fail",
                "serena_process_state",
                "manifest does not prove clean Serena process-state enforcement was enabled",
            )
        for row in rows:
            warnings = row.get("serena_readiness_warnings")
            if not isinstance(warnings, list):
                continue
            process_warnings = [str(warning) for warning in warnings if str(warning) in SERENA_PROCESS_STATE_WARNING_CODES]
            if process_warnings:
                add_issue(
                    issues,
                    "fail",
                    "serena_process_state",
                    f"run has stale Serena process-state warnings: {row.get('run_id')}",
                    run_id=row.get("run_id"),
                    warnings=process_warnings,
                )
    if require_clean_repos:
        for repo_id, state in dict(manifest.get("repo_states", {}) or {}).items():
            if isinstance(state, dict) and state.get("dirty"):
                add_issue(
                    issues,
                    "fail",
                    "clean_repo",
                    f"repo is dirty: {repo_id}",
                    repo_id=repo_id,
                    dirty_entries=state.get("dirty_entries"),
                    path=state.get("path"),
                )
    if require_repo_metadata:
        repo_states = dict(manifest.get("repo_states", {}) or {})
        repo_map = dict(manifest.get("repo_map", {}) or {})
        row_repo_ids = {str(row.get("repo", "")) for row in rows if str(row.get("repo", ""))}
        missing_repo_map_entries = sorted(repo_id for repo_id in row_repo_ids if repo_id not in repo_map)
        for repo_id in missing_repo_map_entries:
            add_issue(
                issues,
                "fail",
                "repo_metadata",
                f"missing repo_map entry for task repo {repo_id}",
                repo_id=repo_id,
            )
        for row in rows:
            repo_id = str(row.get("repo", ""))
            if not repo_id or repo_id not in repo_map:
                continue
            expected_path = normalized_path(repo_map.get(repo_id))
            actual_path = normalized_path(row.get("repo_path"))
            if actual_path != expected_path:
                add_issue(
                    issues,
                    "fail",
                    "repo_metadata",
                    f"run repo_path does not match repo_map for task repo {repo_id}",
                    repo_id=repo_id,
                    run_id=row.get("run_id"),
                    expected_repo_path=expected_path,
                    actual_repo_path=actual_path,
                )
        if not repo_states:
            add_issue(issues, "fail", "repo_metadata", "manifest has no repo_states")
        for repo_id, state in repo_states.items():
            if not isinstance(state, dict):
                add_issue(issues, "fail", "repo_metadata", f"repo state is not an object: {repo_id}")
                continue
            missing = [
                field
                for field in ("path", "git_root", "branch", "commit", "dirty", "dirty_entries")
                if field not in state
            ]
            commit = str(state.get("commit", ""))
            if commit and not GIT_SHA_RE.match(commit):
                missing.append("valid_commit")
            if missing:
                add_issue(
                    issues,
                    "fail",
                    "repo_metadata",
                    f"repo metadata incomplete for {repo_id}",
                    repo_id=repo_id,
                    missing_fields=missing,
                )
    if require_repo_snapshots:
        if manifest.get("snapshot_repos") is not True:
            add_issue(issues, "fail", "repo_snapshots", "manifest does not prove snapshot_repos was enabled")
        repo_map = dict(manifest.get("repo_map", {}) or {})
        snapshots = dict(manifest.get("repo_snapshots", {}) or {})
        if not snapshots:
            add_issue(issues, "fail", "repo_snapshots", "manifest has no repo_snapshots")
        for repo_id in {key or "default" for key in repo_map}:
            snapshot = snapshots.get(repo_id)
            if not isinstance(snapshot, dict):
                add_issue(issues, "fail", "repo_snapshots", f"missing repo snapshot metadata for {repo_id}")
                continue
            missing = [
                field
                for field in ("source_path", "source_git_root", "source_commit", "snapshot_path", "snapshot_git_root")
                if not snapshot.get(field)
            ]
            source_commit = str(snapshot.get("source_commit", ""))
            if source_commit and not GIT_SHA_RE.match(source_commit):
                missing.append("valid_source_commit")
            if missing:
                add_issue(
                    issues,
                    "fail",
                    "repo_snapshots",
                    f"repo snapshot metadata incomplete for {repo_id}",
                    repo_id=repo_id,
                    missing_fields=missing,
                )

    if require_self_contained_artifacts:
        for row in rows:
            run_dir = Path(str(row.get("run_dir", ""))).expanduser()
            run_label = f"{row.get('agent', '')}/{row.get('profile', '')}/{row.get('task_id', '')}"
            if not run_dir.exists() or not run_dir.is_dir():
                add_issue(
                    issues,
                    "fail",
                    "self_contained_artifacts",
                    f"run artifact directory is missing for {run_label}",
                    run_id=row.get("run_id"),
                    run_dir=str(run_dir),
                )
                continue
            if not run_dir_is_under_root(run_dir=run_dir, root=root):
                add_issue(
                    issues,
                    "fail",
                    "self_contained_artifacts",
                    f"run artifact directory is outside benchmark output for {run_label}",
                    run_id=row.get("run_id"),
                    run_dir=str(run_dir.resolve()),
                    benchmark_out=str(root.resolve()),
                )
            missing_artifacts = sorted(name for name in REQUIRED_RUN_ARTIFACTS if not (run_dir / name).exists())
            if missing_artifacts:
                add_issue(
                    issues,
                    "fail",
                    "self_contained_artifacts",
                    f"run artifact directory is incomplete for {run_label}",
                    run_id=row.get("run_id"),
                    run_dir=str(run_dir.resolve()),
                    missing_artifacts=missing_artifacts,
                )

    present_agents = {str(row.get("agent", "")) for row in rows}
    present_profiles = {str(row.get("profile", "")) for row in rows}
    for agent in expected_agents:
        if agent not in present_agents:
            add_issue(issues, "fail", "agent_coverage", f"missing benchmark runs for agent {agent}")
    for profile in expected_profiles:
        if profile not in present_profiles:
            add_issue(issues, "fail", "profile_coverage", f"missing benchmark runs for profile {profile}")

    if require_balanced_matrix:
        present_cells = {
            (
                str(row.get("agent", "")),
                str(row.get("profile", "")),
                str(row.get("task_id", "")),
                str(row.get("repo", "")),
                str(row.get("repeat_index", "")),
            )
            for row in rows
        }
        task_repeat_keys = observed_task_repeat_keys(rows)
        if not task_repeat_keys:
            add_issue(issues, "fail", "balanced_matrix", "no task/repeat cells available to balance")
        for task_id, repo, repeat_index in task_repeat_keys:
            for agent in expected_agents:
                for profile in expected_profiles:
                    cell = (agent, profile, task_id, repo, repeat_index)
                    if cell not in present_cells:
                        add_issue(
                            issues,
                            "fail",
                            "balanced_matrix",
                            f"missing balanced matrix cell for {agent}/{profile}/{task_id}/repeat {repeat_index}",
                            agent=agent,
                            profile=profile,
                            task_id=task_id,
                            repo=repo,
                            repeat_index=repeat_index,
                        )

    matrix = run_matrix(rows)
    for agent in expected_agents:
        for profile in expected_profiles:
            items = matrix.get((agent, profile), [])
            if not items:
                add_issue(issues, "fail", "agent_profile_matrix", f"missing runs for {agent}/{profile}")
                continue
            check_items = rows_to_check(items, allow_controlled_failures=allow_controlled_failures)
            controlled_items = [item for item in items if is_controlled_failure(item)]
            if require_all_pass and not all(item.get("correctness_status") == "pass" for item in items):
                add_issue(issues, "fail", "correctness", f"not all runs pass for {agent}/{profile}")
            if require_observed_tools and not all(item.get("tool_evidence_source") == "observed" for item in check_items):
                add_issue(issues, "fail", "observed_tools", f"not all runs have observed tool evidence for {agent}/{profile}")
            if require_non_proxy_tokens and not all(has_non_proxy_token_totals(item) for item in check_items):
                add_issue(issues, "fail", "token_source", f"not all runs have exact or agent-reported tokens for {agent}/{profile}")
            if require_expected_proof_layer and not all(item.get("expected_proof_layer_seen") is True for item in check_items):
                add_issue(
                    issues,
                    "fail",
                    "expected_proof_layer",
                    f"not all runs prove the expected proof layer for {agent}/{profile}",
                )
            if require_no_weak_route_controls:
                weak_rows = [item for item in items if item.get("route_weak_controls")]
                if weak_rows:
                    add_issue(issues, "fail", "route_isolation", f"weak route controls present for {agent}/{profile}")
            if require_no_weak_route_controls or require_hard_isolation_for_blocked_tools:
                for item in items:
                    run_id = str(item.get("run_id", ""))
                    route_isolation_path = Path(str(item.get("run_dir", ""))).expanduser() / "route-isolation.json"
                    if not route_isolation_path.exists():
                        add_issue(
                            issues,
                            "fail",
                            "route_isolation",
                            f"route-isolation.json is missing for {agent}/{profile}",
                            run_id=run_id,
                            path=str(route_isolation_path),
                        )
                        continue
                    route_isolation = load_json(route_isolation_path)
                    expected_mode = str(route_isolation.get("mode", ""))
                    expected_hard = sorted(str(control) for control in route_isolation.get("hard_controls", []) or [])
                    expected_weak = sorted(str(control) for control in route_isolation.get("weak_controls", []) or [])
                    actual_mode = str(item.get("route_isolation_mode", ""))
                    actual_hard = sorted(str(control) for control in item.get("route_hard_controls", []) or [])
                    actual_weak = sorted(str(control) for control in item.get("route_weak_controls", []) or [])
                    if actual_mode != expected_mode:
                        add_issue(
                            issues,
                            "fail",
                            "route_isolation",
                            f"run route_isolation_mode does not match route-isolation.json for {agent}/{profile}",
                            run_id=run_id,
                            actual=actual_mode,
                            expected=expected_mode,
                        )
                    if actual_hard != expected_hard:
                        add_issue(
                            issues,
                            "fail",
                            "route_isolation",
                            f"run route_hard_controls do not match route-isolation.json for {agent}/{profile}",
                            run_id=run_id,
                            actual=actual_hard,
                            expected=expected_hard,
                        )
                    if actual_weak != expected_weak:
                        add_issue(
                            issues,
                            "fail",
                            "route_isolation",
                            f"run route_weak_controls do not match route-isolation.json for {agent}/{profile}",
                            run_id=run_id,
                            actual=actual_weak,
                            expected=expected_weak,
                        )
            if require_hard_isolation_for_blocked_tools:
                route_profile = load_route_profile(profile_path(profile))
                if route_profile.blocked_tools:
                    hard_rows = [
                        item
                        for item in items
                        if item.get("route_isolation_mode") == "config" and item.get("route_hard_controls")
                    ]
                    if len(hard_rows) != len(items):
                        add_issue(issues, "fail", "route_isolation", f"blocked-tool profile lacks hard isolation for {agent}/{profile}")
            policy_violation_items = rows_to_check(items, allow_controlled_failures=allow_controlled_failures)
            if any(item.get("policy_violations") for item in policy_violation_items):
                add_issue(issues, "fail", "policy_violations", f"policy violations present for {agent}/{profile}")
            if allow_controlled_failures:
                for item in controlled_items:
                    completion_reason = str(item.get("completion_reason", ""))
                    violations = item.get("policy_violations") if isinstance(item.get("policy_violations"), list) else []
                    if completion_reason not in CONTROLLED_FAILURE_REASONS and "tool_output_over_budget" not in violations:
                        add_issue(
                            issues,
                            "fail",
                            "controlled_failure",
                            f"run is not a recognized controlled failure for {agent}/{profile}",
                            run_id=item.get("run_id"),
                        )

            if require_live_lifecycle_telemetry:
                for item in items:
                    telemetry_path = Path(str(item.get("run_dir", ""))) / "telemetry.jsonl"
                    if not telemetry_path.exists():
                        add_issue(
                            issues,
                            "fail",
                            "live_lifecycle_telemetry",
                            f"telemetry.jsonl is missing for {item.get('agent', '')}/{item.get('task_id', '')}",
                            run_id=item.get("run_id"),
                            path=str(telemetry_path),
                        )
                        continue
                    telemetry_events = load_jsonl(telemetry_path)
                    event_names = {str(event.get("event", "")) for event in telemetry_events}
                    missing = [
                        event
                        for event in ("process_started", "prompt_sent", "run_completed")
                        if event not in event_names
                    ]
                    if not event_names.intersection({"process_exited", "process_timeout", "tmux_session_closed"}):
                        missing.append("process_exited_or_timeout_or_tmux_session_closed")
                    if missing:
                        add_issue(
                            issues,
                            "fail",
                            "live_lifecycle_telemetry",
                            f"lifecycle telemetry incomplete for {item.get('agent', '')}/{item.get('task_id', '')}",
                            run_id=item.get("run_id"),
                            missing_events=missing,
                            path=str(telemetry_path),
                        )

    if require_all_adapters:
        probes = adapter_rows(adapter_probe)
        probe_by_agent = {str(row.get("agent", "")): row for row in probes}
        for agent in expected_agents:
            row = probe_by_agent.get(agent)
            if not row:
                add_issue(issues, "fail", "adapter_probe", f"missing adapter probe for {agent}")
            elif row.get("status") != "pass":
                add_issue(
                    issues,
                    "fail",
                    "adapter_probe",
                    f"adapter probe failed for {agent}",
                    agent=agent,
                    reason=row.get("reason"),
                    completion_reason=row.get("completion_reason"),
                )
            elif row.get("ready_for_live_benchmark", True) is False:
                add_issue(
                    issues,
                    "fail",
                    "adapter_probe",
                    f"adapter is not ready for live benchmark use for {agent}",
                    agent=agent,
                    reason=row.get("reason"),
                    next_action=row.get("next_action"),
                )
            elif row.get("route_weak_controls") or row.get("probe_route_weak_controls"):
                add_issue(
                    issues,
                    "fail",
                    "adapter_probe",
                    f"adapter probe has weak route-isolation controls for {agent}",
                    agent=agent,
                    route_weak_controls=row.get("route_weak_controls") or row.get("probe_route_weak_controls"),
                )
            if row and require_non_proxy_tokens:
                token_ready = row.get("token_telemetry_ready")
                if not isinstance(token_ready, bool):
                    token_ready = row.get("non_proxy_token_telemetry_ready")
                if not isinstance(token_ready, bool):
                    token_ready = row.get("probe_non_proxy_token_telemetry_ready")
                if token_ready is True and not has_non_proxy_token_totals(row):
                    token_ready = False
                if token_ready is False:
                    add_issue(
                        issues,
                        "fail",
                        "token_source",
                        f"adapter token telemetry is not exact or agent-reported for {agent}",
                        agent=agent,
                        token_source=row.get("token_source") or row.get("probe_token_source"),
                        next_action=row.get("token_telemetry_next_action"),
                    )

    if require_paired_route_comparisons:
        baseline_profile = "A-search-only"
        treatment_profile = "D-full-router"
        if baseline_profile not in expected_profiles or treatment_profile not in expected_profiles:
            add_issue(
                issues,
                "fail",
                "route_comparisons",
                "paired route comparison requires A-search-only and D-full-router profiles",
            )
        comparison_path = root / "route-comparisons.json"
        comparisons = load_route_comparisons(root)
        if not comparison_path.exists():
            add_issue(issues, "fail", "route_comparisons", "route-comparisons.json is missing")
        comparison_by_key = {
            (
                str(row.get("agent", "")),
                str(row.get("task_id", "")),
                str(row.get("repo", "")),
                str(row.get("repeat_index", "")),
            ): row
            for row in comparisons
        }
        for key, profiles in run_pair_matrix(rows).items():
            agent, task_id, repo, repeat_index = key
            if agent not in expected_agents:
                continue
            if {baseline_profile, treatment_profile}.issubset(profiles):
                comparison = comparison_by_key.get(key)
                if not comparison:
                    add_issue(
                        issues,
                        "fail",
                        "route_comparisons",
                        f"missing paired route comparison for {agent}/{task_id}/repeat {repeat_index}",
                        agent=agent,
                        task_id=task_id,
                        repo=repo,
                        repeat_index=repeat_index,
                    )
                elif require_all_pass and (
                    comparison.get("baseline_correctness") != "pass"
                    or comparison.get("treatment_correctness") != "pass"
                ):
                    add_issue(
                        issues,
                        "fail",
                        "route_comparisons",
                        f"paired route comparison is not pass/pass for {agent}/{task_id}/repeat {repeat_index}",
                        agent=agent,
                        task_id=task_id,
                        repo=repo,
                        repeat_index=repeat_index,
                    )

    if required_savings_claim:
        claim_path = root / "route-claim-readiness.json"
        claim_readiness = load_route_claim_readiness(root)
        claim_rows = [
            row
            for row in claim_readiness.get("rows", [])
            if isinstance(row, dict)
        ] if isinstance(claim_readiness.get("rows", []), list) else []
        if not claim_path.exists():
            add_issue(issues, "fail", "route_claim_readiness", "route-claim-readiness.json is missing")
        elif not claim_rows:
            add_issue(issues, "fail", "route_claim_readiness", "route-claim-readiness.json has no paired claim rows")
        supported_rows = []
        for row in claim_rows:
            exact_supported = row.get("exact_token_savings_claim_supported") is True
            exact_uncached_supported = row.get("exact_uncached_token_savings_claim_supported") is True
            agent_reported_supported = row.get("agent_reported_token_savings_claim_supported") is True
            proxy_supported = row.get("model_visible_proxy_savings_claim_supported") is True
            supported = {
                "exact": exact_supported,
                "exact_uncached": exact_uncached_supported,
                "agent_reported": agent_reported_supported,
                "proxy": proxy_supported,
                "any": exact_supported or exact_uncached_supported or agent_reported_supported or proxy_supported,
            }.get(required_savings_claim, False)
            if supported:
                supported_rows.append(row)
            elif min_supported_savings_pairs <= 0:
                add_issue(
                    issues,
                    "fail",
                    "route_claim_readiness",
                    f"{required_savings_claim} savings claim is not supported for "
                    f"{row.get('agent', '')}/{row.get('task_id', '')}/repeat {row.get('repeat_index', '')}",
                    agent=row.get("agent"),
                    task_id=row.get("task_id"),
                    repo=row.get("repo"),
                    repeat_index=row.get("repeat_index"),
                    exact_claim_blockers=row.get("exact_claim_blockers", []),
                    exact_uncached_claim_blockers=row.get("exact_uncached_claim_blockers", []),
                    agent_reported_claim_blockers=row.get("agent_reported_claim_blockers", []),
                    proxy_claim_blockers=row.get("proxy_claim_blockers", []),
                )
        if min_supported_savings_pairs > 0 and len(supported_rows) < min_supported_savings_pairs:
            add_issue(
                issues,
                "fail",
                "route_claim_readiness",
                f"{required_savings_claim} savings claim has too few supported pairs: "
                f"{len(supported_rows)} < {min_supported_savings_pairs}",
                supported_pairs=len(supported_rows),
                required_pairs=min_supported_savings_pairs,
            )

    if require_matrix_completion_report:
        matrix_path = root / "matrix-completion-summary.json"
        matrix_completion = load_matrix_completion(root)
        if not matrix_path.exists():
            add_issue(issues, "fail", "matrix_completion_report", "matrix-completion-summary.json is missing")
        elif not matrix_completion:
            add_issue(issues, "fail", "matrix_completion_report", "matrix-completion-summary.json is empty or invalid")
        else:
            if not matrix_completion.get("status"):
                add_issue(issues, "fail", "matrix_completion_report", "matrix completion status is missing")
            try:
                missing_cell_count = int(matrix_completion.get("missing_cell_count", 0) or 0)
            except (TypeError, ValueError):
                missing_cell_count = -1
            if missing_cell_count < 0:
                add_issue(issues, "fail", "matrix_completion_report", "matrix completion missing_cell_count is invalid")
            expected_missing_agents = sorted(agent for agent in expected_agents if agent not in present_agents)
            if expected_missing_agents and missing_cell_count == 0:
                add_issue(
                    issues,
                    "fail",
                    "matrix_completion_report",
                    "matrix completion report says complete while expected agents are missing",
                    missing_agents=expected_missing_agents,
                )
        if missing_plan:
            plan_path = Path(missing_plan)
            plan = load_json(plan_path) if plan_path.exists() else {}
            if not plan_path.exists():
                add_issue(
                    issues,
                    "fail",
                    "matrix_completion_report",
                    "missing-run plan for matrix completion comparison is missing",
                    path=str(plan_path),
                )
            elif matrix_completion:
                plan_execution = plan.get("execution_plan") if isinstance(plan.get("execution_plan"), dict) else {}
                comparisons = {
                    "status": (matrix_completion.get("status"), plan_execution.get("status")),
                    "missing_cell_count": (matrix_completion.get("missing_cell_count"), plan.get("missing_cell_count")),
                    "runnable_missing_cell_count": (
                        matrix_completion.get("runnable_missing_cell_count"),
                        plan.get("runnable_missing_cell_count"),
                    ),
                    "blocked_agents": (
                        sorted(str(agent) for agent in matrix_completion.get("blocked_agents", []) or []),
                        sorted(str(agent) for agent in plan.get("blocked_agents", []) or []),
                    ),
                    "missing_by_agent": (
                        matrix_completion.get("missing_by_agent", {}),
                        plan_execution.get("missing_by_agent", {}),
                    ),
                }
                for field, (actual, expected) in comparisons.items():
                    if actual != expected:
                        add_issue(
                            issues,
                            "fail",
                            "matrix_completion_report",
                            f"matrix completion field does not match missing-run plan: {field}",
                            field=field,
                            actual=actual,
                            expected=expected,
                        )

    if require_terminal_control_summary:
        terminal_path = root / "terminal-control-summary.json"
        terminal_summary = load_terminal_control_summary(root)
        if not terminal_path.exists():
            add_issue(issues, "fail", "terminal_control_summary", "terminal-control-summary.json is missing")
        elif not terminal_summary:
            add_issue(issues, "fail", "terminal_control_summary", "terminal-control-summary.json is empty or invalid")
        else:
            summary_rows = terminal_summary.get("rows", [])
            if not isinstance(summary_rows, list):
                summary_rows = []
            if int(terminal_summary.get("runs", -1) or -1) != len(rows):
                add_issue(
                    issues,
                    "fail",
                    "terminal_control_summary",
                    "terminal-control-summary run count does not match runs.jsonl",
                    actual=terminal_summary.get("runs"),
                    expected=len(rows),
                )
            if len(summary_rows) != len(rows):
                add_issue(
                    issues,
                    "fail",
                    "terminal_control_summary",
                    "terminal-control-summary rows do not match runs.jsonl",
                    actual=len(summary_rows),
                    expected=len(rows),
                )
            for field, label in (
                ("prompt_sent_count", "prompt_sent"),
                ("capture_changed_count", "capture_changed"),
                ("closed_or_exited_count", "closed_or_exited"),
            ):
                if int(terminal_summary.get(field, 0) or 0) != len(rows):
                    add_issue(
                        issues,
                        "fail",
                        "terminal_control_summary",
                        f"terminal-control-summary does not prove {label} for every run",
                        actual=terminal_summary.get(field),
                        expected=len(rows),
                    )
            row_by_id = {
                str(item.get("run_id", "")): item
                for item in summary_rows
                if isinstance(item, dict)
            }
            for row in rows:
                run_id = str(row.get("run_id", ""))
                terminal_row = row_by_id.get(run_id)
                if not terminal_row:
                    add_issue(
                        issues,
                        "fail",
                        "terminal_control_summary",
                        f"terminal-control-summary is missing run {run_id}",
                        run_id=run_id,
                    )
                    continue
                if terminal_row.get("terminal_mode") in {None, "", "unknown"}:
                    add_issue(
                        issues,
                        "fail",
                        "terminal_control_summary",
                        f"terminal-control-summary has unknown terminal mode for run {run_id}",
                        run_id=run_id,
                    )
                run_dir = Path(str(row.get("run_dir", ""))).expanduser()
                telemetry_path = run_dir / "telemetry.jsonl"
                launch_plan_path = run_dir / "launch-plan.json"
                if not telemetry_path.exists():
                    add_issue(
                        issues,
                        "fail",
                        "terminal_control_summary",
                        f"terminal-control-summary cannot be verified because telemetry.jsonl is missing for run {run_id}",
                        run_id=run_id,
                        path=str(telemetry_path),
                    )
                    continue
                telemetry_events = load_jsonl(telemetry_path)
                event_names = [str(event.get("event", "")) for event in telemetry_events]
                event_set = set(event_names)
                launch_plan = load_json(launch_plan_path) if launch_plan_path.exists() else {}
                expected_terminal_mode = str(launch_plan.get("terminal_mode") or row.get("terminal_mode") or "unknown")
                expected_flags = {
                    "prompt_sent": "prompt_sent" in event_set,
                    "capture_changed": bool(event_set.intersection({"terminal_capture_changed", "process_output_chunk"})),
                    "sentinel_observed": "sentinel_observed" in event_set or row.get("completion_reason") == "sentinel",
                    "closed_or_exited": bool(event_set.intersection({"process_exited", "process_timeout", "tmux_session_closed"})),
                }
                for field, expected in expected_flags.items():
                    actual = bool(terminal_row.get(field))
                    if actual != expected:
                        add_issue(
                            issues,
                            "fail",
                            "terminal_control_summary",
                            f"terminal-control-summary {field} flag is stale for run {run_id}",
                            run_id=run_id,
                            actual=actual,
                            expected=expected,
                        )
                if terminal_row.get("terminal_mode") != expected_terminal_mode:
                    add_issue(
                        issues,
                        "fail",
                        "terminal_control_summary",
                        f"terminal-control-summary terminal mode is stale for run {run_id}",
                        run_id=run_id,
                        actual=terminal_row.get("terminal_mode"),
                        expected=expected_terminal_mode,
                    )
                if int(terminal_row.get("event_count", -1) or -1) != len(event_names):
                    add_issue(
                        issues,
                        "fail",
                        "terminal_control_summary",
                        f"terminal-control-summary event_count is stale for run {run_id}",
                        run_id=run_id,
                        actual=terminal_row.get("event_count"),
                        expected=len(event_names),
                    )

    if require_route_policy_summary:
        route_policy_path = root / "route-policy-summary.json"
        route_policy = load_route_policy_summary(root)
        if not route_policy_path.exists():
            add_issue(issues, "fail", "route_policy_summary", "route-policy-summary.json is missing")
        elif not route_policy:
            add_issue(issues, "fail", "route_policy_summary", "route-policy-summary.json is empty or invalid")
        else:
            summary_rows = route_policy.get("rows", [])
            if not isinstance(summary_rows, list):
                summary_rows = []
            if int(route_policy.get("runs", -1) or -1) != len(rows):
                add_issue(
                    issues,
                    "fail",
                    "route_policy_summary",
                    "route-policy-summary run count does not match runs.jsonl",
                    actual=route_policy.get("runs"),
                    expected=len(rows),
                )
            if len(summary_rows) != len(rows):
                add_issue(
                    issues,
                    "fail",
                    "route_policy_summary",
                    "route-policy-summary rows do not match runs.jsonl",
                    actual=len(summary_rows),
                    expected=len(rows),
                )
            if int(route_policy.get("blocked_tool_violation_count", 0) or 0) > 0:
                add_issue(
                    issues,
                    "fail",
                    "route_policy_summary",
                    "route-policy-summary contains blocked-tool violations",
                    count=route_policy.get("blocked_tool_violation_count"),
                )
            if int(route_policy.get("checkable_required_first_tool_violation_count", 0) or 0) > 0:
                add_issue(
                    issues,
                    "fail",
                    "route_policy_summary",
                    "route-policy-summary contains required-first-tool violations",
                    count=route_policy.get("checkable_required_first_tool_violation_count"),
                )
            row_by_id = {
                str(item.get("run_id", "")): item
                for item in summary_rows
                if isinstance(item, dict)
            }
            expected_blocked_count = 0
            expected_required_first_count = 0
            expected_checkable_required_first_count = 0
            expected_output_budget_count = 0
            for row in rows:
                run_id = str(row.get("run_id", ""))
                summary_row = row_by_id.get(run_id)
                if not summary_row:
                    add_issue(
                        issues,
                        "fail",
                        "route_policy_summary",
                        f"route-policy-summary is missing run {run_id}",
                        run_id=run_id,
                    )
                    continue
                violations = [str(item) for item in row.get("policy_violations", []) or []]
                expected_blocked = sorted(item for item in violations if item.startswith("blocked_tool_used:"))
                expected_required_first = "required_first_tool_not_used" in violations
                expected_output_budget = "tool_output_over_budget" in violations
                expected_controlled = is_controlled_failure(row)
                expected_blocked_count += len(expected_blocked)
                expected_required_first_count += int(expected_required_first)
                expected_checkable_required_first_count += int(expected_required_first and not expected_controlled)
                expected_output_budget_count += int(expected_output_budget)
                actual_blocked = sorted(str(item) for item in summary_row.get("blocked_tool_violations", []) or [])
                actual_required_first = bool(summary_row.get("required_first_tool_violation"))
                actual_output_budget = bool(summary_row.get("output_budget_violation"))
                if actual_blocked != expected_blocked:
                    add_issue(
                        issues,
                        "fail",
                        "route_policy_summary",
                        f"route-policy-summary blocked-tool violations are stale for run {run_id}",
                        run_id=run_id,
                        actual=actual_blocked,
                        expected=expected_blocked,
                    )
                if actual_required_first != expected_required_first:
                    add_issue(
                        issues,
                        "fail",
                        "route_policy_summary",
                        f"route-policy-summary required-first-tool flag is stale for run {run_id}",
                        run_id=run_id,
                        actual=actual_required_first,
                        expected=expected_required_first,
                    )
                if actual_output_budget != expected_output_budget:
                    add_issue(
                        issues,
                        "fail",
                        "route_policy_summary",
                        f"route-policy-summary output-budget flag is stale for run {run_id}",
                        run_id=run_id,
                        actual=actual_output_budget,
                        expected=expected_output_budget,
                    )
            count_expectations = {
                "blocked_tool_violation_count": expected_blocked_count,
                "required_first_tool_violation_count": expected_required_first_count,
                "checkable_required_first_tool_violation_count": expected_checkable_required_first_count,
                "output_budget_violation_count": expected_output_budget_count,
            }
            for field, expected in count_expectations.items():
                actual = int(route_policy.get(field, 0) or 0)
                if actual != expected:
                    add_issue(
                        issues,
                        "fail",
                        "route_policy_summary",
                        f"route-policy-summary {field} does not match runs.jsonl",
                        field=field,
                        actual=actual,
                        expected=expected,
                    )

    fail_count = sum(1 for issue in issues if issue["severity"] == "fail")
    warn_count = sum(1 for issue in issues if issue["severity"] == "warn")
    requirement_summary = [
        requirement_status(
            issues=issues,
            key="live_execution",
            label="Live benchmark artifacts exist and are from live mode",
            checks={"manifest_exists", "runs_exist", "live_mode", "task_count"},
            requested=True,
            evidence={
                "run_count": len(rows),
                "manifest_live": manifest.get("live"),
                "task_count": manifest.get("task_count", 0),
                "min_tasks": min_tasks,
            },
        ),
        requirement_status(
            issues=issues,
            key="adapter_readiness",
            label="Every expected subject-agent adapter is ready",
            checks={"adapter_probe"},
            requested=require_all_adapters,
            evidence={
                "expected_agents": expected_agents,
                "adapter_probe_inputs": [str(Path(path).resolve()) for path in adapter_probe] if adapter_probe else [],
            },
        ),
        requirement_status(
            issues=issues,
            key="balanced_multi_agent_matrix",
            label="Expected agents and profiles have balanced task/repeat cells",
            checks={"agent_coverage", "profile_coverage", "balanced_matrix", "agent_profile_matrix"},
            requested=True,
            evidence={
                "expected_agents": expected_agents,
                "expected_profiles": expected_profiles,
                "require_balanced_matrix": require_balanced_matrix,
            },
        ),
        requirement_status(
            issues=issues,
            key="correctness_policy_and_proof",
            label="Runs pass correctness, policy, observed-tool, and proof-layer checks",
            checks={"correctness", "observed_tools", "expected_proof_layer", "policy_violations", "controlled_failure"},
            requested=require_all_pass or require_observed_tools or require_expected_proof_layer,
            evidence={
                "require_all_pass": require_all_pass,
                "require_observed_tools": require_observed_tools,
                "require_expected_proof_layer": require_expected_proof_layer,
                "allow_controlled_failures": allow_controlled_failures,
            },
        ),
        requirement_status(
            issues=issues,
            key="token_measurement",
            label="Runs use exact or agent-reported token telemetry",
            checks={"token_source"},
            requested=require_non_proxy_tokens,
            evidence={"require_non_proxy_tokens": require_non_proxy_tokens},
        ),
        requirement_status(
            issues=issues,
            key="route_isolation",
            label="Route profiles have required isolation controls",
            checks={"route_isolation"},
            requested=require_no_weak_route_controls or require_hard_isolation_for_blocked_tools,
            evidence={
                "require_no_weak_route_controls": require_no_weak_route_controls,
                "require_hard_isolation_for_blocked_tools": require_hard_isolation_for_blocked_tools,
            },
        ),
        requirement_status(
            issues=issues,
            key="run_validity_controls",
            label="Fresh sessions, randomized order, clean repos, snapshots, repo metadata, real task manifest, and artifact packaging are proven",
            checks={
                "clean_repo",
                "fresh_sessions",
                "randomized_order",
                "repo_snapshots",
                "repo_metadata",
                "real_task_manifest",
                "self_contained_artifacts",
                "serena_process_state",
            },
            requested=(
                require_clean_repos
                or require_fresh_sessions
                or require_randomized_order
                or require_repo_snapshots
                or require_repo_metadata
                or require_real_task_manifest
                or require_self_contained_artifacts
                or require_clean_serena_process_state
            ),
            evidence={
                "require_clean_repos": require_clean_repos,
                "require_fresh_sessions": require_fresh_sessions,
                "require_randomized_order": require_randomized_order,
                "require_repo_snapshots": require_repo_snapshots,
                "require_repo_metadata": require_repo_metadata,
                "require_real_task_manifest": require_real_task_manifest,
                "require_self_contained_artifacts": require_self_contained_artifacts,
                "require_clean_serena_process_state": require_clean_serena_process_state,
            },
        ),
        requirement_status(
            issues=issues,
            key="live_lifecycle_telemetry",
            label="Per-run telemetry proves live terminal/session monitoring",
            checks={"live_lifecycle_telemetry"},
            requested=require_live_lifecycle_telemetry,
            evidence={"require_live_lifecycle_telemetry": require_live_lifecycle_telemetry},
        ),
        requirement_status(
            issues=issues,
            key="paired_route_comparison",
            label="A-search-only and D-full-router are paired for each comparable cell",
            checks={"route_comparisons"},
            requested=require_paired_route_comparisons,
            evidence={"require_paired_route_comparisons": require_paired_route_comparisons},
        ),
        requirement_status(
            issues=issues,
            key="savings_claim",
            label="Requested route savings claim is supported by paired evidence",
            checks={"route_claim_readiness"},
            requested=bool(required_savings_claim),
            evidence={
                "required_savings_claim": required_savings_claim,
                "min_supported_savings_pairs": min_supported_savings_pairs,
            },
        ),
        requirement_status(
            issues=issues,
            key="matrix_completion_report",
            label="Report carries matrix completion status matching the missing-run plan",
            checks={"matrix_completion_report"},
            requested=require_matrix_completion_report,
            evidence={
                "require_matrix_completion_report": require_matrix_completion_report,
                "missing_plan": str(Path(missing_plan).resolve()) if missing_plan else "",
            },
        ),
        requirement_status(
            issues=issues,
            key="terminal_control_summary",
            label="Report summarizes terminal control-plane lifecycle evidence",
            checks={"terminal_control_summary"},
            requested=require_terminal_control_summary,
            evidence={"require_terminal_control_summary": require_terminal_control_summary},
        ),
        requirement_status(
            issues=issues,
            key="route_policy_summary",
            label="Report summarizes route-policy enforcement and violations",
            checks={"route_policy_summary"},
            requested=require_route_policy_summary,
            evidence={"require_route_policy_summary": require_route_policy_summary},
        ),
    ]
    return {
        "created_at": utc_now(),
        "benchmark_out": str(root.resolve()),
        "adapter_probe": [str(Path(path).resolve()) for path in adapter_probe] if adapter_probe else [],
        "status": "pass" if fail_count == 0 else "fail",
        "requirement_status": "pass" if fail_count == 0 else "fail",
        "requirements": requirement_summary,
        "fail": fail_count,
        "warn": warn_count,
        "run_count": len(rows),
        "expected_agents": expected_agents,
        "expected_profiles": expected_profiles,
        "blockers": [issue["message"] for issue in issues if issue["severity"] == "fail"],
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit whether RARB evidence is strong enough for a real benchmark claim.")
    parser.add_argument("--benchmark-out", required=True)
    parser.add_argument("--adapter-probe", action="append", help="Adapter probe summary path or directory. May be repeated.")
    parser.add_argument("--agents", required=True)
    parser.add_argument("--profiles", default="A-search-only,D-full-router")
    parser.add_argument(
        "--preset",
        choices=["codex-exact-paired"],
        default="",
        help="Apply a strict claim gate preset. codex-exact-paired requires live paired Codex A/D exact-token evidence.",
    )
    parser.add_argument("--min-tasks", type=int, default=1)
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--require-clean-repos", action="store_true")
    parser.add_argument("--require-all-adapters", action="store_true")
    parser.add_argument("--require-all-pass", action="store_true")
    parser.add_argument("--require-observed-tools", action="store_true")
    parser.add_argument("--require-non-proxy-tokens", action="store_true")
    parser.add_argument("--require-expected-proof-layer", action="store_true")
    parser.add_argument("--require-no-weak-route-controls", action="store_true")
    parser.add_argument("--require-hard-isolation-for-blocked-tools", action="store_true")
    parser.add_argument("--require-paired-route-comparisons", action="store_true")
    parser.add_argument("--require-live-lifecycle-telemetry", action="store_true")
    parser.add_argument("--require-fresh-sessions", action="store_true")
    parser.add_argument("--require-randomized-order", action="store_true")
    parser.add_argument("--require-repo-snapshots", action="store_true")
    parser.add_argument("--require-repo-metadata", action="store_true")
    parser.add_argument("--require-real-task-manifest", action="store_true")
    parser.add_argument("--require-balanced-matrix", action="store_true")
    parser.add_argument("--require-self-contained-artifacts", action="store_true")
    parser.add_argument("--require-clean-serena-process-state", action="store_true")
    parser.add_argument("--require-matrix-completion-report", action="store_true")
    parser.add_argument("--require-terminal-control-summary", action="store_true")
    parser.add_argument("--require-route-policy-summary", action="store_true")
    parser.add_argument("--missing-plan", help="Optional missing-run plan JSON to compare with matrix-completion-summary.json.")
    parser.add_argument(
        "--allow-controlled-failures",
        action="store_true",
        help=(
            "Treat controlled benchmark stops such as output_budget_exceeded as valid "
            "execution outcomes for observed-tool/token/policy readiness checks. "
            "Does not make them pass correctness or savings-claim gates."
        ),
    )
    parser.add_argument(
        "--require-supported-savings-claim",
        choices=["exact", "exact_uncached", "agent_reported", "proxy", "any"],
        default="",
        help=(
            "Require every paired route comparison to support a savings claim for the selected metric. "
            "exact_uncached means exact total minus cached input when available."
        ),
    )
    parser.add_argument(
        "--min-supported-savings-pairs",
        type=int,
        default=0,
        help=(
            "When used with --require-supported-savings-claim, require at least this many "
            "supported paired comparisons instead of requiring every paired row to support the claim."
        ),
    )
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    if args.preset == "codex-exact-paired":
        args.agents = "codex"
        args.profiles = "A-search-only,D-full-router"
        args.require_live = True
        args.require_all_pass = True
        args.require_observed_tools = True
        args.require_non_proxy_tokens = True
        args.require_expected_proof_layer = True
        args.require_no_weak_route_controls = True
        args.require_hard_isolation_for_blocked_tools = True
        args.require_paired_route_comparisons = True
        args.require_live_lifecycle_telemetry = True
        args.require_fresh_sessions = True
        args.require_randomized_order = True
        args.require_repo_metadata = True
        args.require_real_task_manifest = True
        args.require_clean_serena_process_state = True
        args.require_terminal_control_summary = True
        args.require_route_policy_summary = True
        args.require_supported_savings_claim = args.require_supported_savings_claim or "exact_uncached"
        args.min_supported_savings_pairs = max(args.min_supported_savings_pairs, 1)
    result = audit(
        benchmark_out=args.benchmark_out,
        adapter_probe=args.adapter_probe,
        expected_agents=split_csv(args.agents),
        expected_profiles=split_csv(args.profiles),
        min_tasks=args.min_tasks,
        require_live=args.require_live,
        require_clean_repos=args.require_clean_repos,
        require_all_adapters=args.require_all_adapters,
        require_all_pass=args.require_all_pass,
        require_observed_tools=args.require_observed_tools,
        require_non_proxy_tokens=args.require_non_proxy_tokens,
        require_expected_proof_layer=args.require_expected_proof_layer,
        require_no_weak_route_controls=args.require_no_weak_route_controls,
        require_hard_isolation_for_blocked_tools=args.require_hard_isolation_for_blocked_tools,
        require_paired_route_comparisons=args.require_paired_route_comparisons,
        required_savings_claim=args.require_supported_savings_claim,
        require_live_lifecycle_telemetry=args.require_live_lifecycle_telemetry,
        require_fresh_sessions=args.require_fresh_sessions,
        require_randomized_order=args.require_randomized_order,
        require_repo_snapshots=args.require_repo_snapshots,
        require_repo_metadata=args.require_repo_metadata,
        require_real_task_manifest=args.require_real_task_manifest,
        require_balanced_matrix=args.require_balanced_matrix,
        require_self_contained_artifacts=args.require_self_contained_artifacts,
        require_clean_serena_process_state=args.require_clean_serena_process_state,
        require_matrix_completion_report=args.require_matrix_completion_report,
        require_terminal_control_summary=args.require_terminal_control_summary,
        require_route_policy_summary=args.require_route_policy_summary,
        missing_plan=args.missing_plan,
        allow_controlled_failures=args.allow_controlled_failures,
        min_supported_savings_pairs=args.min_supported_savings_pairs,
    )
    if args.out:
        Path(args.out).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
