from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts.benchmarks.judge_agent_run import judge_transcript, main
from scripts.lib.agent_session import load_route_profile, load_tasks


ROOT = Path(__file__).resolve().parents[2]


class AgentJudgeTests(unittest.TestCase):
    def test_missing_sentinel_fails_contract(self) -> None:
        result = judge_transcript("BENCHMARK_RESULT\nstatus: pass\n")
        self.assertFalse(result["contract_valid"])
        self.assertIn("missing_done_sentinel", result["violations"])

    def test_valid_response_passes(self) -> None:
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
confidence: high
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  ok
BENCHMARK_DONE
""",
            dry_run=True,
        )
        self.assertTrue(result["contract_valid"])
        self.assertEqual(result["correctness_status"], "dry_run_contract_pass")

    def test_policy_failure_fails_correctness(self) -> None:
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
raw_dump_incidents:
  count: 0
policy_adherence: fail
final_answer:
  ok
BENCHMARK_DONE
"""
        )
        self.assertEqual(result["correctness_status"], "fail")
        self.assertIn("policy_adherence_failed", result["violations"])

    def test_blocked_tool_fails_route_policy(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
tools_used:
  - Serena
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  ok
BENCHMARK_DONE
""",
            route_profile=profile,
        )
        self.assertEqual(result["correctness_status"], "fail")
        self.assertIn("blocked_tool_used:Serena", result["violations"])

    def test_first_tool_policy_ignores_shell_plumbing(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
        task = next(
            task
            for task in load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv")
            if task.task_id == "high_fanout_usecase"
        )
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
tools_used:
  - rg
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  Summary counts reported: Search evidence indicates UseCase is concentrated in app-core with about 127 matching files, then checkout modules.
BENCHMARK_DONE
""",
            route_profile=profile,
            task=task,
            metrics={
                "observed_task_tools": ["pwd", "printf", "rg"],
                "tool_evidence_source": "observed",
                "search_count": 1,
            },
        )

        self.assertEqual(result["correctness_status"], "pass")
        self.assertNotIn("required_first_tool_not_used", result["violations"])

    def test_observed_tool_evidence_overrides_self_report(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
tools_used:
  - rg
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  ok
BENCHMARK_DONE
""",
            route_profile=profile,
            metrics={"observed_tools": ["serena/find_symbol"], "tool_evidence_source": "observed"},
        )
        self.assertEqual(result["correctness_status"], "fail")
        self.assertIn("blocked_tool_used:Serena", result["violations"])

    def test_search_only_blocks_provider_neutral_semantic_tool_names(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/B-search-summary.yaml")
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
tools_used:
  - rg
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  grouped summary reported
BENCHMARK_DONE
""",
            route_profile=profile,
            metrics={"observed_task_tools": ["find_symbol"], "tool_evidence_source": "observed"},
        )

        self.assertEqual(result["correctness_status"], "fail")
        self.assertTrue(any(item.startswith("blocked_tool_used:") for item in result["violations"]))

    def test_live_pass_requires_expected_proof_layer_evidence(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
        task = next(
            task
            for task in load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv")
            if task.task_id == "flow_collect_structural_pattern"
        )
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
tools_used:
  - rg
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  structural summary reported from plain search only
BENCHMARK_DONE
""",
            route_profile=profile,
            task=task,
            metrics={"observed_task_tools": ["rg"], "tool_evidence_source": "observed", "search_count": 1},
        )

        self.assertEqual(result["correctness_status"], "fail")
        self.assertFalse(result["expected_proof_layer_seen"])
        self.assertIn("expected_proof_layer_missing", result["violations"])

    def test_live_pass_accepts_observed_expected_proof_layer(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
        task = next(
            task
            for task in load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv")
            if task.task_id == "flow_collect_structural_pattern"
        )
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
tools_used:
  - ast-grep
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  structural summary reported from ast-grep pattern evidence
BENCHMARK_DONE
""",
            route_profile=profile,
            task=task,
            metrics={"observed_task_tools": ["ast-grep"], "tool_evidence_source": "observed", "ast_grep_count": 1},
        )

        self.assertEqual(result["correctness_status"], "pass")
        self.assertTrue(result["expected_proof_layer_seen"])

    def test_judge_ignores_echoed_user_prompt_for_forbidden_claims(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
        task = next(
            task
            for task in load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv")
            if task.task_id == "known_symbol_definition"
        )
        transcript = (
            '{"type":"user","message":{"role":"user","content":[{"type":"text",'
            '"text":"Do not claim runtime behavior."}]}}\n'
            '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"'
            "BENCHMARK_RESULT\\nstatus: pass\\nconfidence: high\\ntools_used:\\n  - rg\\n"
            "files_opened:\\n  count: 1\\n  paths:\\n    - app/src/main/java/com/example/SampleFeatureViewModel.kt\\n"
            "raw_dump_incidents:\\n  count: 0\\npolicy_adherence: pass\\nfinal_answer:\\n"
            "Definition location reported: `SampleFeatureViewModel` is defined in `app/src/main/java/com/example/SampleFeatureViewModel.kt`. "
            "Evidence layer: search-only. No runtime behavior was claimed or tested.\\nBENCHMARK_DONE"
            '"}]}}\n'
        )
        result = judge_transcript(
            transcript,
            route_profile=profile,
            task=task,
            metrics={"observed_task_tools": ["rg"], "tool_evidence_source": "observed", "search_count": 1},
        )

        self.assertEqual(result["correctness_status"], "pass")
        self.assertNotIn("forbidden_claim_echoed", result["violations"])
        self.assertTrue(result["expected_success_signal_seen"])

    def test_high_fanout_summary_accepts_grouped_count_wording(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
        task = next(
            task
            for task in load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv")
            if task.task_id == "high_fanout_usecase"
        )
        result = judge_transcript(
            """BENCHMARK_RESULT
status: pass
tools_used:
  - rg
raw_dump_incidents:
  count: 0
policy_adherence: pass
final_answer:
  Summary counts reported: Search evidence indicates UseCase is concentrated in app-core with about 127 matching files, then checkout and feature modules.
BENCHMARK_DONE
""",
            route_profile=profile,
            task=task,
            metrics={"observed_task_tools": ["rg"], "tool_evidence_source": "observed", "search_count": 1},
        )

        self.assertEqual(result["correctness_status"], "pass")
        self.assertTrue(result["expected_proof_layer_seen"])

    def test_cli_returns_nonzero_for_policy_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "transcript.txt"
            transcript.write_text(
                """BENCHMARK_RESULT
status: pass
raw_dump_incidents:
  count: 0
policy_adherence: fail
final_answer:
  ok
BENCHMARK_DONE
""",
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--transcript", str(transcript)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
