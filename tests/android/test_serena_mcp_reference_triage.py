from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "serena_mcp_reference_triage.py"
spec = importlib.util.spec_from_file_location("android_serena_mcp_reference_triage", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidSerenaMcpReferenceTriageTests(unittest.TestCase):
    def test_manifest_validates_without_repo(self) -> None:
        rows = probe.load_cases(ROOT / "benchmarks" / "android" / "serena-mcp-reference-triage.sample-b2b.tsv")
        self.assertEqual(probe.validate_cases(rows), [])

    def test_tool_text_extracts_mcp_content(self) -> None:
        response = {"result": {"content": [{"type": "text", "text": "[]"}], "isError": False}}
        self.assertEqual(probe.tool_text(response), "[]")

    def test_response_status_maps_timeout(self) -> None:
        self.assertEqual(probe.response_status({"error": {"message": "timed out waiting"}}), "timeout")

    def test_response_status_detects_tool_error_payload(self) -> None:
        response = {
            "result": {
                "content": [{"text": "Error executing tool: ValueError - No symbol matching 'Foo' found"}],
                "isError": False,
                "structuredContent": {"result": "Error executing tool: ValueError - No symbol matching 'Foo' found"},
            }
        }
        self.assertEqual(probe.response_status(response), "error")

    def test_response_status_detects_mcp_is_error_result(self) -> None:
        response = {"result": {"content": [{"text": "validation error"}], "isError": True}}
        self.assertEqual(probe.response_status(response), "error")

    def test_classify_fixed_when_paths_overlap(self) -> None:
        find_response = {"result": {"content": [{"text": "symbol"}], "isError": False}}
        reference_response = {"result": {"content": [{"text": "app/Foo.kt"}], "isError": False}}
        studio_result = {"status": "pass"}
        self.assertEqual(
            probe.classify_case(find_response, reference_response, studio_result, {"app/Foo.kt"}, {"app/Foo.kt"}),
            "fixed",
        )

    def test_build_assertions_allows_probe_disagreement(self) -> None:
        rows = [
            {
                "case_id": "case",
                "transport": "stdio",
                "symbol_label": "Foo",
                "classification": "serena-reference-empty-boundary",
                "expected_classification": "probe",
                "find_status": "pass",
                "reference_status": "pass",
                "studio_status": "pass",
                "expected_studio_files_missing": [],
                "overlap_paths": [],
            }
        ]
        transports = [{"transport": "stdio", "initialize": {"result": {}}, "tool_count": 22, "stderr": ""}]
        before = {"counts": {"serena_mcp": 1, "kotlin_lsp": 0}}
        after = {"counts": {"serena_mcp": 1, "kotlin_lsp": 0}}
        assertions = probe.build_assertions(rows, transports, before, after, max_serena_growth=0)
        self.assertEqual(assertions["summary"]["fail"], 0)
        self.assertGreater(assertions["summary"]["warn"], 0)

    def test_classify_empty_serena_references_as_named_boundary(self) -> None:
        find_response = {"result": {"content": [{"text": "symbol"}], "isError": False}}
        reference_response = {"result": {"content": [{"text": "{}"}], "isError": False}}
        studio_result = {"status": "pass"}
        self.assertEqual(
            probe.classify_case(find_response, reference_response, studio_result, set(), {"app/Foo.kt"}),
            "serena-reference-empty-boundary",
        )

    def test_classify_missing_relative_path_as_query_shape_issue(self) -> None:
        find_response = {"result": {"content": [{"text": "symbol"}], "isError": False}}
        reference_response = {"result": {"content": [{"text": "relative_path Field required"}], "isError": True}}
        studio_result = {"status": "pass"}
        self.assertEqual(
            probe.classify_case(find_response, reference_response, studio_result, set(), {"app/Foo.kt"}),
            "query-shape issue",
        )


if __name__ == "__main__":
    unittest.main()
