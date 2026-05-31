from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "process_scope_acceptance.py"
spec = importlib.util.spec_from_file_location("android_process_scope_acceptance", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidProcessScopeAcceptanceTests(unittest.TestCase):
    def process_summary(self) -> dict[str, object]:
        return {
            "status": "clean",
            "target_project_path": "/Users/me/sample_b2b",
            "expected_serena_mcp_count": 1,
            "target_serena_mcp_count": 1,
            "other_project_serena_mcp_count": 3,
            "unknown_serena_mcp_count": 0,
            "classification_counts": {"target_project": 1, "other_project": 3},
        }

    def test_template_only_does_not_accept_project_aware_strictness(self) -> None:
        data = probe.build_acceptance(
            None,
            self.process_summary(),
            accept_project_aware_strictness=False,
            accepted_by="",
            reason="",
        )

        self.assertEqual(data["status"], "template_only")
        self.assertFalse(data["accepted_project_aware_strictness"])
        self.assertEqual(data["assertions"]["fail"], 0)
        self.assertGreater(data["assertions"]["warn"], 0)

    def test_explicit_acceptance_requires_owner_and_reason(self) -> None:
        data = probe.build_acceptance(
            None,
            self.process_summary(),
            accept_project_aware_strictness=True,
            accepted_by="",
            reason="",
        )

        self.assertEqual(data["status"], "blocked")
        self.assertFalse(data["accepted_project_aware_strictness"])
        self.assertGreater(data["assertions"]["fail"], 0)

    def test_explicit_acceptance_passes_when_target_project_state_is_clean(self) -> None:
        data = probe.build_acceptance(
            None,
            self.process_summary(),
            accept_project_aware_strictness=True,
            accepted_by="amr",
            reason="Other Serena sessions belong to separate active projects; target-project ownership is clean.",
        )

        self.assertEqual(data["status"], "accepted")
        self.assertTrue(data["accepted_project_aware_strictness"])
        self.assertEqual(data["assertions"]["fail"], 0)
        self.assertEqual(data["target_serena_mcp_count"], 1)
        self.assertEqual(data["other_project_serena_mcp_count"], 3)

    def test_acceptance_blocks_when_target_project_has_duplicate_sessions(self) -> None:
        process = self.process_summary()
        process["target_serena_mcp_count"] = 2

        data = probe.build_acceptance(
            None,
            process,
            accept_project_aware_strictness=True,
            accepted_by="amr",
            reason="Testing duplicate target session.",
        )

        self.assertEqual(data["status"], "blocked")
        self.assertGreater(data["assertions"]["fail"], 0)


if __name__ == "__main__":
    unittest.main()
