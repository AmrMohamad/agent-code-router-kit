from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "generated_semantic_mapping.py"
spec = importlib.util.spec_from_file_location("android_generated_semantic_mapping", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def row(**overrides: str) -> dict[str, str]:
    data = {
        "case_id": "apollo",
        "repo": "sample_b2b",
        "project": "SampleWholesaleAndroid",
        "flow_type": "apollo",
        "source_surface": "feature/src/main/graphql/query.graphql",
        "source_pattern": "query Foo",
        "generated_file": "feature/build/generated/source/apollo/FooQuery.kt",
        "generated_symbol": "FooQuery",
        "usage_file": "feature/src/main/java/Repo.kt",
        "usage_pattern": "FooQuery()",
        "semantic_symbol": "FooQuery",
        "semantic_context_file": "feature/src/main/java/Repo.kt",
        "expected_declaration_file": "feature/build/generated/source/apollo/FooQuery.kt",
        "expected_semantic_status": "pass",
        "build_task": ":feature:compileKotlin",
        "purpose": "test",
    }
    data.update(overrides)
    return data


class AndroidGeneratedSemanticMappingTests(unittest.TestCase):
    def test_manifest_validates_without_repos(self) -> None:
        rows = probe.load_cases(ROOT / "benchmarks" / "android" / "generated-semantic-mapping.sample-b2b.tsv")
        self.assertEqual(probe.validate(rows, {}, require_repos=False), [])

    def test_evaluate_case_separates_discovery_mapping_and_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            current = row()
            for rel, text in [
                (current["source_surface"], "query Foo { id }\n"),
                (current["generated_file"], "class FooQuery\n"),
                (current["usage_file"], "FooQuery()\n"),
            ]:
                path = repo / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            semantic = {
                "status": "pass",
                "stdout": f"{repo / current['expected_declaration_file']}:1",
                "stderr": "",
            }
            build = {"status": "not-run"}

            result = probe.evaluate_case(current, repo, semantic, build)

            self.assertTrue(result["discovery_pass"])
            self.assertTrue(result["mapping_pass"])
            self.assertEqual(result["semantic_classification"], "pass")
            self.assertEqual(result["classification"], "pass")

    def test_boundary_semantic_can_pass_with_warning_classification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            current = row(
                expected_semantic_status="boundary",
                expected_declaration_file="",
                generated_symbol="BuildConfig",
                semantic_symbol="BuildConfig",
            )
            for rel, text in [
                (current["source_surface"], "query Foo { id }\n"),
                (current["generated_file"], "class BuildConfig\n"),
                (current["usage_file"], "FooQuery()\n"),
            ]:
                path = repo / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            semantic = {"status": "no-result", "stdout": "No declaration found", "stderr": ""}
            build = {"status": "not-run"}

            result = probe.evaluate_case(current, repo, semantic, build)

            self.assertTrue(result["mapping_pass"])
            self.assertEqual(result["semantic_classification"], "boundary")
            self.assertEqual(result["classification"], "pass-with-boundary")

    def test_assertions_fail_when_mapping_threshold_is_not_met(self) -> None:
        rows = [
            {
                "case_id": "one",
                "flow_type": "apollo",
                "discovery_pass": True,
                "mapping_pass": False,
                "expected_semantic_status": "pass",
                "semantic_classification": "semantic-mismatch",
                "semantic_status": "no-result",
                "build_pass": True,
                "build_status": "not-run",
                "source_exists": True,
                "generated_exists": True,
                "usage_exists": True,
                "source_pattern_found": True,
                "generated_symbol_found": False,
                "usage_pattern_found": True,
            }
        ]

        payload = probe.build_assertions(rows, min_mapping_pass=1, min_semantic_pass=1)

        self.assertGreater(payload["summary"]["fail"], 0)


if __name__ == "__main__":
    unittest.main()
