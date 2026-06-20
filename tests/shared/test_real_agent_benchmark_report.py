from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmarks.build_real_agent_report import main, write_report
from scripts.lib.agent_session import append_jsonl, to_json_file


def write_run(
    root: Path,
    *,
    profile: str,
    exact_total_tokens: int,
    proxy_tokens: int,
    correctness_status: str = "pass",
    token_source: str = "exact",
    expected_proof_layer_seen: bool | None = True,
    route_isolation_mode: str = "config",
    route_hard_controls: list[str] | None = None,
    route_weak_controls: list[str] | None = None,
    exact_cached_input_tokens: int | None = None,
    exact_uncached_total_tokens: int | None = None,
    agent_reported_total_tokens: int | None = None,
    run_dir: Path | None = None,
) -> None:
    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "run_id": profile,
        "repeat_index": 0,
        "agent": "codex",
        "profile": profile,
        "task_id": "task",
        "task_family": "family",
        "repo": "sample",
        "correctness_status": correctness_status,
        "policy_adherence": "pass",
        "policy_violations": [],
        "token_source": token_source,
        "model_visible_proxy_tokens": proxy_tokens,
        "raw_dump_incidents": 0,
        "tool_output_bytes": 0,
        "tool_evidence_source": "observed",
        "route_isolation_mode": route_isolation_mode,
        "route_hard_controls": route_hard_controls if route_hard_controls is not None else ["test_hard_control"],
        "route_weak_controls": route_weak_controls if route_weak_controls is not None else [],
    }
    if run_dir is not None:
        row["run_dir"] = str(run_dir)
    if token_source == "exact":
        row["exact_total_tokens"] = exact_total_tokens
    if token_source == "agent_reported":
        row["agent_reported_total_tokens"] = (
            agent_reported_total_tokens if agent_reported_total_tokens is not None else exact_total_tokens
        )
    if exact_cached_input_tokens is not None:
        row["exact_cached_input_tokens"] = exact_cached_input_tokens
    if exact_uncached_total_tokens is not None:
        row["exact_uncached_total_tokens"] = exact_uncached_total_tokens
    if expected_proof_layer_seen is not None:
        row["expected_proof_layer_seen"] = expected_proof_layer_seen
    append_jsonl(
        root / "runs.jsonl",
        row,
    )


def write_terminal_artifacts(run_dir: Path, *, terminal_mode: str = "tmux", sentinel: bool = True) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    to_json_file(run_dir / "launch-plan.json", {"terminal_mode": terminal_mode})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "process_started"})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "prompt_sent"})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "terminal_capture_changed"})
    if sentinel:
        append_jsonl(run_dir / "telemetry.jsonl", {"event": "sentinel_observed"})
    append_jsonl(run_dir / "telemetry.jsonl", {"event": "tmux_session_closed" if terminal_mode == "tmux" else "process_exited"})


def write_route_isolation_artifact(run_dir: Path, *, allowed_tools: str = "rg,basic file reads", blocked_tools: str = "Serena,Kotlin LSP") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    to_json_file(
        run_dir / "route-isolation.json",
        {
            "env": {
                "RARB_ALLOWED_TOOLS": allowed_tools,
                "RARB_BLOCKED_TOOLS": blocked_tools,
            },
            "mode": "config",
            "hard_controls": ["test_hard_control"],
            "weak_controls": [],
        },
    )


class RealAgentBenchmarkReportTests(unittest.TestCase):
    def test_claim_readiness_separates_exact_and_proxy_savings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, profile="A-search-only", exact_total_tokens=100, proxy_tokens=100)
            write_run(root, profile="D-full-router", exact_total_tokens=125, proxy_tokens=60)

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            readiness = summary["route_claim_readiness"]
            self.assertEqual(readiness["paired_comparisons"], 1)
            self.assertEqual(readiness["exact_token_savings_claims_supported"], 0)
            self.assertEqual(readiness["exact_uncached_token_savings_claims_supported"], 0)
            self.assertEqual(readiness["agent_reported_token_savings_claims_supported"], 0)
            self.assertEqual(readiness["model_visible_proxy_savings_claims_supported"], 1)
            row = readiness["rows"][0]
            self.assertIn("exact_token_savings_not_positive", row["exact_claim_blockers"])
            self.assertEqual(row["model_visible_proxy_savings_claim_supported"], True)
            written = json.loads((root / "out" / "route-claim-readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(written, readiness)
            report = (root / "out" / "token-savings-report.md").read_text(encoding="utf-8")
            self.assertIn("Exact-token savings claims supported: 0 / 1", report)
            self.assertIn("Uncached exact-token savings claims supported: 0 / 1", report)
            self.assertIn("Agent-reported token savings claims supported: 0 / 1", report)
            self.assertIn("Model-visible proxy savings claims supported: 1 / 1", report)
            proof_layer_summary = json.loads((root / "out" / "proof-layer-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(proof_layer_summary["profiles"]["A-search-only"]["expected_proof_layer_seen"], 1)
            self.assertEqual(proof_layer_summary["profiles"]["D-full-router"]["expected_proof_layer_missing"], 0)
            route_isolation_summary = json.loads((root / "out" / "route-isolation-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(route_isolation_summary["profiles"]["A-search-only"]["runs_with_route_hard_controls"], 1)
            self.assertEqual(route_isolation_summary["profiles"]["D-full-router"]["runs_with_route_weak_controls"], 0)
            self.assertIn("Proof layers seen", report)
            self.assertIn("Hard-isolated runs", report)

    def test_claim_readiness_separates_raw_exact_from_uncached_exact_savings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(
                root,
                profile="A-search-only",
                exact_total_tokens=100,
                exact_cached_input_tokens=10,
                proxy_tokens=100,
            )
            write_run(
                root,
                profile="D-full-router",
                exact_total_tokens=125,
                exact_cached_input_tokens=80,
                proxy_tokens=110,
            )

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            self.assertEqual(summary["profiles"]["A-search-only"]["median_exact_uncached_total_tokens"], 90)
            self.assertEqual(summary["profiles"]["D-full-router"]["median_exact_uncached_total_tokens"], 45)
            self.assertEqual(summary["profiles"]["A-search-only"]["exact_uncached_run_count"], 1)
            readiness = summary["route_claim_readiness"]
            self.assertEqual(readiness["exact_token_savings_claims_supported"], 0)
            self.assertEqual(readiness["exact_uncached_token_savings_claims_supported"], 1)
            self.assertEqual(readiness["model_visible_proxy_savings_claims_supported"], 0)
            row = readiness["rows"][0]
            self.assertIn("exact_token_savings_not_positive", row["exact_claim_blockers"])
            self.assertTrue(row["exact_uncached_token_savings_claim_supported"])
            self.assertEqual(row["baseline_exact_uncached_total_tokens"], 90)
            self.assertEqual(row["treatment_exact_uncached_total_tokens"], 45)
            self.assertEqual(row["treatment_minus_baseline_exact_uncached_tokens"], -45)
            self.assertEqual(row["uncached_tokens_avoided"], 45)
            self.assertEqual(row["exact_uncached_token_savings_percent"], 50.0)
            comparison = summary["route_comparisons"][0]
            self.assertEqual(comparison["treatment_minus_baseline_exact_uncached_tokens"], -45)
            self.assertEqual(comparison["uncached_tokens_avoided"], 45)
            report = (root / "out" / "token-savings-report.md").read_text(encoding="utf-8")
            self.assertIn("Median uncached exact tokens", report)
            self.assertIn("Uncached tokens avoided", report)
            self.assertIn("Uncached exact savings %", report)

    def test_claim_readiness_supports_agent_reported_savings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(
                root,
                profile="A-search-only",
                token_source="agent_reported",
                exact_total_tokens=0,
                agent_reported_total_tokens=120,
                proxy_tokens=100,
            )
            write_run(
                root,
                profile="D-full-router",
                token_source="agent_reported",
                exact_total_tokens=0,
                agent_reported_total_tokens=90,
                proxy_tokens=130,
            )

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            readiness = summary["route_claim_readiness"]
            self.assertEqual(readiness["agent_reported_token_savings_claims_supported"], 1)
            self.assertEqual(readiness["exact_token_savings_claims_supported"], 0)
            self.assertEqual(readiness["model_visible_proxy_savings_claims_supported"], 0)
            row = readiness["rows"][0]
            self.assertTrue(row["agent_reported_token_savings_claim_supported"])
            self.assertEqual(row["baseline_agent_reported_total_tokens"], 120)
            self.assertEqual(row["treatment_agent_reported_total_tokens"], 90)
            self.assertEqual(row["agent_reported_total_token_delta"], -30)
            self.assertEqual(row["agent_reported_token_savings_percent"], 25.0)
            report = (root / "out" / "token-savings-report.md").read_text(encoding="utf-8")
            self.assertIn("Agent-reported savings %", report)

    def test_claim_readiness_blocks_non_pass_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, profile="A-search-only", exact_total_tokens=100, proxy_tokens=100)
            write_run(
                root,
                profile="D-full-router",
                exact_total_tokens=50,
                proxy_tokens=50,
                correctness_status="fail",
            )

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            row = summary["route_claim_readiness"]["rows"][0]
            self.assertFalse(row["exact_token_savings_claim_supported"])
            self.assertFalse(row["model_visible_proxy_savings_claim_supported"])
            self.assertIn("correctness_not_pass_pass", row["exact_claim_blockers"])
            self.assertIn("correctness_not_pass_pass", row["proxy_claim_blockers"])

    def test_report_counts_missing_expected_proof_layer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, profile="A-search-only", exact_total_tokens=100, proxy_tokens=100, expected_proof_layer_seen=None)
            write_run(root, profile="D-full-router", exact_total_tokens=80, proxy_tokens=80, expected_proof_layer_seen=False)

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            self.assertEqual(summary["profiles"]["A-search-only"]["expected_proof_layer_missing"], 1)
            self.assertEqual(summary["profiles"]["A-search-only"]["expected_proof_layer_missing_field"], 1)
            self.assertEqual(summary["profiles"]["D-full-router"]["expected_proof_layer_missing"], 1)
            proof_layer_summary = json.loads((root / "out" / "proof-layer-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(proof_layer_summary["agents"]["codex"]["expected_proof_layer_seen"], 0)
            self.assertEqual(proof_layer_summary["agents"]["codex"]["expected_proof_layer_missing"], 2)

    def test_report_counts_route_isolation_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(
                root,
                profile="A-search-only",
                exact_total_tokens=100,
                proxy_tokens=100,
                route_hard_controls=["codex_ignore_user_config", "codex_ignore_rules"],
            )
            write_run(
                root,
                profile="D-full-router",
                exact_total_tokens=80,
                proxy_tokens=80,
                route_isolation_mode="prompt-plus-env",
                route_hard_controls=[],
                route_weak_controls=["weak_control"],
            )

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            self.assertEqual(summary["profiles"]["A-search-only"]["route_hard_control_counts"]["codex_ignore_rules"], 1)
            self.assertEqual(summary["profiles"]["D-full-router"]["runs_with_route_weak_controls"], 1)
            route_isolation_summary = json.loads((root / "out" / "route-isolation-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(route_isolation_summary["agents"]["codex"]["runs_with_route_hard_controls"], 1)
            self.assertEqual(route_isolation_summary["agents"]["codex"]["runs_with_route_weak_controls"], 1)

    def test_report_includes_missing_matrix_completion_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, profile="A-search-only", exact_total_tokens=100, proxy_tokens=100)
            write_run(root, profile="D-full-router", exact_total_tokens=80, proxy_tokens=80)
            missing_plan = {
                "missing_cell_count": 10,
                "runnable_missing_cell_count": 0,
                "blocked_agents": ["claude-code"],
                "unknown_agents": [],
                "missing_repo_map_entries": [],
                "execution_plan": {
                    "status": "blocked",
                    "can_resume_now": False,
                    "completion_boundary": "missing cells remain, but no blocked adapter can be launched safely now",
                    "missing_by_agent": {"claude-code": 10},
                    "blocked_actions": [
                        {
                            "agent": "claude-code",
                            "missing_cells": 10,
                            "reason": "model_access_denied",
                        }
                    ],
                },
            }

            summary = write_report(
                runs_jsonl=root / "runs.jsonl",
                out_dir=root / "out",
                missing_plan=missing_plan,
            )

            self.assertEqual(summary["matrix_completion"]["status"], "blocked")
            self.assertEqual(summary["matrix_completion"]["missing_cell_count"], 10)
            self.assertEqual(summary["matrix_completion"]["blocked_agents"], ["claude-code"])
            matrix_summary = json.loads((root / "out" / "matrix-completion-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(matrix_summary["missing_by_agent"], {"claude-code": 10})
            report = (root / "out" / "token-savings-report.md").read_text(encoding="utf-8")
            self.assertIn("## Matrix Completion", report)
            self.assertIn("Status: `blocked`", report)
            self.assertIn("Blocked agents: `claude-code`", report)
            self.assertIn("not a full requested-agent matrix", report)

    def test_report_writes_terminal_control_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            write_terminal_artifacts(run_dir, terminal_mode="tmux")
            write_run(root, profile="A-search-only", exact_total_tokens=100, proxy_tokens=100, run_dir=run_dir)

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            self.assertEqual(summary["terminal_control"]["terminal_modes"], {"tmux": 1})
            self.assertEqual(summary["terminal_control"]["prompt_sent_count"], 1)
            self.assertEqual(summary["terminal_control"]["sentinel_observed_count"], 1)
            self.assertEqual(summary["terminal_control"]["closed_or_exited_count"], 1)
            terminal_summary = json.loads((root / "out" / "terminal-control-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(terminal_summary["rows"][0]["terminal_mode"], "tmux")
            report = (root / "out" / "token-savings-report.md").read_text(encoding="utf-8")
            self.assertIn("## Terminal Control", report)
            self.assertIn("Prompt sent: `1 / 1`", report)

    def test_report_writes_route_policy_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            write_route_isolation_artifact(run_dir)
            write_run(
                root,
                profile="A-search-only",
                exact_total_tokens=100,
                proxy_tokens=100,
                run_dir=run_dir,
                route_hard_controls=["test_hard_control"],
            )

            summary = write_report(runs_jsonl=root / "runs.jsonl", out_dir=root / "out")

            self.assertEqual(summary["route_policy"]["blocked_tool_violation_count"], 0)
            self.assertEqual(summary["route_policy"]["checkable_required_first_tool_violation_count"], 0)
            policy_summary = json.loads((root / "out" / "route-policy-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(policy_summary["rows"][0]["blocked_tools"], ["Serena", "Kotlin LSP"])
            report = (root / "out" / "token-savings-report.md").read_text(encoding="utf-8")
            self.assertIn("## Route Policy", report)
            self.assertIn("Blocked-tool violations: `0`", report)
            self.assertIn("Checkable required-first-tool violations: `0`", report)

    def test_cli_accepts_missing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_run(root, profile="A-search-only", exact_total_tokens=100, proxy_tokens=100)
            plan_path = root / "missing.json"
            plan_path.write_text(
                json.dumps(
                    {
                        "missing_cell_count": 1,
                        "runnable_missing_cell_count": 0,
                        "blocked_agents": ["claude-code"],
                        "execution_plan": {
                            "status": "blocked",
                            "can_resume_now": False,
                            "completion_boundary": "blocked by adapter",
                            "missing_by_agent": {"claude-code": 1},
                        },
                    }
                ),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--runs",
                        str(root / "runs.jsonl"),
                        "--out",
                        str(root / "out"),
                        "--missing-plan",
                        str(plan_path),
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["matrix_completion"]["missing_cell_count"], 1)
            self.assertTrue((root / "out" / "matrix-completion-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
