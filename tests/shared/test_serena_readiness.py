from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest import mock

from scripts.lib.serena_readiness import (
    SerenaProcess,
    SerenaProcessInspection,
    SerenaProcessState,
    candidate_source_files,
    classify_index_output,
    extract_source_symbol,
    run_serena_source_symbol_readiness,
    serena_process_cleanup_plan,
    stale_processes_from_cleanup_plan,
)


class SerenaReadinessTests(unittest.TestCase):
    def test_extract_source_symbol_prefers_task_symbol(self) -> None:
        self.assertEqual(
            extract_source_symbol("Find the definition of SampleCatalogViewModel with Serena"),
            "SampleCatalogViewModel",
        )

    def test_candidate_source_files_prefers_matching_basename(self) -> None:
        result = subprocess.CompletedProcess(
            args=["rg"],
            returncode=0,
            stdout=(
                "app/src/main/java/com/example/Screen.kt\n"
                "app/src/main/java/com/example/SampleFeatureViewModel.kt\n"
                "feature/src/main/java/com/example/Other.kt\n"
            ),
            stderr="",
        )
        with mock.patch("scripts.lib.serena_readiness.subprocess.run", return_value=result):
            files = candidate_source_files(Path("/repo"), "SampleFeatureViewModel")

        self.assertEqual(files[0], "app/src/main/java/com/example/SampleFeatureViewModel.kt")

    def test_classify_index_output_requires_symbol_line(self) -> None:
        status, ready, reason, next_action = classify_index_output(
            symbol="SampleCatalogViewModel",
            source_file="app/SampleCatalogViewModel.kt",
            returncode=0,
            stdout="Symbols in file:\n  - SampleCatalogViewModel at line 14 of kind 5\n",
            stderr="",
        )

        self.assertEqual(status, "pass")
        self.assertTrue(ready)
        self.assertEqual(reason, "")
        self.assertEqual(next_action, "ready")

    def test_classify_index_output_detects_cancelled_lsp_initialization(self) -> None:
        status, ready, reason, next_action = classify_index_output(
            symbol="SampleCatalogViewModel",
            source_file="app/SampleCatalogViewModel.kt",
            returncode=1,
            stdout="",
            stderr="request cancelled (-32800)",
        )

        self.assertEqual(status, "fail")
        self.assertFalse(ready)
        self.assertEqual(reason, "kotlin_lsp_initialization_cancelled")
        self.assertIn("restart stale Serena", next_action)

    def test_run_readiness_records_process_warnings_and_source_smoke(self) -> None:
        rg_result = subprocess.CompletedProcess(
            args=["rg"],
            returncode=0,
            stdout="app/SampleCatalogViewModel.kt\n",
            stderr="",
        )
        index_result = subprocess.CompletedProcess(
            args=["serena"],
            returncode=0,
            stdout="Symbols in file:\n  - SampleCatalogViewModel at line 14 of kind 5\n",
            stderr="",
        )

        with (
            mock.patch("scripts.lib.serena_readiness.shutil.which", return_value="/usr/local/bin/serena"),
            mock.patch(
                "scripts.lib.serena_readiness.serena_process_state",
                return_value=SerenaProcessState(serena_mcp=2, kotlin_lsp=3, json_lsp=0),
            ),
            mock.patch("scripts.lib.serena_readiness.subprocess.run", side_effect=[rg_result, index_result]),
        ):
            readiness = run_serena_source_symbol_readiness(
                repo="/repo",
                prompt="Find SampleCatalogViewModel",
                timeout_seconds=5,
            )

        self.assertTrue(readiness.ready)
        self.assertEqual(readiness.status, "pass")
        self.assertEqual(readiness.source_file, "app/SampleCatalogViewModel.kt")
        self.assertEqual(readiness.warnings, ["multiple_serena_mcp_processes", "multiple_kotlin_lsp_processes"])

    def test_cleanup_plan_lists_stale_candidates_without_terminating(self) -> None:
        plan = serena_process_cleanup_plan(
            process_state=SerenaProcessState(serena_mcp=2, kotlin_lsp=1, json_lsp=0),
            warnings=["multiple_serena_mcp_processes"],
            processes=[
                SerenaProcess(pid=101, command="serena start-mcp-server --context codex"),
                SerenaProcess(pid=102, command="serena start-mcp-server --context cursor"),
                SerenaProcess(pid=201, command="KotlinLspServerKt --stdio"),
            ],
            inspections={
                101: SerenaProcessInspection(
                    pid=101,
                    parent_pid=1,
                    parent_command="launchd",
                    elapsed="01:00",
                    cwd="/repo-a",
                    project_guess="/repo-a",
                ),
                102: SerenaProcessInspection(
                    pid=102,
                    parent_pid=1,
                    parent_command="launchd",
                    elapsed="02:00",
                    cwd="/repo-b",
                    project_guess="/repo-b",
                ),
                201: SerenaProcessInspection(
                    pid=201,
                    parent_pid=1,
                    parent_command="launchd",
                    elapsed="00:10",
                    cwd="/repo-c",
                    project_guess="/repo-c",
                ),
            },
        )

        self.assertEqual(plan["status"], "blocked")
        self.assertTrue(plan["manual_review_required"])
        candidates = plan["stale_candidate_processes"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual({candidate["pid"] for candidate in candidates}, {101, 102})
        self.assertIn("kill -TERM 101", {candidate["termination_command"] for candidate in candidates})
        self.assertEqual({candidate["project_guess"] for candidate in candidates}, {"/repo-a", "/repo-b"})
        self.assertTrue(all(candidate["safe_to_terminate"] for candidate in candidates))
        self.assertEqual(plan["cleanup_status"], "safe_execute_available")
        self.assertEqual(plan["executable_candidate_process_count"], 2)
        self.assertEqual(plan["unsafe_candidate_process_count"], 0)
        self.assertFalse(plan["unsafe_manual_review_required"])
        self.assertIn("inspection_command", plan)
        self.assertIn("execute_cleanup_command", plan)
        self.assertIn("dry_run_table_command", plan)

    def test_stale_processes_from_cleanup_plan_ignores_invalid_candidates(self) -> None:
        processes = stale_processes_from_cleanup_plan(
            {
                "stale_candidate_processes": [
                    {"pid": 101, "command": "serena start-mcp-server", "safe_to_terminate": True},
                    {"pid": "bad", "command": "KotlinLspServerKt"},
                    {"pid": 202, "command": None},
                ]
            }
        )

        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0].pid, 101)

    def test_cleanup_plan_marks_safety_exclusions_not_safe_to_terminate(self) -> None:
        plan = serena_process_cleanup_plan(
            process_state=SerenaProcessState(serena_mcp=2, kotlin_lsp=2, json_lsp=0),
            warnings=["multiple_serena_mcp_processes", "multiple_kotlin_lsp_processes"],
            processes=[
                SerenaProcess(pid=101, command="serena start-mcp-server --context=codex"),
                SerenaProcess(pid=202, command="KotlinLspServerKt --stdio"),
            ],
            inspections={
                101: SerenaProcessInspection(
                    pid=101,
                    parent_pid=10,
                    parent_command="/opt/homebrew/bin/codex",
                    elapsed="01:00",
                    cwd="/repo",
                    project_guess="/repo",
                ),
                202: SerenaProcessInspection(
                    pid=202,
                    parent_pid=101,
                    parent_command="serena start-mcp-server --context=codex",
                    elapsed="00:30",
                    cwd="/repo",
                    project_guess="/repo",
                ),
            },
        )

        candidates = {candidate["pid"]: candidate for candidate in plan["stale_candidate_processes"]}
        self.assertFalse(candidates[101]["safe_to_terminate"])
        self.assertIn("codex_process", candidates[101]["safety_exclusions"])
        self.assertFalse(candidates[202]["safe_to_terminate"])
        self.assertIn("parent_process_not_safe", candidates[202]["safety_exclusions"])
        self.assertFalse(plan["safe_to_execute"])
        self.assertEqual(plan["cleanup_status"], "manual_review_required")
        self.assertEqual(plan["executable_candidate_process_count"], 0)
        self.assertEqual(plan["unsafe_candidate_process_count"], 2)
        self.assertTrue(plan["unsafe_manual_review_required"])
        self.assertIn("default repair cannot execute", plan["operator_required_action"])

    def test_cleanup_plan_marks_processes_outside_target_repo_review_only(self) -> None:
        plan = serena_process_cleanup_plan(
            process_state=SerenaProcessState(serena_mcp=0, kotlin_lsp=2, json_lsp=0),
            warnings=["multiple_kotlin_lsp_processes"],
            target_repo="/target-repo",
            processes=[
                SerenaProcess(pid=101, command="KotlinLspServerKt --stdio"),
                SerenaProcess(pid=202, command="KotlinLspServerKt --stdio"),
            ],
            inspections={
                101: SerenaProcessInspection(
                    pid=101,
                    parent_pid=1,
                    parent_command="launchd",
                    elapsed="01:00",
                    cwd="/target-repo/app",
                    project_guess="/target-repo/app",
                ),
                202: SerenaProcessInspection(
                    pid=202,
                    parent_pid=1,
                    parent_command="launchd",
                    elapsed="01:00",
                    cwd="/other-repo",
                    project_guess="/other-repo",
                ),
            },
        )

        candidates = {candidate["pid"]: candidate for candidate in plan["stale_candidate_processes"]}
        self.assertTrue(candidates[101]["safe_to_terminate"])
        self.assertFalse(candidates[202]["safe_to_terminate"])
        self.assertIn("outside_target_repo", candidates[202]["safety_exclusions"])
        self.assertEqual(plan["cleanup_status"], "partial_safe_execute_available")
        self.assertEqual(plan["executable_candidate_process_count"], 1)
        self.assertEqual(plan["unsafe_candidate_process_count"], 1)
        self.assertTrue(plan["unsafe_manual_review_required"])
        self.assertIn("--target-repo", plan["dry_run_table_command"])


if __name__ == "__main__":
    unittest.main()
