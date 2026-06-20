from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmarks.export_sanitized_live_pilot import export_sanitized_live_pilot, main
from scripts.lib.agent_session import append_jsonl, to_json_file


PRIVATE_REPO = "/Users/example/Developer/private-android"


def write_live_pilot(root: Path) -> None:
    run_dir = root / "rarb-run-a"
    run_dir.mkdir(parents=True)
    to_json_file(
        root / "run-manifest.json",
        {
            "created_at": "2026-06-02T00:00:00Z",
            "agents": ["codex"],
            "arms": ["A-search-only"],
            "task_ids": ["task"],
            "task_count": 1,
            "repeats": 1,
            "dry_run": False,
            "live": True,
            "fresh_session_per_run": True,
            "order_randomized": True,
            "seed": 123,
            "repo_map": {"sample": PRIVATE_REPO},
            "repo_states": {
                "sample": {
                    "path": PRIVATE_REPO,
                    "git_root": PRIVATE_REPO,
                    "commit": "0123456789abcdef0123456789abcdef01234567",
                    "dirty": False,
                }
            },
            "require_clean_serena_process_state": True,
        },
    )
    append_jsonl(
        root / "runs.jsonl",
        {
            "run_id": "rarb-run-a",
            "agent": "codex",
            "profile": "A-search-only",
            "task_id": "task",
            "task_family": "known_kotlin_symbol_definition",
            "repo": "sample",
            "repo_path": PRIVATE_REPO,
            "run_dir": str(run_dir),
            "completion_reason": "sentinel",
            "correctness_status": "pass",
            "policy_adherence": "pass",
            "policy_violations": [],
            "expected_proof_layer_seen": True,
            "token_source": "exact",
            "exact_total_tokens": 100,
            "exact_uncached_total_tokens": 80,
            "model_visible_proxy_tokens": 50,
            "tool_evidence_source": "observed",
            "observed_task_tools": ["rg"],
            "route_hard_controls": ["codex_ignore_user_config"],
            "route_weak_controls": [],
            "dynamic_target_symbol": "SampleViewModel",
        },
    )
    for name, payload in {
        "metrics-summary.json": {"repo_path": PRIVATE_REPO, "runs": 1},
        "route-comparisons.json": [{"agent": "codex", "repo_path": PRIVATE_REPO}],
        "route-claim-readiness.json": {"rows": []},
        "terminal-control-summary.json": {"rows": [{"run_id": "rarb-run-a", "events": ["process_started"]}]},
        "route-policy-summary.json": {"rows": [{"run_id": "rarb-run-a", "blocked_tool_violations": []}]},
    }.items():
        to_json_file(root / name, payload)
    (root / "token-savings-report.md").write_text(f"Repo: {PRIVATE_REPO}\n", encoding="utf-8")
    for name, text in {
        "metrics.normalized.json": json.dumps({"token_source": "exact", "repo_path": PRIVATE_REPO}),
        "judge.json": json.dumps({"correctness_status": "pass", "path": PRIVATE_REPO}),
        "route-isolation.json": json.dumps({"env": {"RARB_ALLOWED_TOOLS": "rg"}, "cwd": PRIVATE_REPO}),
        "telemetry.jsonl": json.dumps({"event": "process_started", "cwd": PRIVATE_REPO}) + "\n",
        "launch-plan.json": json.dumps({"terminal_mode": "pty", "cwd": PRIVATE_REPO}),
        "transcript.txt": "raw transcript with private path",
        "agent_final_answer.md": "final answer with private path",
        "task-packet.md": "prompt with private path",
    }.items():
        (run_dir / name).write_text(text, encoding="utf-8")


class SanitizedLivePilotExportTests(unittest.TestCase):
    def test_export_sanitizes_paths_and_omits_raw_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            write_live_pilot(root)
            out = Path(tmp) / "export"

            summary = export_sanitized_live_pilot(benchmark_out=root, out=out, title="Codex pilot")

            self.assertEqual(summary["status"], "pass")
            self.assertTrue((out / "run-manifest.sanitized.json").exists())
            self.assertTrue((out / "runs.sanitized.jsonl").exists())
            self.assertTrue((out / "runs" / "rarb-run-a" / "metrics.normalized.json").exists())
            self.assertFalse((out / "runs" / "rarb-run-a" / "transcript.txt").exists())
            self.assertFalse((out / "runs" / "rarb-run-a" / "agent_final_answer.md").exists())
            exported_text = "\n".join(path.read_text(encoding="utf-8") for path in out.rglob("*") if path.is_file())
            self.assertNotIn(PRIVATE_REPO, exported_text)
            self.assertIn("<repo:sample>", exported_text)
            row = json.loads((out / "runs.sanitized.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["exact_total_tokens"], 100)
            self.assertNotIn("repo_path", row)

    def test_cli_writes_export_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            write_live_pilot(root)
            out = Path(tmp) / "export"

            code = main(["--benchmark-out", str(root), "--out", str(out)])

            self.assertEqual(code, 0)
            self.assertTrue((out / "export-summary.json").exists())


if __name__ == "__main__":
    unittest.main()
