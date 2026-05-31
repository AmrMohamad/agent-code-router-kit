from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "scripts" / "benchmarks" / "android" / "generate_report.py"
spec = importlib.util.spec_from_file_location("generate_android_report", REPORT_PATH)
assert spec and spec.loader
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class GenerateAndroidReportTests(unittest.TestCase):
    def test_latest_picks_lexically_last_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "summary-2026-05-24-010000.json").write_text("[]")
            expected = root / "summary-2026-05-24-020000.json"
            expected.write_text("[]")
            self.assertEqual(report.latest(root, "summary-*.json"), expected)

    def test_token_proxy_uses_four_char_ceil(self) -> None:
        self.assertEqual(report.token_proxy(0), 0)
        self.assertEqual(report.token_proxy(1), 1)
        self.assertEqual(report.token_proxy(4), 1)
        self.assertEqual(report.token_proxy(5), 2)

    def test_render_process_state_includes_counts_and_cleanup_commands(self) -> None:
        text = report.render_process_state(
            {
                "status": "stale-session-risk",
                "counts": {
                    "serena_mcp": 3,
                    "kotlin_lsp": 5,
                    "json_lsp": 2,
                    "java_jdtls": 1,
                },
                "guidance": {
                    "dry_run": "scripts/setup/repair-serena-android-sessions.sh --dry-run",
                    "explicit_kill": "scripts/setup/repair-serena-android-sessions.sh --kill",
                },
            }
        )
        self.assertIn("Serena / Android Process State", text)
        self.assertIn("stale-session-risk", text)
        self.assertIn("repair-serena-android-sessions.sh --dry-run", text)

    def test_render_direct_comparison_pairs_search_and_lsp_cases(self) -> None:
        text = report.render_direct_comparison(
            [
                {
                    "case_id": "known_symbol_main_activity_files",
                    "last_byte_count": 800,
                    "last_estimated_tokens": 200,
                    "median_wall_seconds": 0.02,
                }
            ],
            [
                {
                    "case_id": "serena_project_find_sample_retail_main_activity",
                    "last_estimated_tokens": 260,
                    "median_wall_seconds": 0.1,
                }
            ],
        )
        self.assertIn("Direct Search vs LSP Comparison", text)
        self.assertIn("Sample Retail MainActivity", text)
        self.assertIn("semantic Serena ProjectServer", text)

    def test_warning_breakdown_groups_by_check_and_message(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "assertions.json"
            path.write_text(
                json.dumps(
                    {
                        "summary": {"pass": 1, "warn": 2, "fail": 0},
                        "assertions": [
                            {
                                "status": "warn",
                                "check": "semantic_probe_not_ready",
                                "message": "actual=no-result",
                                "context": {"case_id": "case_a", "repo": "repo_a"},
                            },
                            {
                                "status": "warn",
                                "check": "semantic_probe_not_ready",
                                "message": "actual=no-result",
                                "context": {"case_id": "case_b", "repo": "repo_a"},
                            },
                            {
                                "status": "pass",
                                "check": "expected_status",
                                "message": "expected=pass actual=pass",
                                "context": {"case_id": "case_c", "repo": "repo_a"},
                            },
                        ],
                    }
                )
            )

            breakdown = report.assertion_warning_breakdown(path)
            self.assertEqual(len(breakdown), 1)
            self.assertEqual(breakdown[0]["count"], 2)
            self.assertEqual(breakdown[0]["cases"], ["case_a", "case_b"])

    def test_render_warning_breakdown_uses_layer_names(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "assertions.json"
            path.write_text(
                json.dumps(
                    {
                        "assertions": [
                            {
                                "status": "warn",
                                "check": "project_model_not_ready",
                                "message": "missing=sample_analytics_id",
                                "context": {"case_id": "project_model_sample_b2b", "repo": "sample_b2b_android"},
                            }
                        ]
                    }
                )
            )

            text = report.render_warning_breakdown([("Project model", path)])
            self.assertIn("Warning / Blocker Breakdown", text)
            self.assertIn("Project model", text)
            self.assertIn("project_model_not_ready", text)
            self.assertIn("project_model_sample_b2b", text)


if __name__ == "__main__":
    unittest.main()
