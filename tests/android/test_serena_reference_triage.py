from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "serena_reference_triage.py"
spec = importlib.util.spec_from_file_location("android_serena_reference_triage", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidSerenaReferenceTriageTests(unittest.TestCase):
    def test_manifest_validates(self) -> None:
        rows = probe.load_cases(ROOT / "benchmarks" / "android" / "serena-reference-triage.sample-b2b.tsv")
        self.assertEqual(probe.validate(rows, {}, require_repos=False), [])

    def test_extract_paths_finds_absolute_and_relative_kt_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            rel = Path("app/src/main/java/Foo.kt")
            (repo / rel).parent.mkdir(parents=True)
            (repo / rel).write_text("class Foo\n")
            text = f"{repo / rel}:1\napp/src/main/java/Foo.kt:2"
            self.assertEqual(probe.extract_paths(text, repo), {str(rel)})

    def test_empty_semantic_result_detects_empty_json(self) -> None:
        self.assertTrue(probe.text_is_empty_semantic_result("{}"))
        self.assertTrue(probe.text_is_empty_semantic_result("[]"))
        self.assertFalse(probe.text_is_empty_semantic_result("app/Foo.kt:1"))

    def test_classifies_fixed_when_serena_and_studio_overlap(self) -> None:
        result = probe.classify_case(
            {"status": "pass", "stdout": "symbol", "stderr": ""},
            {"status": "pass", "stdout": "app/Foo.kt:1", "stderr": ""},
            {"status": "pass", "stdout": "app/Foo.kt:2", "stderr": ""},
            {"app/Foo.kt"},
            {"app/Foo.kt"},
        )
        self.assertEqual(result, "fixed")

    def test_classifies_empty_serena_references_as_named_boundary(self) -> None:
        result = probe.classify_case(
            {"status": "pass", "stdout": "symbol", "stderr": ""},
            {"status": "pass", "stdout": "{}", "stderr": ""},
            {"status": "pass", "stdout": "app/Foo.kt:2", "stderr": ""},
            set(),
            {"app/Foo.kt"},
        )
        self.assertEqual(result, "serena-reference-empty-boundary")

    def test_overall_classification_prefers_fixed_if_any_case_fixes(self) -> None:
        rows = [{"classification": "unclassified disagreement"}, {"classification": "fixed"}]
        self.assertEqual(probe.overall_classification(rows), "fixed")


if __name__ == "__main__":
    unittest.main()
