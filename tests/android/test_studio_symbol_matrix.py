from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "studio_symbol_matrix.py"
spec = importlib.util.spec_from_file_location("android_studio_symbol_matrix", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


def base_row(**overrides: str) -> dict[str, str]:
    row = {
        "case_id": "sample",
        "repo": "sample_b2b",
        "project": "SampleWholesaleAndroid",
        "category": "viewmodel-class",
        "symbol": "FooViewModel",
        "context_file": "app/FooFragment.kt",
        "expected_declaration_file": "app/FooViewModel.kt",
        "expected_usage_files_json": '["app/FooFragment.kt"]',
        "expected_min_usages": "1",
        "expected_kind": "class",
        "expected_status": "pass",
        "no_result_classification": "",
        "purpose": "test",
    }
    row.update(overrides)
    return row


class AndroidStudioSymbolMatrixTests(unittest.TestCase):
    def test_manifest_validates_without_repos(self) -> None:
        rows = probe.load_cases(ROOT / "benchmarks" / "android" / "studio-symbol-matrix.sample-b2b.tsv")
        self.assertEqual(probe.validate(rows, {}, require_repos=False), [])

    def test_sample_retail_manifest_validates_without_repos(self) -> None:
        rows = probe.load_cases(ROOT / "benchmarks" / "android" / "studio-symbol-matrix.sample-retail.tsv")
        self.assertEqual(probe.validate(rows, {}, require_repos=False), [])

    def test_normalize_studio_status_treats_error_stdout_as_error(self) -> None:
        self.assertEqual(probe.normalize_studio_status(0, "Error: no project\n", "", False), "error")

    def test_extract_repo_paths_handles_absolute_relative_and_xml(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            kt = Path("app/src/main/Foo.kt")
            xml = Path("app/src/main/AndroidManifest.xml")
            (repo / kt).parent.mkdir(parents=True)
            (repo / kt).write_text("class Foo\n")
            (repo / xml).write_text("<manifest />\n")
            text = f"{repo / kt}:10\napp/src/main/AndroidManifest.xml:3"
            self.assertEqual(probe.extract_repo_paths(text, repo), {str(kt), str(xml)})

    def test_evaluate_case_passes_when_expected_declaration_and_usages_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            for rel in ["app/FooViewModel.kt", "app/FooFragment.kt"]:
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text("class X\n")
            row = base_row()
            declaration = {"status": "pass", "stdout": f"{repo / 'app/FooViewModel.kt'}:1", "stderr": ""}
            usages = {"status": "pass", "stdout": "app/FooFragment.kt:2", "stderr": ""}
            result = probe.evaluate_case(row, repo, declaration, usages)
            self.assertEqual(result["classification"], "pass")
            self.assertTrue(result["declaration_pass"])
            self.assertTrue(result["usages_pass"])

    def test_build_assertions_fails_thresholds_when_too_few_pass(self) -> None:
        rows = [
            {
                "case_id": "sample",
                "symbol": "Foo",
                "category": "viewmodel",
                "expected_status": "pass",
                "classification": "declaration-only",
                "declaration_status": "pass",
                "usages_status": "no-result",
                "declaration_pass": True,
                "usages_pass": False,
                "no_result_classification": "",
                "expected_usage_files_missing": ["app/FooFragment.kt"],
            }
        ]
        payload = probe.build_assertions(rows, declaration_threshold=2, usage_threshold=1)
        self.assertGreater(payload["summary"]["fail"], 0)

    def test_classified_boundary_warns_but_does_not_fail_expected_boundary(self) -> None:
        rows = [
            {
                "case_id": "generated_boundary",
                "symbol": "BuildConfig",
                "category": "generated",
                "expected_status": "boundary",
                "classification": "no-result-classified",
                "declaration_status": "no-result",
                "usages_status": "no-result",
                "declaration_pass": False,
                "usages_pass": False,
                "no_result_classification": "generated-source boundary",
                "expected_usage_files_missing": [],
            }
        ]
        payload = probe.build_assertions(rows, declaration_threshold=0, usage_threshold=0)
        self.assertEqual(payload["summary"]["fail"], 0)
        self.assertGreater(payload["summary"]["warn"], 0)


if __name__ == "__main__":
    unittest.main()
