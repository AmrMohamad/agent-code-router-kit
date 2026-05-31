from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "agent_behavior_gate.py"
spec = importlib.util.spec_from_file_location("android_agent_behavior_gate", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidAgentBehaviorGateTests(unittest.TestCase):
    def test_manifest_validates(self) -> None:
        rows = probe.load_cases(ROOT / "benchmarks" / "android" / "agent-behavior.sample-b2b.tsv")
        self.assertEqual(probe.validate_cases(rows), [])

    def test_known_symbol_routes_to_serena(self) -> None:
        result = probe.classify_prompt("Find the definition for `SampleFeatureViewModel`.")
        self.assertEqual(result["first_tool"], "serena_kotlin_lsp")
        self.assertEqual(result["intent"], "known_symbol")

    def test_reference_disagreement_routes_to_studio(self) -> None:
        result = probe.classify_prompt("Serena references returned empty but Studio usages worked for SampleFeatureViewModel.")
        self.assertEqual(result["first_tool"], "android_studio_usages")
        self.assertEqual(result["intent"], "semantic_disagreement")

    def test_high_fanout_routes_to_summary(self) -> None:
        result = probe.classify_prompt("Find all usages of UseCase across the repo.")
        self.assertEqual(result["first_tool"], "grouped_summary")
        self.assertEqual(result["summary_mode"], "grouped_counts")

    def test_graphql_routes_to_graphql_tooling(self) -> None:
        result = probe.classify_prompt("Validate the GraphQL operation for checkout.")
        self.assertEqual(result["first_tool"], "graphql_workbench_rg_fd")

    def test_graphql_fragment_routes_to_graphql_tooling(self) -> None:
        result = probe.classify_prompt("Validate the GraphQL fragment for product details.")
        self.assertEqual(result["first_tool"], "graphql_workbench_rg_fd")
        self.assertEqual(result["intent"], "graphql_surface")

    def test_json_structure_routes_to_json_lsp(self) -> None:
        result = probe.classify_prompt("Validate JSON diagnostics and structure for google-services.json.")
        self.assertEqual(result["first_tool"], "serena_json_lsp")
        self.assertEqual(result["intent"], "json_structure")

    def test_json_literal_key_stays_discovery_first(self) -> None:
        result = probe.classify_prompt("Find the literal string key google_app_id inside JSON or resources.")
        self.assertEqual(result["first_tool"], "rg_fd")
        self.assertEqual(result["intent"], "literal_resource")

    def test_known_implementation_routes_to_serena(self) -> None:
        result = probe.classify_prompt("Find implementations of the known Kotlin interface GraphQLClient.")
        self.assertEqual(result["first_tool"], "serena_kotlin_lsp")
        self.assertEqual(result["proof_layer"], "semantic_implementation")

    def test_build_routes_to_runtime_tools(self) -> None:
        result = probe.classify_prompt("Install stagingDebug on emulator and launch the package.")
        self.assertEqual(result["first_tool"], "gradle_android_runtime")
        self.assertEqual(result["proof_layer"], "runtime_proof")

    def test_assertions_detect_wrong_first_tool(self) -> None:
        rows = [
            {
                "case_id": "bad",
                "expected_intent": "known_symbol",
                "actual_intent": "known_symbol",
                "expected_first_tool": "serena_kotlin_lsp",
                "actual_first_tool": "rg_fd",
                "expected_proof_layer": "semantic_identity",
                "actual_proof_layer": "semantic_identity",
                "expected_summary_mode": "focused_symbol",
                "actual_summary_mode": "focused_symbol",
                "forbidden_first_tools_json": "[]",
            }
        ]
        assertions = probe.build_assertions(rows)
        self.assertGreater(assertions["summary"]["fail"], 0)

    def test_load_observed_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "observed.json"
            path.write_text(
                json.dumps(
                    {
                        "observations": [
                            {
                                "case_id": "known_symbol_definition",
                                "observed_first_tool": "serena_kotlin_lsp",
                                "observed_notes": "live smoke",
                            }
                        ]
                    }
                )
            )
            observed = probe.load_observed_log(path)
        self.assertEqual(observed["known_symbol_definition"]["observed_first_tool"], "serena_kotlin_lsp")

    def test_observed_first_tool_assertion_scores_live_evidence(self) -> None:
        rows = [
            {
                "case_id": "live",
                "expected_intent": "known_symbol",
                "actual_intent": "known_symbol",
                "expected_first_tool": "serena_kotlin_lsp",
                "actual_first_tool": "serena_kotlin_lsp",
                "expected_proof_layer": "semantic_identity",
                "actual_proof_layer": "semantic_identity",
                "expected_summary_mode": "focused_symbol",
                "actual_summary_mode": "focused_symbol",
                "forbidden_first_tools_json": "[]",
                "observed_first_tool": "rg_fd",
            }
        ]
        assertions = probe.build_assertions(rows)
        self.assertGreater(assertions["summary"]["fail"], 0)

    def test_require_observed_fails_missing_live_evidence(self) -> None:
        rows = [
            {
                "case_id": "missing",
                "expected_intent": "known_symbol",
                "actual_intent": "known_symbol",
                "expected_first_tool": "serena_kotlin_lsp",
                "actual_first_tool": "serena_kotlin_lsp",
                "expected_proof_layer": "semantic_identity",
                "actual_proof_layer": "semantic_identity",
                "expected_summary_mode": "focused_symbol",
                "actual_summary_mode": "focused_symbol",
                "forbidden_first_tools_json": "[]",
                "observed_first_tool": "",
            }
        ]
        assertions = probe.build_assertions(rows, require_observed=True)
        self.assertGreater(assertions["summary"]["fail"], 0)

    def test_summary_records_minimum_observed_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / "out"
            args = type(
                "Args",
                (),
                {
                    "observed_log": "",
                    "require_observed": False,
                    "output": str(output),
                    "enforce_assertions": True,
                    "min_observed_cases_for_readiness": 12,
                },
            )()
            cases = [
                {
                    "case_id": "known_symbol_definition",
                    "repo_scope": "sample_b2b",
                    "task_prompt": "Find the definition and owner module for the known Kotlin symbol `SampleFeatureViewModel`.",
                    "expected_intent": "known_symbol",
                    "expected_first_tool": "serena_kotlin_lsp",
                    "expected_proof_layer": "semantic_identity",
                    "expected_summary_mode": "focused_symbol",
                    "forbidden_first_tools_json": "[]",
                    "purpose": "threshold smoke",
                }
            ]

            self.assertEqual(probe.run(args, cases), 0)
            summary_path = next(output.glob("android-agent-behavior-summary-*.json"))
            summary = json.loads(summary_path.read_text())
            self.assertEqual(summary["minimum_observed_cases_for_readiness"], 12)


if __name__ == "__main__":
    unittest.main()
