from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "live_evidence_template.py"
spec = importlib.util.spec_from_file_location("android_live_evidence_template", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidLiveEvidenceTemplateTests(unittest.TestCase):
    def test_behavior_template_selects_diverse_first_tools(self) -> None:
        cases = [
            {
                "case_id": "a",
                "task_prompt": "task a",
                "expected_first_tool": "serena_kotlin_lsp",
            },
            {
                "case_id": "b",
                "task_prompt": "task b",
                "expected_first_tool": "rg_fd",
            },
            {
                "case_id": "c",
                "task_prompt": "task c",
                "expected_first_tool": "serena_kotlin_lsp",
            },
        ]

        data = probe.behavior_template(cases, 2)

        tools = {row["expected_first_tool"] for row in data["observations"]}
        self.assertEqual(tools, {"serena_kotlin_lsp", "rg_fd"})
        self.assertEqual(data["minimum_observations_for_readiness"], 2)
        self.assertEqual(data["observations"][0]["observed_first_tool"], "")

    def test_transport_template_uses_candidate_without_marking_pass(self) -> None:
        data = probe.transport_template(3, "streamable-http")

        self.assertEqual(data["candidate_transport"], "streamable-http")
        self.assertEqual(len(data["observations"]), 3)
        self.assertTrue(all(row["transport"] == "streamable-http" for row in data["observations"]))
        self.assertTrue(all(row["status"] == "" for row in data["observations"]))


if __name__ == "__main__":
    unittest.main()
