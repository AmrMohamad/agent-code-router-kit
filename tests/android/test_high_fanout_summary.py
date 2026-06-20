from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "high_fanout_summary.py"
spec = importlib.util.spec_from_file_location("android_high_fanout_summary", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidHighFanoutSummaryTests(unittest.TestCase):
    def test_default_patterns_cover_common_android_broad_names(self) -> None:
        self.assertIn("Mapper", probe.DEFAULT_PATTERNS)
        self.assertIn("Service", probe.DEFAULT_PATTERNS)
        self.assertIn("Module", probe.DEFAULT_PATTERNS)

    def test_parse_count_output_uses_last_colon(self) -> None:
        rows = probe.parse_count_output("src/main/Foo.kt:3\nweird:path/Bar.kt:7\n")
        self.assertEqual(rows, [("src/main/Foo.kt", 3), ("weird:path/Bar.kt", 7)])

    def test_build_assertions_warns_for_high_fanout_without_failing(self) -> None:
        payload = {
            "patterns": [
                {
                    "pattern": "UseCase",
                    "status": "pass",
                    "file_count": 30,
                    "total_matches": 60,
                }
            ]
        }
        assertions = probe.build_assertions(payload)
        self.assertEqual(assertions["summary"]["fail"], 0)
        self.assertEqual(assertions["summary"]["warn"], 1)
        self.assertTrue(any(item["check"] == "summary_mode" for item in assertions["assertions"]))

    def test_summarize_pattern_returns_counts_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            source = repo / "src" / "main" / "Foo.kt"
            source.parent.mkdir(parents=True)
            source.write_text("class FooUseCase\nclass OtherUseCase\n")

            summary = probe.summarize_pattern(repo, "UseCase", ["*.kt"], top_limit=5, timeout=5)

            self.assertEqual(summary.status, "pass")
            self.assertEqual(summary.total_matches, 2)
            self.assertEqual(summary.file_count, 1)
            self.assertEqual(summary.top_files[0]["matches"], 2)
            self.assertEqual(summary.top_modules[0], {"key": "src", "matches": 2})
            self.assertEqual(summary.budget["status"], "pass")
            self.assertIn("--no-config", summary.command)
            self.assertEqual(summary.command[-1], ".")
            self.assertIn("read focused ranges only", summary.next_actions)

    def test_build_payload_includes_grouped_counts_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            source = repo / "feature" / "src" / "main" / "java" / "com" / "app" / "FooUseCase.kt"
            source.parent.mkdir(parents=True)
            source.write_text("class FooUseCase\n")

            payload = probe.build_payload(repo, ["UseCase"], ["*.kt"], top_limit=5, timeout=5)
            item = payload["patterns"][0]

            self.assertEqual(item["top_modules"][0], {"key": "feature", "matches": 1})
            self.assertEqual(item["top_packages"][0], {"key": "com.app", "matches": 1})
            self.assertEqual(item["output_budget"]["status"], "pass")
            self.assertEqual(item["mode"], "summary_only")
            self.assertIn("next_actions", item)


if __name__ == "__main__":
    unittest.main()
