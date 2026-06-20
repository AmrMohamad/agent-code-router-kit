from __future__ import annotations

import unittest
from unittest import mock

from scripts.benchmarks.repair_serena_process_state import format_repair_table, repair_serena_process_state


DIRTY_PLAN = {
    "status": "blocked",
    "cleanup_status": "safe_execute_available",
    "safe_to_execute": True,
    "operator_required_action": "review candidate table",
    "executable_candidate_process_count": 2,
    "unsafe_candidate_process_count": 0,
    "dry_run_cleanup_command": "python3 scripts/benchmarks/repair_serena_process_state.py --dry-run --out /tmp/serena-process-repair.json",
    "execute_cleanup_command": "python3 scripts/benchmarks/repair_serena_process_state.py --execute --out /tmp/serena-process-repair.json",
    "partial_safe_execute_command": "python3 scripts/benchmarks/repair_serena_process_state.py --execute --allow-partial-safe-execute --out /tmp/serena-process-repair.json",
    "review_only_execute_command": "python3 scripts/benchmarks/repair_serena_process_state.py --execute --approve-review-only-candidates --approval-token TERMINATE_REVIEW_ONLY_SERENA_PROCESSES --out /tmp/serena-process-repair.json",
    "stale_candidate_processes": [
        {
            "kind": "serena_mcp",
            "pid": 101,
            "command": "serena start-mcp-server",
            "elapsed": "01:00",
            "parent_pid": 1,
            "parent_command": "launchd",
            "project_guess": "/repo",
            "safe_to_terminate": True,
            "safety_exclusions": [],
            "kill_reason": "stale serena_mcp process",
        },
        {
            "kind": "kotlin_lsp",
            "pid": 202,
            "command": "KotlinLspServerKt --stdio",
            "elapsed": "02:00",
            "parent_pid": 1,
            "parent_command": "launchd",
            "project_guess": "/repo",
            "safe_to_terminate": True,
            "safety_exclusions": [],
            "kill_reason": "stale kotlin_lsp process",
        },
    ],
}
CLEAN_PLAN = {"status": "clean", "stale_candidate_processes": []}
MIXED_SAFE_PLAN = {
    "status": "blocked",
    "stale_candidate_processes": [
        {
            "kind": "serena_mcp",
            "pid": 101,
            "command": "serena start-mcp-server",
            "safe_to_terminate": False,
            "safety_exclusions": ["codex_process"],
        },
        {
            "kind": "kotlin_lsp",
            "pid": 202,
            "command": "KotlinLspServerKt --stdio",
            "safe_to_terminate": True,
        },
    ],
}
ALL_UNSAFE_PLAN = {
    "status": "blocked",
    "stale_candidate_processes": [
        {
            "kind": "serena_mcp",
            "pid": 101,
            "command": "serena start-mcp-server",
            "safe_to_terminate": False,
            "safety_exclusions": ["codex_process"],
        }
    ],
}


class SerenaProcessRepairTests(unittest.TestCase):
    def test_dry_run_does_not_terminate_processes(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            return_value=DIRTY_PLAN,
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes"
        ) as terminate:
            result = repair_serena_process_state(execute=False)

        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["stale_candidate_process_count"], 2)
        self.assertEqual(result["executable_candidate_process_count"], 2)
        self.assertIsNone(result["after"])
        self.assertFalse(terminate.called)

    def test_execute_terminates_only_stale_candidates_and_records_after_plan(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            side_effect=[DIRTY_PLAN, CLEAN_PLAN],
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes",
            return_value=[{"pid": 101, "terminated": True}, {"pid": 202, "terminated": True}],
        ) as terminate:
            result = repair_serena_process_state(execute=True)

        self.assertEqual(result["mode"], "execute")
        self.assertEqual(result["status"], "executed")
        self.assertEqual(result["after"], CLEAN_PLAN)
        self.assertEqual([process.pid for process in terminate.call_args.args[0]], [101, 202])

    def test_execute_skips_candidates_not_marked_safe(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            return_value=ALL_UNSAFE_PLAN,
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes"
        ) as terminate:
            result = repair_serena_process_state(execute=True)

        self.assertEqual(result["status"], "refused_partial_cleanup")
        self.assertEqual(result["stale_candidate_process_count"], 1)
        self.assertEqual(result["executable_candidate_process_count"], 0)
        self.assertEqual(result["unsafe_candidate_process_count"], 1)
        self.assertFalse(terminate.called)
        self.assertIsNone(result["after"])

    def test_execute_refuses_partial_cleanup_when_unsafe_candidates_remain(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            return_value=MIXED_SAFE_PLAN,
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes"
        ) as terminate:
            result = repair_serena_process_state(execute=True)

        self.assertEqual(result["status"], "refused_partial_cleanup")
        self.assertEqual(result["stale_candidate_process_count"], 2)
        self.assertEqual(result["executable_candidate_process_count"], 1)
        self.assertEqual(result["unsafe_candidate_process_count"], 1)
        self.assertFalse(terminate.called)
        self.assertIsNone(result["after"])

    def test_partial_override_executes_only_safe_candidates(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            side_effect=[MIXED_SAFE_PLAN, CLEAN_PLAN],
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes",
            return_value=[{"pid": 202, "terminated": True}],
        ) as terminate:
            result = repair_serena_process_state(execute=True, allow_partial_safe_execute=True)

        self.assertEqual(result["status"], "executed")
        self.assertTrue(result["allow_partial_safe_execute"])
        self.assertEqual([process.pid for process in terminate.call_args.args[0]], [202])
        self.assertEqual(result["after"], CLEAN_PLAN)

    def test_partial_override_with_no_safe_candidates_reports_blocked_not_executed(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            return_value=ALL_UNSAFE_PLAN,
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes"
        ) as terminate:
            result = repair_serena_process_state(execute=True, allow_partial_safe_execute=True)

        self.assertEqual(result["status"], "blocked_no_safe_candidates")
        self.assertTrue(result["allow_partial_safe_execute"])
        self.assertEqual(result["executable_candidate_process_count"], 0)
        self.assertEqual(result["unsafe_candidate_process_count"], 1)
        self.assertIn("no cleanup candidates are safe", result["next_action"])
        self.assertFalse(terminate.called)
        self.assertIsNone(result["after"])

    def test_review_only_override_requires_exact_approval_token(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            return_value=ALL_UNSAFE_PLAN,
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes"
        ) as terminate:
            result = repair_serena_process_state(
                execute=True,
                approve_review_only_candidates=True,
                approval_token="wrong",
            )

        self.assertEqual(result["status"], "refused_missing_review_only_approval")
        self.assertFalse(result["review_only_approval_accepted"])
        self.assertFalse(terminate.called)
        self.assertIsNone(result["after"])

    def test_review_only_override_executes_all_stale_candidates_with_exact_token(self) -> None:
        with mock.patch(
            "scripts.benchmarks.repair_serena_process_state.serena_process_cleanup_plan",
            side_effect=[ALL_UNSAFE_PLAN, CLEAN_PLAN],
        ), mock.patch(
            "scripts.benchmarks.repair_serena_process_state.terminate_processes",
            return_value=[{"pid": 101, "terminated": True}],
        ) as terminate:
            result = repair_serena_process_state(
                execute=True,
                approve_review_only_candidates=True,
                approval_token="TERMINATE_REVIEW_ONLY_SERENA_PROCESSES",
            )

        self.assertEqual(result["status"], "executed_review_only_approved")
        self.assertTrue(result["review_only_approval_accepted"])
        self.assertEqual(result["executable_candidate_process_count"], 0)
        self.assertEqual(result["selected_process_count"], 1)
        self.assertEqual(result["unsafe_candidate_process_count"], 1)
        self.assertEqual([process.pid for process in terminate.call_args.args[0]], [101])
        self.assertEqual(result["after"], CLEAN_PLAN)

    def test_format_repair_table_includes_review_columns_and_commands(self) -> None:
        table = format_repair_table({"before": DIRTY_PLAN})

        self.assertIn("Summary:", table)
        self.assertIn("cleanup_status: safe_execute_available", table)
        self.assertIn("safe_to_execute: True", table)
        self.assertIn("executable_candidates: 2", table)
        self.assertIn("unsafe_candidates: 0", table)
        self.assertIn("PID", table)
        self.assertIn("process kind", table)
        self.assertIn("command", table)
        self.assertIn("parent command", table)
        self.assertIn("project/cwd guess", table)
        self.assertIn("exclusions", table)
        self.assertIn("kill reason", table)
        self.assertIn("serena start-mcp-server", table)
        self.assertIn("101", table)
        self.assertIn("--execute", table)
        self.assertIn("--allow-partial-safe-execute", table)
        self.assertIn("--approve-review-only-candidates", table)


if __name__ == "__main__":
    unittest.main()
