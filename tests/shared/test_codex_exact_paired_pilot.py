from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.benchmarks.run_codex_exact_paired_pilot import run_codex_exact_paired_pilot


ROOT = Path(__file__).resolve().parents[2]


def make_args(tmp: str, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "repo": str(ROOT),
        "repo_map": f"sample_b2b_android={ROOT}",
        "tasks": str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
        "out": str(Path(tmp) / "pilot"),
        "sanitized_out": "",
        "task_limit": 1,
        "repeats": 1,
        "timeout": 900,
        "doctor_timeout": 120,
        "serena_readiness_timeout": 90,
        "terminal_mode": None,
        "allow_dirty": True,
        "snapshot_repos": False,
        "monitor": False,
        "stream_agent_output": False,
        "seed": 123,
        "clean_out": False,
        "no_doctor_probe": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class CodexExactPairedPilotTests(unittest.TestCase):
    def test_dirty_serena_preflight_blocks_before_live_probe_or_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dirty_doctor = {
                "status": "fail",
                "serena_process_state": {"serena_mcp": 3, "kotlin_lsp": 2, "json_lsp": 0},
                "serena_process_state_warnings": [
                    "multiple_serena_mcp_processes",
                    "multiple_kotlin_lsp_processes",
                ],
                "blockers": [
                    {
                        "agent": "codex",
                        "reason": "probe_skipped",
                        "next_action": "clean stale Serena/Kotlin/JSON LSP sessions before full-router benchmark use",
                    }
                ],
            }
            with mock.patch(
                "scripts.benchmarks.run_codex_exact_paired_pilot.run_doctor",
                return_value=dirty_doctor,
            ) as doctor, mock.patch(
                "scripts.benchmarks.run_codex_exact_paired_pilot.run_benchmark"
            ) as benchmark, mock.patch(
                "scripts.benchmarks.run_codex_exact_paired_pilot.serena_process_cleanup_plan",
                return_value={
                    "status": "blocked",
                    "safe_to_execute": True,
                    "cleanup_status": "safe_execute_available",
                    "operator_required_action": "review candidate table",
                    "executable_candidate_process_count": 2,
                    "unsafe_candidate_process_count": 0,
                    "dry_run_cleanup_command": "python3 scripts/benchmarks/repair_serena_process_state.py --dry-run --out /tmp/serena-process-repair.json",
                    "dry_run_table_command": "python3 scripts/benchmarks/repair_serena_process_state.py --dry-run --format text --out /tmp/serena-process-repair.json",
                    "execute_cleanup_command": "python3 scripts/benchmarks/repair_serena_process_state.py --execute --out /tmp/serena-process-repair.json",
                    "partial_safe_execute_command": "python3 scripts/benchmarks/repair_serena_process_state.py --execute --allow-partial-safe-execute --out /tmp/serena-process-repair.json",
                    "review_only_execute_command": "python3 scripts/benchmarks/repair_serena_process_state.py --execute --approve-review-only-candidates --approval-token TERMINATE_REVIEW_ONLY_SERENA_PROCESSES --out /tmp/serena-process-repair.json",
                    "stale_candidate_processes": [
                        {"kind": "serena_mcp", "pid": 101, "command": "serena start-mcp-server"},
                        {"kind": "kotlin_lsp", "pid": 202, "command": "KotlinLspServerKt"},
                    ],
                },
            ) as cleanup_plan_mock:
                code, status = run_codex_exact_paired_pilot(make_args(tmp))
                status_file = Path(status["status_file"])
                self.assertTrue(status_file.exists())
                persisted = json.loads(status_file.read_text(encoding="utf-8"))
                cleanup_plan_path = Path(status["serena_cleanup_plan"])
                self.assertTrue(cleanup_plan_path.exists())
                cleanup_plan = json.loads(cleanup_plan_path.read_text(encoding="utf-8"))

            self.assertEqual(code, 2)
            self.assertEqual(status["status"], "blocked")
            self.assertEqual(status["phase"], "doctor-preflight")
            self.assertIn("multiple_serena_mcp_processes", status["serena_process_state_warnings"])
            self.assertEqual(status["stale_candidate_process_count"], 2)
            self.assertEqual(status["executable_candidate_process_count"], 2)
            self.assertEqual(status["unsafe_candidate_process_count"], 0)
            self.assertTrue(status["serena_cleanup_safe_to_execute"])
            self.assertEqual(status["serena_cleanup_status"], "safe_execute_available")
            self.assertEqual(status["operator_required_action"], "review candidate table")
            self.assertIn("--dry-run", status["dry_run_cleanup_command"])
            self.assertIn("--format text", status["dry_run_table_command"])
            self.assertIn("--execute", status["execute_cleanup_command"])
            self.assertIn("--allow-partial-safe-execute", status["partial_safe_execute_command"])
            self.assertIn("--approve-review-only-candidates", status["review_only_execute_command"])
            self.assertEqual(len(cleanup_plan["stale_candidate_processes"]), 2)
            self.assertFalse(benchmark.called)
            self.assertEqual(doctor.call_count, 1)
            self.assertFalse(doctor.call_args.kwargs["run_probe"])
            self.assertEqual(cleanup_plan_mock.call_args.kwargs["target_repo"], str(ROOT))
            self.assertEqual(persisted["phase"], "doctor-preflight")

    def test_successful_pilot_runs_probe_benchmark_audit_and_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clean_doctor = {
                "status": "fail",
                "serena_process_state": {"serena_mcp": 1, "kotlin_lsp": 1, "json_lsp": 0},
                "serena_process_state_warnings": [],
                "blockers": [{"agent": "codex", "reason": "probe_skipped"}],
            }
            passing_doctor = {
                "status": "pass",
                "serena_process_state": {"serena_mcp": 1, "kotlin_lsp": 1, "json_lsp": 0},
                "serena_process_state_warnings": [],
                "blockers": [],
            }
            with mock.patch(
                "scripts.benchmarks.run_codex_exact_paired_pilot.run_doctor",
                side_effect=[clean_doctor, passing_doctor],
            ) as doctor, mock.patch(
                "scripts.benchmarks.run_codex_exact_paired_pilot.run_benchmark",
                return_value={"summary": {"runs": 2}},
            ) as benchmark, mock.patch(
                "scripts.benchmarks.run_codex_exact_paired_pilot.strict_codex_paired_audit",
                return_value={"status": "pass", "blockers": []},
            ) as audit, mock.patch(
                "scripts.benchmarks.run_codex_exact_paired_pilot.export_sanitized_live_pilot",
                return_value={"status": "pass", "run_count": 2},
            ) as export:
                code, status = run_codex_exact_paired_pilot(make_args(tmp))

        self.assertEqual(code, 0)
        self.assertEqual(status["status"], "pass")
        self.assertEqual(status["phase"], "export")
        self.assertEqual(doctor.call_count, 2)
        self.assertFalse(doctor.call_args_list[0].kwargs["run_probe"])
        self.assertTrue(doctor.call_args_list[1].kwargs["run_probe"])
        self.assertTrue(benchmark.called)
        self.assertTrue(audit.called)
        self.assertTrue(export.called)
        self.assertEqual(status["benchmark_summary"], {"runs": 2})


if __name__ == "__main__":
    unittest.main()
