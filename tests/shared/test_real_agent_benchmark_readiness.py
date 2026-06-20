from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmarks.audit_real_agent_benchmark_readiness import audit, main
from scripts.lib.agent_session import append_jsonl, to_json_file


def write_manifest(
    root: Path,
    *,
    live: bool = True,
    dirty: bool = False,
    fresh_sessions: bool = True,
    randomized_order: bool = True,
    snapshot_repos: bool = False,
    include_repo_metadata: bool = True,
    task_manifest: str | None = None,
    require_clean_serena_process_state: bool = False,
) -> None:
    repo_state = {
        "path": str(root),
        "git_root": str(root),
        "branch": "main",
        "commit": "0123456789abcdef0123456789abcdef01234567",
        "dirty": dirty,
        "dirty_entries": 1 if dirty else 0,
    }
    if not include_repo_metadata:
        repo_state.pop("commit")
    to_json_file(
        root / "run-manifest.json",
        {
            "live": live,
            "task_count": 1,
            "task_manifest": task_manifest or str(root / "android-realworld.local.tsv"),
            "fresh_session_per_run": fresh_sessions,
            "order_randomized": randomized_order,
            "snapshot_repos": snapshot_repos,
            "repo_map": {"sample": str(root)},
            "repo_states": {"sample": repo_state},
            "repo_snapshots": {
                "sample": {
                    "source_path": str(root / "source"),
                    "source_git_root": str(root / "source"),
                    "source_commit": "0123456789abcdef0123456789abcdef01234567",
                    "snapshot_path": str(root),
                    "snapshot_git_root": str(root),
                }
            }
            if snapshot_repos
            else {},
            "require_clean_serena_process_state": require_clean_serena_process_state,
        },
    )


def write_run(
    root: Path,
    *,
    agent: str = "codex",
    profile: str = "A-search-only",
    correctness_status: str = "pass",
    token_source: str = "exact",
    tool_evidence_source: str = "observed",
    route_isolation_mode: str = "config",
    route_hard_controls: list[str] | None = None,
    route_weak_controls: list[str] | None = None,
    policy_violations: list[str] | None = None,
    expected_proof_layer_seen: bool = True,
    completion_reason: str = "sentinel",
    task_id: str = "task",
    repo: str = "sample",
    repeat_index: int = 0,
    run_dir: Path | None = None,
    repo_path: str | None = None,
    serena_readiness_warnings: list[str] | None = None,
) -> None:
    row = {
        "run_id": f"{agent}-{profile}",
        "agent": agent,
        "profile": profile,
        "task_id": task_id,
        "repo": repo,
        "repeat_index": repeat_index,
        "correctness_status": correctness_status,
        "token_source": token_source,
        "tool_evidence_source": tool_evidence_source,
        "route_isolation_mode": route_isolation_mode,
        "route_hard_controls": route_hard_controls or ["test_hard_control"],
        "route_weak_controls": route_weak_controls or [],
        "policy_violations": policy_violations or [],
        "expected_proof_layer_seen": expected_proof_layer_seen,
        "completion_reason": completion_reason,
        "repo_path": repo_path or str(root),
        "run_dir": str(run_dir or root),
        "serena_readiness_warnings": serena_readiness_warnings or [],
    }
    if token_source == "exact":
        row["exact_total_tokens"] = 100
    elif token_source == "agent_reported":
        row["agent_reported_total_tokens"] = 100
    effective_run_dir = Path(row["run_dir"])
    effective_run_dir.mkdir(parents=True, exist_ok=True)
    to_json_file(
        effective_run_dir / "route-isolation.json",
        {
            "mode": row["route_isolation_mode"],
            "hard_controls": row["route_hard_controls"],
            "weak_controls": row["route_weak_controls"],
        },
    )
    append_jsonl(
        root / "runs.jsonl",
        row,
    )


def write_probe(root: Path, rows: list[dict[str, object]]) -> Path:
    probe = root / "adapter-probe"
    probe.mkdir()
    to_json_file(probe / "adapter-probe-summary.json", {"rows": rows})
    return probe


def write_doctor(root: Path, rows: list[dict[str, object]]) -> Path:
    doctor = root / "adapter-doctor"
    doctor.mkdir()
    to_json_file(doctor / "adapter-doctor-summary.json", {"rows": rows})
    return doctor


def write_route_comparisons(root: Path, rows: list[dict[str, object]]) -> None:
    to_json_file(root / "route-comparisons.json", rows)


def write_route_claim_readiness(root: Path, rows: list[dict[str, object]]) -> None:
    to_json_file(
        root / "route-claim-readiness.json",
        {
            "paired_comparisons": len(rows),
            "exact_token_savings_claims_supported": sum(
                1 for row in rows if row.get("exact_token_savings_claim_supported")
            ),
            "exact_uncached_token_savings_claims_supported": sum(
                1 for row in rows if row.get("exact_uncached_token_savings_claim_supported")
            ),
            "agent_reported_token_savings_claims_supported": sum(
                1 for row in rows if row.get("agent_reported_token_savings_claim_supported")
            ),
            "model_visible_proxy_savings_claims_supported": sum(
                1 for row in rows if row.get("model_visible_proxy_savings_claim_supported")
            ),
            "rows": rows,
        },
    )


def write_matrix_completion(root: Path, *, status: str = "blocked", missing_cell_count: int = 10) -> None:
    to_json_file(
        root / "matrix-completion-summary.json",
        {
            "status": status,
            "can_resume_now": False,
            "completion_boundary": "missing cells remain",
            "missing_cell_count": missing_cell_count,
            "runnable_missing_cell_count": 0,
            "blocked_agents": ["claude-code"] if missing_cell_count else [],
            "unknown_agents": [],
            "missing_by_agent": {"claude-code": missing_cell_count} if missing_cell_count else {},
            "blocked_actions": [
                {
                    "agent": "claude-code",
                    "missing_cells": missing_cell_count,
                    "reason": "model_access_denied",
                }
            ]
            if missing_cell_count
            else [],
        },
    )


def write_missing_plan(root: Path, *, status: str = "blocked", missing_cell_count: int = 10) -> Path:
    path = root / "missing-plan.json"
    to_json_file(
        path,
        {
            "missing_cell_count": missing_cell_count,
            "runnable_missing_cell_count": 0,
            "blocked_agents": ["claude-code"] if missing_cell_count else [],
            "unknown_agents": [],
            "missing_repo_map_entries": [],
            "execution_plan": {
                "status": status,
                "can_resume_now": False,
                "completion_boundary": "missing cells remain",
                "missing_by_agent": {"claude-code": missing_cell_count} if missing_cell_count else {},
                "blocked_actions": [
                    {
                        "agent": "claude-code",
                        "missing_cells": missing_cell_count,
                        "reason": "model_access_denied",
                    }
                ]
                if missing_cell_count
                else [],
            },
        },
    )
    return path


def write_terminal_control_summary(
    root: Path,
    rows: list[dict[str, object]],
    *,
    complete: bool = True,
    capture_changed: bool | None = None,
    write_artifacts: bool = True,
) -> None:
    capture_changed = complete if capture_changed is None else capture_changed
    summary_rows = []
    for row in rows:
        if write_artifacts:
            run_dir = Path(str(row.get("run_dir") or root))
            run_dir.mkdir(parents=True, exist_ok=True)
            to_json_file(run_dir / "launch-plan.json", {"terminal_mode": "tmux"})
            events = ["process_started"]
            if complete:
                events.extend(["prompt_sent", "sentinel_observed", "tmux_session_closed"])
            if capture_changed:
                events.insert(2 if complete else 1, "terminal_capture_changed")
            for event in events:
                append_jsonl(run_dir / "telemetry.jsonl", {"event": event})
        summary_rows.append(
            {
                "run_id": row["run_id"],
                "agent": row["agent"],
                "profile": row["profile"],
                "task_id": row["task_id"],
                "terminal_mode": "tmux",
                "prompt_sent": complete,
                "sentinel_observed": complete,
                "closed_or_exited": complete,
                "capture_changed": capture_changed,
                "event_count": (4 if complete else 1) + int(capture_changed),
                "events": [
                    event
                    for event in (
                        ["process_started", "prompt_sent", "terminal_capture_changed", "sentinel_observed", "tmux_session_closed"]
                        if complete and capture_changed
                        else ["process_started", "prompt_sent", "sentinel_observed", "tmux_session_closed"]
                        if complete
                        else ["process_started", "terminal_capture_changed"]
                        if capture_changed
                        else ["process_started"]
                    )
                ],
            }
        )
    to_json_file(
        root / "terminal-control-summary.json",
        {
            "runs": len(rows),
            "terminal_modes": {"tmux": len(rows)},
            "prompt_sent_count": len(rows) if complete else 0,
            "sentinel_observed_count": len(rows) if complete else 0,
            "closed_or_exited_count": len(rows) if complete else 0,
            "capture_changed_count": len(rows) if capture_changed else 0,
            "rows": summary_rows,
        },
    )


def write_route_policy_summary(root: Path, rows: list[dict[str, object]], *, blocked_violations: int = 0) -> None:
    to_json_file(
        root / "route-policy-summary.json",
        {
            "runs": len(rows),
            "blocked_tool_violation_count": blocked_violations,
            "required_first_tool_violation_count": 0,
            "checkable_required_first_tool_violation_count": 0,
            "output_budget_violation_count": 0,
            "rows": [
                {
                    "run_id": row["run_id"],
                    "agent": row["agent"],
                    "profile": row["profile"],
                    "task_id": row["task_id"],
                    "allowed_tools": ["rg"],
                    "blocked_tools": ["Serena"],
                    "observed_task_tools": ["rg"],
                    "blocked_tool_violations": ["blocked_tool_used:Serena"] if blocked_violations else [],
                    "required_first_tool_violation": False,
                    "output_budget_violation": False,
                }
                for row in rows
            ],
        },
    )


def write_lifecycle_telemetry(run_dir: Path, *, complete: bool = True) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "process_started"})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "prompt_sent"})
    if complete:
        append_jsonl(run_dir / "telemetry.jsonl", {"event": "process_exited"})
        append_jsonl(run_dir / "telemetry.jsonl", {"event": "run_completed"})


def write_fresh_session_telemetry(run_dir: Path, *, session: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "process_started"})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "tmux_session_started", "session": session})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "prompt_sent"})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "tmux_session_closed", "session": session})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "run_completed"})


def write_required_run_artifacts(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "task-packet.md",
        "transcript.txt",
        "metrics.normalized.json",
        "judge.json",
        "route-isolation.json",
    ):
        (run_dir / name).write_text("{}\n", encoding="utf-8")
    if not (run_dir / "telemetry.jsonl").exists():
        (run_dir / "telemetry.jsonl").write_text("{}\n", encoding="utf-8")


class RealAgentBenchmarkReadinessTests(unittest.TestCase):
    def test_audit_passes_when_required_evidence_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
            )

            self.assertEqual(result["status"], "pass")
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(result["requirement_status"], "pass")
            self.assertEqual(requirement_by_key["live_execution"]["status"], "pass")
            self.assertEqual(requirement_by_key["adapter_readiness"]["status"], "pass")
            self.assertEqual(requirement_by_key["token_measurement"]["status"], "pass")
            self.assertEqual(requirement_by_key["paired_route_comparison"]["status"], "not_requested")
            self.assertEqual(result["blockers"], [])

    def test_audit_can_treat_budget_stops_as_controlled_benchmark_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(
                root,
                agent="codex",
                profile="D-full-router",
                correctness_status="fail",
                token_source="proxy",
                tool_evidence_source="missing",
                policy_violations=[
                    "missing_done_sentinel",
                    "missing_response_contract",
                    "tool_output_over_budget",
                ],
                expected_proof_layer_seen=True,
                completion_reason="output_budget_exceeded",
            )
            probe = write_probe(
                root,
                [{"agent": "codex", "status": "pass", "token_telemetry_ready": True, "probe_token_source": "exact", "probe_exact_total_tokens": 100}],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=False,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
                allow_controlled_failures=True,
            )

            self.assertEqual(result["status"], "pass")
            self.assertNotIn("token_source", {issue["check"] for issue in result["issues"]})
            self.assertNotIn("observed_tools", {issue["check"] for issue in result["issues"]})

    def test_audit_still_fails_controlled_outcomes_when_all_pass_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(
                root,
                agent="codex",
                profile="A-search-only",
                correctness_status="fail",
                token_source="proxy",
                tool_evidence_source="missing",
                policy_violations=["tool_output_over_budget"],
                completion_reason="output_budget_exceeded",
            )
            probe = write_probe(
                root,
                [{"agent": "codex", "status": "pass", "token_telemetry_ready": True, "probe_token_source": "exact", "probe_exact_total_tokens": 100}],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
                allow_controlled_failures=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("correctness", {issue["check"] for issue in result["issues"]})

    def test_audit_requires_self_contained_run_artifacts_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "root"
            root.mkdir()
            external = Path(tmp) / "external"
            run_dir = root / "codex-run"
            write_manifest(root)
            write_required_run_artifacts(run_dir)
            write_required_run_artifacts(external)
            write_run(root, agent="codex", profile="A-search-only", run_dir=run_dir)
            write_run(
                root,
                agent="cursor-agent",
                profile="A-search-only",
                run_dir=external,
                task_id="task-2",
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex", "cursor-agent"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_expected_proof_layer=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                required_savings_claim="",
                require_self_contained_artifacts=True,
            )

            self.assertEqual(result["status"], "fail")
            messages = [issue["message"] for issue in result["issues"]]
            self.assertTrue(any("outside benchmark output" in message for message in messages))
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(requirement_by_key["run_validity_controls"]["status"], "fail")

    def test_audit_accepts_adapter_doctor_summary_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            doctor = write_doctor(
                root,
                [
                    {
                        "agent": "codex",
                        "status": "pass",
                        "probe_completion_reason": "sentinel",
                        "probe_reason": "",
                    }
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[doctor],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_fails_when_adapter_doctor_marks_agent_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            doctor = write_doctor(
                root,
                [
                    {
                        "agent": "codex",
                        "status": "pass",
                        "ready_for_live_benchmark": False,
                        "reason": "route_isolation_weak",
                        "next_action": "fix weak route-isolation controls before benchmark use",
                    }
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[doctor],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("adapter_probe", {issue["check"] for issue in result["issues"]})
            self.assertIn("not ready for live benchmark", result["blockers"][0])

    def test_audit_fails_when_adapter_probe_has_weak_route_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            probe = write_probe(
                root,
                [
                    {
                        "agent": "codex",
                        "status": "pass",
                        "route_weak_controls": ["cursor_mcp_probe_unavailable"],
                    }
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("weak route-isolation controls", result["blockers"][0])

    def test_audit_fails_when_adapter_token_telemetry_is_proxy_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            doctor = write_doctor(
                root,
                [
                    {
                        "agent": "codex",
                        "status": "pass",
                        "ready_for_live_benchmark": True,
                        "token_telemetry_ready": False,
                        "probe_token_source": "proxy",
                        "token_telemetry_next_action": "enable exact telemetry",
                    }
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[doctor],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
            )

            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(result["status"], "fail")
            self.assertIn("token_source", {issue["check"] for issue in result["issues"]})
            self.assertEqual(requirement_by_key["token_measurement"]["status"], "fail")

    def test_audit_fails_when_adapter_token_source_has_no_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            doctor = write_doctor(
                root,
                [
                    {
                        "agent": "codex",
                        "status": "pass",
                        "ready_for_live_benchmark": True,
                        "token_telemetry_ready": True,
                        "probe_token_source": "exact",
                        "probe_exact_usage_event_count": 2,
                        "token_telemetry_next_action": "ready",
                    }
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[doctor],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("token_source", {issue["check"] for issue in result["issues"]})

    def test_audit_can_require_paired_route_comparisons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            write_route_comparisons(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task",
                        "repo": "sample",
                        "repeat_index": "0",
                        "baseline_correctness": "pass",
                        "treatment_correctness": "pass",
                    }
                ],
            )
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_expected_proof_layer=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=True,
                required_savings_claim="",
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_fails_when_paired_route_comparisons_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=True,
                required_savings_claim="",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("route_comparisons", {issue["check"] for issue in result["issues"]})

    def test_audit_can_require_run_validity_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, snapshot_repos=True, require_clean_serena_process_state=True)
            run_dir = root / "run-a"
            write_fresh_session_telemetry(run_dir, session="rarb-codex-a")
            write_run(root, agent="codex", profile="A-search-only", run_dir=run_dir)
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_fresh_sessions=True,
                require_randomized_order=True,
                require_repo_snapshots=True,
                require_repo_metadata=True,
                require_clean_serena_process_state=True,
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_can_require_clean_serena_process_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, require_clean_serena_process_state=False)
            write_run(
                root,
                agent="codex",
                profile="D-full-router",
                serena_readiness_warnings=["multiple_serena_mcp_processes"],
            )
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_clean_serena_process_state=True,
            )

            self.assertEqual(result["status"], "fail")
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(requirement_by_key["run_validity_controls"]["status"], "fail")
            self.assertIn("serena_process_state", {issue["check"] for issue in result["issues"]})

    def test_audit_fails_when_fresh_session_proof_reuses_session_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, snapshot_repos=True)
            run_a = root / "run-a"
            run_b = root / "run-b"
            write_fresh_session_telemetry(run_a, session="rarb-reused")
            write_fresh_session_telemetry(run_b, session="rarb-reused")
            write_run(root, agent="codex", profile="A-search-only", run_dir=run_a)
            write_run(root, agent="codex", profile="D-full-router", run_dir=run_b)
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_fresh_sessions=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("fresh_sessions", {issue["check"] for issue in result["issues"]})

    def test_audit_can_require_real_task_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_manifest = root / "android-realworld.local.tsv"
            task_manifest.write_text("task_id\nreal-task\n", encoding="utf-8")
            write_manifest(root, task_manifest=str(task_manifest))
            write_run(root, agent="codex", profile="A-search-only")

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=False,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_real_task_manifest=True,
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_rejects_sample_task_manifest_for_publishable_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_manifest = root / "android-realworld.sample.tsv"
            task_manifest.write_text("task_id\nsample-task\n", encoding="utf-8")
            write_manifest(root, task_manifest=str(task_manifest))
            write_run(root, agent="codex", profile="A-search-only")

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=False,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_real_task_manifest=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("real_task_manifest", {issue["check"] for issue in result["issues"]})

    def test_audit_fails_when_run_repo_path_does_not_match_repo_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            wrong_repo = root / "wrong-repo"
            wrong_repo.mkdir()
            write_run(root, agent="codex", profile="A-search-only", repo_path=str(wrong_repo))

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=False,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_repo_metadata=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("run repo_path does not match repo_map", result["blockers"][0])

    def test_audit_fails_for_missing_run_validity_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(
                root,
                fresh_sessions=False,
                randomized_order=False,
                snapshot_repos=False,
                include_repo_metadata=False,
            )
            write_run(root, agent="codex", profile="A-search-only")
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_fresh_sessions=True,
                require_randomized_order=True,
                require_repo_snapshots=True,
                require_repo_metadata=True,
            )

            checks = {issue["check"] for issue in result["issues"]}
            self.assertEqual(result["status"], "fail")
            self.assertIn("fresh_sessions", checks)
            self.assertIn("randomized_order", checks)
            self.assertIn("repo_snapshots", checks)
            self.assertIn("repo_metadata", checks)

    def test_audit_fails_when_run_repo_is_missing_from_repo_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, snapshot_repos=True)
            write_run(root, agent="codex", profile="A-search-only", repo="sample_retail_android")
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_fresh_sessions=True,
                require_randomized_order=True,
                require_repo_snapshots=True,
                require_repo_metadata=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("missing repo_map entry for task repo sample_retail_android", result["blockers"])

    def test_audit_can_require_balanced_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            for agent in ("codex", "cursor-agent"):
                for profile in ("A-search-only", "D-full-router"):
                    write_run(root, agent=agent, profile=profile, task_id="task", repeat_index=0)
            probe = write_probe(
                root,
                [
                    {"agent": "codex", "status": "pass"},
                    {"agent": "cursor-agent", "status": "pass"},
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex", "cursor-agent"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_balanced_matrix=True,
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_fails_for_missing_balanced_matrix_cell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only", task_id="task", repeat_index=0)
            write_run(root, agent="codex", profile="D-full-router", task_id="task", repeat_index=0)
            write_run(root, agent="cursor-agent", profile="A-search-only", task_id="task", repeat_index=0)
            probe = write_probe(
                root,
                [
                    {"agent": "codex", "status": "pass"},
                    {"agent": "cursor-agent", "status": "pass"},
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex", "cursor-agent"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_balanced_matrix=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("balanced_matrix", {issue["check"] for issue in result["issues"]})
            self.assertIn("cursor-agent/D-full-router/task/repeat 0", result["blockers"][0])

    def test_audit_can_require_expected_proof_layer_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only", expected_proof_layer_seen=True)
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_expected_proof_layer=True,
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_fails_when_expected_proof_layer_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only", expected_proof_layer_seen=False)
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_expected_proof_layer=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("expected_proof_layer", {issue["check"] for issue in result["issues"]})

    def test_audit_can_require_supported_exact_savings_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            write_route_claim_readiness(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": True,
                        "model_visible_proxy_savings_claim_supported": False,
                    }
                ],
            )
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="exact",
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_fails_when_required_savings_claim_is_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            write_route_claim_readiness(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "model_visible_proxy_savings_claim_supported": True,
                        "exact_claim_blockers": ["exact_token_savings_not_positive"],
                        "proxy_claim_blockers": [],
                    }
                ],
            )
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="exact",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("route_claim_readiness", {issue["check"] for issue in result["issues"]})

    def test_audit_can_require_minimum_supported_savings_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            write_route_claim_readiness(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task-supported",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "model_visible_proxy_savings_claim_supported": True,
                    },
                    {
                        "agent": "codex",
                        "task_id": "task-unsupported",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "model_visible_proxy_savings_claim_supported": False,
                        "proxy_claim_blockers": ["model_visible_proxy_savings_not_positive"],
                    },
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                required_savings_claim="proxy",
                min_supported_savings_pairs=1,
            )

            self.assertEqual(result["status"], "pass")
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(requirement_by_key["savings_claim"]["status"], "pass")

    def test_audit_can_require_minimum_supported_uncached_exact_savings_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            write_route_claim_readiness(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task-supported",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "exact_uncached_token_savings_claim_supported": True,
                        "model_visible_proxy_savings_claim_supported": False,
                        "exact_claim_blockers": ["exact_token_savings_not_positive"],
                    },
                    {
                        "agent": "codex",
                        "task_id": "task-unsupported",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "exact_uncached_token_savings_claim_supported": False,
                        "model_visible_proxy_savings_claim_supported": False,
                        "exact_uncached_claim_blockers": ["exact_uncached_token_savings_not_positive"],
                    },
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                required_savings_claim="exact_uncached",
                min_supported_savings_pairs=1,
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_can_require_agent_reported_savings_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only", token_source="agent_reported")
            write_run(root, agent="codex", profile="D-full-router", token_source="agent_reported")
            write_route_claim_readiness(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task-supported",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "exact_uncached_token_savings_claim_supported": False,
                        "agent_reported_token_savings_claim_supported": True,
                        "model_visible_proxy_savings_claim_supported": False,
                    }
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                required_savings_claim="agent_reported",
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_fails_when_minimum_supported_savings_pairs_is_not_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            write_route_claim_readiness(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "model_visible_proxy_savings_claim_supported": True,
                    }
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                required_savings_claim="proxy",
                min_supported_savings_pairs=2,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("too few supported pairs", result["blockers"][0])

    def test_audit_accepts_any_savings_claim_when_proxy_only_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            write_route_claim_readiness(
                root,
                [
                    {
                        "agent": "codex",
                        "task_id": "task",
                        "repo": "sample",
                        "repeat_index": "0",
                        "exact_token_savings_claim_supported": False,
                        "model_visible_proxy_savings_claim_supported": True,
                    }
                ],
            )
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="any",
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_can_require_live_lifecycle_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            write_manifest(root)
            write_lifecycle_telemetry(run_dir)
            write_run(root, agent="codex", profile="A-search-only", run_dir=run_dir)
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_live_lifecycle_telemetry=True,
            )

            self.assertEqual(result["status"], "pass")

    def test_audit_fails_for_incomplete_live_lifecycle_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            write_manifest(root)
            write_lifecycle_telemetry(run_dir, complete=False)
            write_run(root, agent="codex", profile="A-search-only", run_dir=run_dir)
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_live_lifecycle_telemetry=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("live_lifecycle_telemetry", {issue["check"] for issue in result["issues"]})

    def test_audit_fails_for_scaffold_or_incomplete_benchmark_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, dirty=True)
            write_run(
                root,
                agent="codex",
                profile="A-search-only",
                correctness_status="fail",
                token_source="proxy",
                route_isolation_mode="prompt-plus-env",
                route_hard_controls=[],
                route_weak_controls=["weak_only"],
            )
            probe = write_probe(
                root,
                [
                    {"agent": "codex", "status": "pass"},
                    {"agent": "cursor-agent", "status": "fail", "reason": "quota_exceeded"},
                ],
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex", "cursor-agent"],
                expected_profiles=["A-search-only", "D-full-router"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                required_savings_claim="",
            )

            checks = {issue["check"] for issue in result["issues"]}
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["requirement_status"], "fail")
            self.assertIn("clean_repo", checks)
            self.assertIn("correctness", checks)
            self.assertIn("token_source", checks)
            self.assertIn("route_isolation", checks)
            self.assertIn("adapter_probe", checks)
            self.assertIn("agent_profile_matrix", checks)
            self.assertEqual(requirement_by_key["adapter_readiness"]["status"], "fail")
            self.assertEqual(requirement_by_key["balanced_multi_agent_matrix"]["status"], "fail")
            self.assertEqual(requirement_by_key["correctness_policy_and_proof"]["status"], "fail")
            self.assertEqual(requirement_by_key["token_measurement"]["status"], "fail")
            self.assertTrue(requirement_by_key["token_measurement"]["blockers"])

    def test_audit_fails_when_route_isolation_row_is_stale_against_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            run_dir = root / "run"
            write_run(root, agent="codex", profile="A-search-only", run_dir=run_dir)
            to_json_file(
                run_dir / "route-isolation.json",
                {
                    "mode": "prompt-plus-env",
                    "hard_controls": [],
                    "weak_controls": ["stale_weak_control"],
                },
            )

            result = audit(
                benchmark_out=root,
                adapter_probe=None,
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("route_isolation", {issue["check"] for issue in result["issues"]})
            self.assertTrue(
                any("route-isolation.json" in issue["message"] for issue in result["issues"] if issue["check"] == "route_isolation")
            )

    def test_cli_accepts_multiple_adapter_probe_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            codex_probe = write_probe(root, [{"agent": "codex", "status": "pass"}])
            second_probe = root / "adapter-probe-2"
            second_probe.mkdir()
            to_json_file(second_probe / "adapter-probe-summary.json", {"rows": []})

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--benchmark-out",
                        str(root),
                        "--adapter-probe",
                        str(codex_probe),
                        "--adapter-probe",
                        str(second_probe),
                        "--agents",
                        "codex",
                        "--profiles",
                        "A-search-only",
                        "--require-live",
                        "--require-clean-repos",
                        "--require-all-adapters",
                        "--require-all-pass",
                        "--require-observed-tools",
                        "--require-non-proxy-tokens",
                        "--require-no-weak-route-controls",
                        "--require-hard-isolation-for-blocked-tools",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["status"], "pass")

    def test_cli_accepts_matrix_completion_report_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_matrix_completion(root, missing_cell_count=10)
            missing_plan = write_missing_plan(root, missing_cell_count=10)
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--benchmark-out",
                        str(root),
                        "--agents",
                        "codex",
                        "--profiles",
                        "A-search-only",
                        "--require-live",
                        "--require-matrix-completion-report",
                        "--missing-plan",
                        str(missing_plan),
                    ]
                )

            self.assertEqual(code, 0)
            requirement_by_key = {item["key"]: item for item in json.loads(stdout.getvalue())["requirements"]}
            self.assertEqual(requirement_by_key["matrix_completion_report"]["status"], "pass")

    def test_audit_can_require_matrix_completion_report_matching_missing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_matrix_completion(root, missing_cell_count=10)
            missing_plan = write_missing_plan(root, missing_cell_count=10)

            result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_matrix_completion_report=True,
                missing_plan=missing_plan,
            )

            self.assertEqual(result["status"], "pass")
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(requirement_by_key["matrix_completion_report"]["status"], "pass")

    def test_audit_fails_when_matrix_completion_report_is_missing_or_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            missing_plan = write_missing_plan(root, missing_cell_count=10)

            missing_result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_matrix_completion_report=True,
                missing_plan=missing_plan,
            )
            self.assertIn("matrix_completion_report", {issue["check"] for issue in missing_result["issues"]})

            write_matrix_completion(root, missing_cell_count=9)
            stale_result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_matrix_completion_report=True,
                missing_plan=missing_plan,
            )
            self.assertIn("matrix_completion_report", {issue["check"] for issue in stale_result["issues"]})
            self.assertTrue(
                any(
                    issue["message"].endswith("missing_cell_count")
                    for issue in stale_result["issues"]
                    if issue["check"] == "matrix_completion_report"
                )
            )

    def test_audit_can_require_terminal_control_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            rows = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            write_terminal_control_summary(root, rows, complete=True)

            result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_terminal_control_summary=True,
            )

            self.assertEqual(result["status"], "pass")
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(requirement_by_key["terminal_control_summary"]["status"], "pass")

    def test_audit_fails_when_terminal_control_summary_is_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            rows = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            write_terminal_control_summary(root, rows, complete=False)

            result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_terminal_control_summary=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("terminal_control_summary", {issue["check"] for issue in result["issues"]})

    def test_audit_fails_when_terminal_control_summary_has_no_capture_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            rows = [json.loads((root / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])]
            write_terminal_control_summary(root, rows, complete=True, capture_changed=False)
            probe = write_probe(root, [{"agent": "codex", "status": "pass"}])

            result = audit(
                benchmark_out=root,
                adapter_probe=[probe],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=True,
                require_all_adapters=True,
                require_all_pass=True,
                require_observed_tools=True,
                require_non_proxy_tokens=True,
                require_no_weak_route_controls=True,
                require_hard_isolation_for_blocked_tools=True,
                require_paired_route_comparisons=False,
                require_terminal_control_summary=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn(
                "terminal-control-summary does not prove capture_changed for every run",
                result["blockers"],
            )

    def test_audit_fails_when_terminal_control_summary_is_stale_against_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            rows = [json.loads((root / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])]
            write_terminal_control_summary(root, rows, complete=True)
            telemetry_path = root / "telemetry.jsonl"
            telemetry_path.write_text('{"event":"process_started"}\n', encoding="utf-8")

            result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_terminal_control_summary=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertTrue(
                any("stale" in issue["message"] for issue in result["issues"] if issue["check"] == "terminal_control_summary")
            )

    def test_audit_can_require_route_policy_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            rows = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            write_route_policy_summary(root, rows)

            result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_route_policy_summary=True,
            )

            self.assertEqual(result["status"], "pass")
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(requirement_by_key["route_policy_summary"]["status"], "pass")

    def test_audit_fails_when_route_policy_summary_has_blocked_tool_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            rows = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            write_route_policy_summary(root, rows, blocked_violations=1)

            result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_route_policy_summary=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("route_policy_summary", {issue["check"] for issue in result["issues"]})

    def test_audit_fails_when_route_policy_summary_is_stale_against_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(
                root,
                agent="codex",
                profile="A-search-only",
                policy_violations=["blocked_tool_used:Serena", "required_first_tool_not_used"],
            )
            rows = [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            write_route_policy_summary(root, rows)

            result = audit(
                benchmark_out=root,
                adapter_probe=[],
                expected_agents=["codex"],
                expected_profiles=["A-search-only"],
                min_tasks=1,
                require_live=True,
                require_clean_repos=False,
                require_all_adapters=False,
                require_all_pass=False,
                require_observed_tools=False,
                require_non_proxy_tokens=False,
                require_no_weak_route_controls=False,
                require_hard_isolation_for_blocked_tools=False,
                require_paired_route_comparisons=False,
                require_route_policy_summary=True,
            )

            self.assertEqual(result["status"], "fail")
            self.assertTrue(
                any("stale" in issue["message"] for issue in result["issues"] if issue["check"] == "route_policy_summary")
            )

    def test_cli_codex_exact_paired_preset_blocks_incomplete_a_only_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, require_clean_serena_process_state=True)
            run_dir = root / "run-a"
            write_fresh_session_telemetry(run_dir, session="rarb-codex-a")
            write_run(root, agent="codex", profile="A-search-only", run_dir=run_dir)
            write_terminal_control_summary(
                root,
                [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()],
            )
            write_route_policy_summary(
                root,
                [json.loads(line) for line in (root / "runs.jsonl").read_text(encoding="utf-8").splitlines()],
            )
            out = root / "nested" / "audit.json"
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--benchmark-out",
                        str(root),
                        "--agents",
                        "codex",
                        "--preset",
                        "codex-exact-paired",
                        "--out",
                        str(out),
                    ]
                )

            self.assertEqual(code, 2)
            result = json.loads(out.read_text(encoding="utf-8"))
            requirement_by_key = {item["key"]: item for item in result["requirements"]}
            self.assertEqual(requirement_by_key["paired_route_comparison"]["status"], "fail")
            self.assertEqual(requirement_by_key["savings_claim"]["status"], "fail")
            self.assertIn("route_claim_readiness", {issue["check"] for issue in result["issues"]})


if __name__ == "__main__":
    unittest.main()
