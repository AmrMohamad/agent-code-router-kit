from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "serena_mcp_lifecycle_probe.py"
spec = importlib.util.spec_from_file_location("android_serena_mcp_lifecycle_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidSerenaMcpLifecycleProbeTests(unittest.TestCase):
    def test_manifest_validates_without_repo(self) -> None:
        rows = probe.load_cases(ROOT / "benchmarks" / "android" / "serena-mcp-lifecycle.sample-b2b.tsv")
        self.assertEqual(probe.validate_cases(rows), [])

    def test_parse_sse_jsons(self) -> None:
        body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
        self.assertEqual(probe.parse_sse_jsons(body)[0]["result"], {"ok": True})

    def test_make_find_symbol_tool_call_uses_relative_symbol(self) -> None:
        row = {
            "semantic_tool": "find_symbol",
            "semantic_name_path": "SampleFeatureViewModel",
            "semantic_relative_path": "feature-notifications/src/main/java/com/example/sample/features/notifications/SampleFeatureViewModel.kt",
        }
        payload = probe.make_find_symbol_tool_call(row, request_id=9)
        self.assertEqual(payload["id"], 9)
        self.assertEqual(payload["params"]["name"], "find_symbol")
        self.assertEqual(payload["params"]["arguments"]["name_path_pattern"], "SampleFeatureViewModel")
        self.assertFalse(payload["params"]["arguments"]["include_body"])

    def test_process_delta_compares_counts(self) -> None:
        before = {"counts": {"serena_mcp": 3, "kotlin_lsp": 0}}
        after = {"counts": {"serena_mcp": 3, "kotlin_lsp": 1}}
        self.assertEqual(probe.process_delta(before, after), {"kotlin_lsp": 1, "serena_mcp": 0})

    def test_build_assertions_accepts_clean_pass_rows(self) -> None:
        rows = [
            {
                "case_id": "stdio",
                "transport": "stdio",
                "expected_status": "pass",
                "status": "pass",
                "checks": {
                    "initialize": True,
                    "tools_list": True,
                    "semantic_tool_call": True,
                    "transport_error_absent": True,
                },
            },
            {
                "case_id": "http",
                "transport": "streamable-http",
                "expected_status": "pass",
                "status": "pass",
                "checks": {
                    "initialize": True,
                    "tools_list": True,
                    "semantic_tool_call": True,
                    "transport_error_absent": True,
                },
            },
        ]
        before = {"counts": {"serena_mcp": 2, "kotlin_lsp": 0}}
        after = {"counts": {"serena_mcp": 2, "kotlin_lsp": 0}}
        payload = probe.build_assertions(rows, before, after)
        self.assertEqual(payload["summary"]["fail"], 0)

    def test_transport_performance_marks_fastest_as_candidate_only(self) -> None:
        rows = [
            {"transport": "stdio", "status": "pass", "wall_seconds": 20.0},
            {"transport": "stdio", "status": "pass", "wall_seconds": 10.0},
            {"transport": "streamable-http", "status": "pass", "wall_seconds": 8.0},
            {"transport": "streamable-http", "status": "pass", "wall_seconds": 9.0},
        ]

        summary = probe.transport_performance(rows)

        self.assertEqual(summary["candidate_transport"], "streamable-http")
        self.assertEqual(summary["recommendation_status"], "lifecycle_candidate_only")
        self.assertEqual(summary["transports"]["stdio"]["pass_count"], 2)


if __name__ == "__main__":
    unittest.main()
