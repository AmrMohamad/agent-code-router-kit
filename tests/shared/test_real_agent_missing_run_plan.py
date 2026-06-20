from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmarks.plan_missing_real_agent_runs import build_missing_run_markdown, main, plan_missing_runs
from scripts.lib.agent_session import append_jsonl, to_json_file


ROOT = Path(__file__).resolve().parents[2]


def write_manifest(root: Path) -> None:
    to_json_file(
        root / "run-manifest.json",
        {
            "repo": str(ROOT),
            "repo_map": {"sample_b2b_android": str(ROOT)},
            "task_manifest": str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
            "task_ids": ["known_symbol_definition"],
            "repeats": 1,
        },
    )


def write_manifest_with_missing_repo_map(root: Path) -> Path:
    tasks = root / "tasks.tsv"
    tasks.write_text(
        "task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds\n"
        "retail_task\tknown_kotlin_symbol_definition\tsample_retail_android\tFind CartViewModel\tA-search-only\tfalse\tfalse\tsemantic_identity_or_search_labeled\tCartViewModel definition reported\tDo not claim runtime behavior.\t900\n",
        encoding="utf-8",
    )
    to_json_file(
        root / "run-manifest.json",
        {
            "repo": str(ROOT),
            "repo_map": {"sample_b2b_android": str(ROOT)},
            "task_manifest": str(tasks),
            "task_ids": ["retail_task"],
            "repeats": 1,
        },
    )
    return tasks


def write_run(
    root: Path,
    *,
    agent: str,
    profile: str,
    task_id: str = "known_symbol_definition",
    repo: str = "sample_b2b_android",
) -> None:
    append_jsonl(
        root / "runs.jsonl",
        {
            "run_id": f"{agent}-{profile}",
            "agent": agent,
            "profile": profile,
            "task_id": task_id,
            "repo": repo,
            "repeat_index": 0,
        },
    )


def write_doctor(root: Path, rows: list[dict[str, object]]) -> Path:
    doctor = root / "doctor"
    doctor.mkdir()
    to_json_file(doctor / "adapter-doctor-summary.json", {"rows": rows})
    return doctor


class RealAgentMissingRunPlanTests(unittest.TestCase):
    def test_plan_reports_blocked_missing_agent_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            doctor = write_doctor(
                root,
                [
                    {"agent": "codex", "status": "pass", "ready_for_live_benchmark": True},
                    {
                        "agent": "cursor-agent",
                        "status": "fail",
                        "ready_for_live_benchmark": False,
                        "reason": "quota_exceeded",
                        "next_action": "restore quota",
                        "token_telemetry_ready": False,
                        "token_telemetry_next_action": "enable telemetry",
                    },
                ],
            )

            result = plan_missing_runs(
                benchmark_out=root,
                agents=["codex", "cursor-agent"],
                profiles=["A-search-only", "D-full-router"],
                adapter_probe=[doctor],
            )

            self.assertEqual(result["missing_cell_count"], 2)
            self.assertEqual(result["runnable_missing_cell_count"], 0)
            self.assertEqual(result["blocked_agents"], ["cursor-agent"])
            self.assertEqual(result["execution_plan"]["status"], "blocked")
            self.assertFalse(result["execution_plan"]["can_resume_now"])
            self.assertEqual(result["execution_plan"]["missing_by_agent"], {"cursor-agent": 2})
            self.assertEqual(result["execution_plan"]["blocked_actions"][0]["agent"], "cursor-agent")
            self.assertEqual(result["execution_plan"]["blocked_actions"][0]["missing_cells"], 2)
            self.assertFalse(result["adapter_readiness"]["cursor-agent"]["token_telemetry_ready"])
            self.assertEqual(result["adapter_readiness"]["cursor-agent"]["token_telemetry_next_action"], "enable telemetry")
            self.assertEqual({cell["profile"] for cell in result["missing_cells"]}, {"A-search-only", "D-full-router"})
            self.assertTrue(all(cell["blocker_reason"] == "quota_exceeded" for cell in result["missing_cells"]))
            self.assertTrue(all(cell["token_telemetry_ready"] is False for cell in result["missing_cells"]))
            self.assertTrue(all(cell["token_telemetry_next_action"] == "enable telemetry" for cell in result["missing_cells"]))

    def test_plan_preserves_model_access_denied_blocker_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            doctor = write_doctor(
                root,
                [
                    {
                        "agent": "claude-code",
                        "status": "fail",
                        "ready_for_live_benchmark": False,
                        "reason": "model_access_denied",
                        "next_action": "switch organization/account",
                        "token_telemetry_ready": True,
                        "probe_token_source": "exact",
                        "probe_exact_usage_event_count": 2,
                        "token_telemetry_next_action": "ready",
                    },
                ],
            )

            result = plan_missing_runs(
                benchmark_out=root,
                agents=["claude-code"],
                profiles=["A-search-only"],
                adapter_probe=[doctor],
            )

            self.assertEqual(result["blocked_agents"], ["claude-code"])
            self.assertEqual(result["execution_plan"]["blocked_actions"][0]["reason"], "model_access_denied")
            self.assertEqual(result["execution_plan"]["blocked_actions"][0]["next_action"], "switch organization/account")
            self.assertTrue(all(cell["blocker_reason"] == "model_access_denied" for cell in result["missing_cells"]))
            self.assertFalse(result["adapter_readiness"]["claude-code"]["token_telemetry_ready"])
            markdown = build_missing_run_markdown(result)
            self.assertIn("# Missing Real-Agent Benchmark Runs", markdown)
            self.assertIn("| claude-code |", markdown)
            self.assertIn("model_access_denied", markdown)
            self.assertIn("This benchmark matrix is incomplete", markdown)

    def test_plan_emits_resume_command_for_ready_missing_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")
            doctor = write_doctor(
                root,
                [
                    {"agent": "cursor-agent", "status": "pass", "ready_for_live_benchmark": True},
                ],
            )

            result = plan_missing_runs(
                benchmark_out=root,
                agents=["codex", "cursor-agent"],
                profiles=["A-search-only", "D-full-router"],
                adapter_probe=[doctor],
            )

            self.assertEqual(result["runnable_missing_cell_count"], 2)
            self.assertEqual(result["execution_plan"]["status"], "runnable")
            self.assertTrue(result["execution_plan"]["can_resume_now"])
            self.assertEqual(result["execution_plan"]["runnable_agents"], ["cursor-agent"])
            self.assertEqual(result["resume_commands"][0]["agent"], "cursor-agent")
            argv = result["resume_commands"][0]["argv"]
            self.assertIn("--resume-from", argv)
            self.assertIn(str(root.resolve()), argv)
            self.assertIn("--snapshot-repos", argv)
            markdown = build_missing_run_markdown(result)
            self.assertIn("## Resume Commands", markdown)
            self.assertIn("cursor-agent", markdown)
            self.assertIn("--resume-from", markdown)

    def test_plan_blocks_resume_when_named_task_repo_mapping_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest_with_missing_repo_map(root)
            write_run(
                root,
                agent="cursor-agent",
                profile="A-search-only",
                task_id="retail_task",
                repo="sample_retail_android",
            )
            doctor = write_doctor(
                root,
                [
                    {"agent": "codex", "status": "pass", "ready_for_live_benchmark": True},
                    {"agent": "cursor-agent", "status": "pass", "ready_for_live_benchmark": True},
                ],
            )

            result = plan_missing_runs(
                benchmark_out=root,
                agents=["codex", "cursor-agent"],
                profiles=["A-search-only"],
                adapter_probe=[doctor],
            )

            self.assertEqual(result["missing_repo_map_entries"], ["sample_retail_android"])
            self.assertEqual(result["invalid_existing_runs"], 1)
            self.assertEqual(result["runnable_missing_cell_count"], 0)
            self.assertEqual(result["resume_commands"], [])
            self.assertEqual(result["execution_plan"]["status"], "blocked")
            self.assertFalse(result["execution_plan"]["can_resume_now"])
            self.assertEqual(result["missing_cells"][0]["blocker_reason"], "missing_repo_map")

    def test_plan_reports_complete_when_no_cells_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            write_run(root, agent="codex", profile="A-search-only")
            write_run(root, agent="codex", profile="D-full-router")

            result = plan_missing_runs(
                benchmark_out=root,
                agents=["codex"],
                profiles=["A-search-only", "D-full-router"],
            )

            self.assertEqual(result["missing_cell_count"], 0)
            self.assertEqual(result["execution_plan"]["status"], "complete")
            self.assertFalse(result["execution_plan"]["can_resume_now"])
            markdown = build_missing_run_markdown(result)
            self.assertIn("All requested benchmark matrix cells are present.", markdown)
            self.assertIn("This benchmark matrix is complete", markdown)

    def test_cli_returns_nonzero_when_cells_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(["--benchmark-out", str(root), "--agents", "codex", "--profiles", "A-search-only"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stdout.getvalue())["missing_cell_count"], 1)

    def test_cli_writes_markdown_when_cells_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root)
            out = root / "missing.md"
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
                        "--out-markdown",
                        str(out),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertTrue(out.exists())
            self.assertIn("Missing Real-Agent Benchmark Runs", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
