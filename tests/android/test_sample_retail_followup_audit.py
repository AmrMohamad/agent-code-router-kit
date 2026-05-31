from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "sample_retail_followup_audit.py"
spec = importlib.util.spec_from_file_location("android_sample_retail_followup_audit", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidSampleRetailFollowupAuditTests(unittest.TestCase):
    def test_sample_retail_serena_stats_counts_boundaries(self) -> None:
        rows = [
            {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
            {"repo": "sample_retail_android", "tool_name": "find_referencing_symbols", "statuses": ["empty"]},
            {"repo": "sample_retail_android", "tool_name": "get_diagnostics_for_file", "statuses": ["empty"]},
            {"repo": "sample_b2b_android", "tool_name": "find_symbol", "statuses": ["pass"]},
        ]
        self.assertEqual(
            probe.sample_retail_serena_stats(rows),
            {
                "find_symbol_pass": 1,
                "overview_pass": 0,
                "references_empty": 1,
                "diagnostics_empty": 1,
                "implementation_boundary": 0,
            },
        )

    def test_project_model_pass_detects_sample_retail_pass(self) -> None:
        summary = [{"repo": "sample_retail_android", "statuses": ["pass"]}]
        self.assertTrue(probe.project_model_pass(summary))

    def test_build_assertions_allows_named_boundaries(self) -> None:
        payload = {
            "project_model_summary": [{"repo": "sample_retail_android", "statuses": ["pass"]}],
            "generated_assertions": {"summary": {"pass": 6, "warn": 0, "fail": 0}},
            "high_fanout_assertions": {"summary": {"pass": 5, "warn": 5, "fail": 0}},
            "serena_summary": [
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_referencing_symbols", "statuses": ["empty"]},
                {"repo": "sample_retail_android", "tool_name": "get_diagnostics_for_file", "statuses": ["empty"]},
            ],
            "process_state_summary": {"counts": {"serena_mcp": 2, "kotlin_lsp": 0}},
        }
        result = probe.build_assertions(payload)
        self.assertEqual(result["summary"], {"pass": 4, "warn": 6, "fail": 0})

    def test_optional_studio_and_runtime_can_promote_sample_retail_equivalence(self) -> None:
        payload = {
            "project_model_summary": [{"repo": "sample_retail_android", "statuses": ["pass"]}],
            "generated_assertions": {"summary": {"pass": 6, "warn": 0, "fail": 0}},
            "high_fanout_assertions": {"summary": {"pass": 5, "warn": 5, "fail": 0}},
            "serena_summary": [
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
                {"repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"]},
            ],
            "process_state_summary": {"counts": {"serena_mcp": 1, "kotlin_lsp": 0}},
            "sample_retail_studio_matrix_summary": {
                "trusted_studio_layer": True,
                "case_count": 12,
                "declaration_pass_count": 10,
                "usage_pass_count": 9,
            },
            "sample_retail_operational_summary": {
                "overall_status": "pass",
                "summary": {"pass": 8, "warn": 0, "fail": 0},
                "gates": [
                    {"gate_id": "assemble_debug", "level": "pass"},
                    {"gate_id": "install_debug", "level": "pass"},
                    {"gate_id": "launch_smoke", "level": "pass"},
                ],
            },
        }
        result = probe.build_assertions(payload)
        checks = {item["check"]: item["status"] for item in result["assertions"]}
        self.assertEqual(checks["sample_retail_studio_symbol_matrix"], "pass")
        self.assertEqual(checks["sample_retail_build_install_launch_smoke"], "pass")
        self.assertEqual(checks["sample_retail_equivalent_operational_gate"], "pass")

    def test_project_aware_clean_process_state_ignores_other_project_sessions(self) -> None:
        summary = {
            "status": "clean",
            "counts": {"serena_mcp": 7, "kotlin_lsp": 0},
            "target_serena_mcp_count": 0,
            "other_project_serena_mcp_count": 7,
            "unknown_serena_mcp_count": 0,
        }
        self.assertFalse(probe.process_state_has_stale_risk(summary))


if __name__ == "__main__":
    unittest.main()
