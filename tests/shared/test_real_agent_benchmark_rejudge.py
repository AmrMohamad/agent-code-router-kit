from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmarks.rejudge_real_agent_benchmark import rejudge
from scripts.lib.agent_session import append_jsonl, to_json_file


TASKS_TSV = """task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds
sample_task\tknown_kotlin_symbol_definition\tsample\tFind SampleFeatureViewModel\tA-search-only\tfalse\tfalse\tsemantic_identity_or_search_labeled\tSampleFeatureViewModel\tDo not claim runtime behavior.\t900
"""


TRANSCRIPT = """{"type":"item.completed","item":{"type":"command_execution","command":"/bin/zsh -lc \\"rg -n SampleFeatureViewModel app/src/main/java\\""}}
{"type":"usage","input_tokens":10,"cached_input_tokens":4,"output_tokens":5,"reasoning_output_tokens":2}
BENCHMARK_RESULT
status: pass
confidence: high

tools_used:
  - rg

proof_layers:
  semantic_identity: search-labeled definition evidence
  references: not used
  runtime: not run

files_opened:
  count: 0
  paths:

raw_dump_incidents:
  count: 0

policy_adherence: pass

final_answer:
  SampleFeatureViewModel definition location reported from search evidence.

BENCHMARK_DONE_rarb-test
"""


class RealAgentBenchmarkRejudgeTests(unittest.TestCase):
    def test_rejudge_rebuilds_stale_rows_from_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "rarb-test"
            run_dir.mkdir()
            tasks_path = root / "tasks.tsv"
            tasks_path.write_text(TASKS_TSV, encoding="utf-8")
            (run_dir / "task-packet.md").write_text("prompt", encoding="utf-8")
            (run_dir / "transcript.txt").write_text(TRANSCRIPT, encoding="utf-8")
            to_json_file(run_dir / "route-isolation.json", {"mode": "config", "hard_controls": ["codex_ignore_user_config"], "weak_controls": []})
            to_json_file(run_dir / "metrics.normalized.json", {"wall_seconds": 1.5, "completion_reason": "sentinel"})
            to_json_file(root / "run-manifest.json", {"dry_run": False, "live": True, "task_count": 1})
            append_jsonl(
                root / "runs.jsonl",
                {
                    "run_id": "rarb-test",
                    "agent": "codex",
                    "profile": "A-search-only",
                    "task_id": "sample_task",
                    "task_family": "known_kotlin_symbol_definition",
                    "repo": "sample",
                    "repo_path": str(root),
                    "run_dir": str(run_dir),
                    "correctness_status": "fail",
                    "policy_violations": ["stale"],
                    "token_source": "proxy",
                },
            )

            result = rejudge(benchmark_out=root, tasks=tasks_path, write=True, replace_runs=True)

            self.assertEqual(result["runs"], 1)
            row = json.loads((root / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["correctness_status"], "pass")
            self.assertEqual(row["policy_violations"], [])
            self.assertEqual(row["token_source"], "exact")
            self.assertEqual(row["exact_total_tokens"], 15)
            self.assertEqual(row["exact_uncached_total_tokens"], 11)
            self.assertEqual(row["exact_cached_input_tokens"], 4)
            self.assertEqual(row["exact_reasoning_output_tokens"], 2)
            self.assertEqual(row["exact_usage_event_count"], 1)
            self.assertEqual(row["observed_task_tools"][0], "rg")
            self.assertTrue(row["expected_proof_layer_seen"])
            self.assertTrue(list(root.glob("runs.*.bak.jsonl")))
            self.assertTrue((root / "metrics-summary.json").exists())

    def test_rejudge_uses_manifest_task_path_when_cli_tasks_not_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "rarb-test"
            run_dir.mkdir()
            tasks_path = root / "tasks.tsv"
            tasks_path.write_text(TASKS_TSV, encoding="utf-8")
            (run_dir / "task-packet.md").write_text("prompt", encoding="utf-8")
            (run_dir / "transcript.txt").write_text(TRANSCRIPT, encoding="utf-8")
            to_json_file(run_dir / "route-isolation.json", {"mode": "config", "hard_controls": ["codex_ignore_user_config"], "weak_controls": []})
            to_json_file(root / "run-manifest.json", {"dry_run": False, "live": True, "task_count": 1, "task_manifest": str(tasks_path)})
            append_jsonl(
                root / "runs.jsonl",
                {
                    "run_id": "rarb-test",
                    "agent": "codex",
                    "profile": "A-search-only",
                    "task_id": "sample_task",
                    "run_dir": str(run_dir),
                    "correctness_status": "fail",
                    "policy_violations": ["stale"],
                    "token_source": "proxy",
                },
            )

            result = rejudge(benchmark_out=root, tasks=None, write=False, replace_runs=False)

            self.assertEqual(result["task_manifest"], str(tasks_path.resolve()))
            self.assertEqual(result["changes"][0]["new_correctness_status"], "pass")
            self.assertEqual(result["runs_path"], "")
            self.assertTrue(str(result["planned_runs_path"]).endswith("runs.rejudged.jsonl"))

    def test_rejudge_preserves_output_budget_completion_from_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "rarb-test"
            run_dir.mkdir()
            tasks_path = root / "tasks.tsv"
            tasks_path.write_text(TASKS_TSV, encoding="utf-8")
            (run_dir / "task-packet.md").write_text("prompt", encoding="utf-8")
            (run_dir / "transcript.txt").write_text("large interrupted output", encoding="utf-8")
            to_json_file(run_dir / "route-isolation.json", {"mode": "config", "hard_controls": ["codex_ignore_user_config"], "weak_controls": []})
            to_json_file(run_dir / "metrics.normalized.json", {"wall_seconds": 1.5, "completion_reason": "missing_sentinel"})
            append_jsonl(run_dir / "telemetry.jsonl", {"event": "output_budget_exceeded", "observed_bytes": 20000})
            append_jsonl(run_dir / "telemetry.jsonl", {"event": "run_completed", "completion_reason": "output_budget_exceeded"})
            to_json_file(root / "run-manifest.json", {"dry_run": False, "live": True, "task_count": 1, "task_manifest": str(tasks_path)})
            append_jsonl(
                root / "runs.jsonl",
                {
                    "run_id": "rarb-test",
                    "agent": "codex",
                    "profile": "A-search-only",
                    "task_id": "sample_task",
                    "run_dir": str(run_dir),
                    "correctness_status": "fail",
                    "policy_violations": ["missing_done_sentinel"],
                    "token_source": "proxy",
                    "completion_reason": "missing_sentinel",
                },
            )

            result = rejudge(benchmark_out=root, tasks=None, write=True, replace_runs=True)

            self.assertEqual(result["runs"], 1)
            row = json.loads((root / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["completion_reason"], "output_budget_exceeded")
            metrics = json.loads((run_dir / "metrics.normalized.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["completion_reason"], "output_budget_exceeded")


if __name__ == "__main__":
    unittest.main()
