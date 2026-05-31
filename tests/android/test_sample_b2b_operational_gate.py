from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "operational_gate.py"
spec = importlib.util.spec_from_file_location("android_sample_b2b_operational_gate", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidOperationalGateTests(unittest.TestCase):
    def test_manifest_validation_requires_expected_gates(self) -> None:
        rows = [
            {
                "gate_id": "process_state",
                "category": "process",
                "tool": "scan",
                "expected_status": "pass",
                "required": "yes",
                "purpose": "test",
            }
        ]
        errors = probe.validate_manifest(rows)
        self.assertTrue(any("manifest missing expected gates" in error for error in errors))

    def test_repo_manifest_has_all_expected_gates(self) -> None:
        rows = probe.load_manifest(ROOT / "benchmarks" / "android" / "operational-gates.sample-b2b.tsv")
        self.assertEqual(probe.validate_manifest(rows), [])

    def test_variant_suffix_and_package_defaults(self) -> None:
        self.assertEqual(probe.variant_suffix("stagingDebug"), "StagingDebug")
        self.assertEqual(probe.package_for_variant("stagingDebug"), "com.example.sampleb2b.staging")
        self.assertEqual(probe.package_for_variant("productionDebug"), "com.example.sampleb2b")

    def test_process_state_gate_uses_project_aware_summary(self) -> None:
        original_table = probe.process_probe.process_table
        original_cwd = probe.process_probe.process_cwd
        try:
            probe.process_probe.process_table = lambda: [
                {
                    "kind": "serena_mcp",
                    "pid": 1,
                    "command": "serena start-mcp-server --project /repo --context=codex",
                }
            ]
            probe.process_probe.process_cwd = lambda pid: "/repo"
            result = probe.process_state_gate(False, Path("/repo"), 1, False, False)
            self.assertEqual(result.status, "pass")
            self.assertEqual(result.details["classification_counts"]["target_project"], 1)
        finally:
            probe.process_probe.process_table = original_table
            probe.process_probe.process_cwd = original_cwd

    def test_write_outputs_counts_warning_without_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            results = [
                probe.make_gate("a", "cat", "tool", "pass", "ok"),
                probe.make_gate("b", "cat", "tool", "warn", "risk"),
            ]
            manifest = [
                {
                    "gate_id": "a",
                    "category": "cat",
                    "tool": "tool",
                    "expected_status": "pass",
                    "required": "yes",
                    "purpose": "test",
                },
                {
                    "gate_id": "b",
                    "category": "cat",
                    "tool": "tool",
                    "expected_status": "warn",
                    "required": "yes",
                    "purpose": "test",
                },
            ]
            _, summary_path, counts = probe.write_outputs(output, results, manifest, enforce=False)
            self.assertEqual(counts, {"pass": 1, "warn": 1, "fail": 0})
            self.assertTrue(summary_path.exists())

    def test_manifest_policy_fails_missing_required_gate(self) -> None:
        adjusted, assertions = probe.apply_manifest_policy(
            [],
            [
                {
                    "gate_id": "required_gate",
                    "category": "cat",
                    "tool": "tool",
                    "expected_status": "pass",
                    "required": "yes",
                    "purpose": "test",
                }
            ],
        )
        self.assertEqual(adjusted[0].level, "fail")
        self.assertEqual(assertions[0]["status"], "fail")

    def test_expected_warn_accepts_cleaner_pass(self) -> None:
        self.assertTrue(probe.expected_status_ok("warn", "pass", "pass"))
        self.assertTrue(probe.expected_status_ok("probe", "disagreement", "warn"))
        self.assertFalse(probe.expected_status_ok("pass", "warn", "warn"))

    def test_launch_smoke_can_use_visible_activity_when_process_is_hidden_by_permission_ui(self) -> None:
        text = "Task{1 A=10228:com.example.sampleb2b.staging visible=true}"
        self.assertTrue(probe.launch_activity_visible("com.example.sampleb2b.staging", text))
        self.assertFalse(probe.launch_activity_visible("com.other", text))


if __name__ == "__main__":
    unittest.main()
