from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "kotlin_lsp_memory_matrix.py"
spec = importlib.util.spec_from_file_location("android_kotlin_lsp_memory_matrix", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidKotlinLspMemoryMatrixTests(unittest.TestCase):
    def test_parse_jvm_values_accepts_xmx_list(self) -> None:
        self.assertEqual(probe.parse_jvm_values("-Xmx2G, -Xmx4G"), ["-Xmx2G", "-Xmx4G"])

    def test_parse_jvm_values_rejects_non_xmx(self) -> None:
        with self.assertRaises(Exception):
            probe.parse_jvm_values("-Dfoo=bar")

    def test_local_override_text_contains_kotlin_jvm_options(self) -> None:
        text = probe.local_override_text("-Xmx4G")
        self.assertIn("ls_specific_settings:", text)
        self.assertIn("kotlin:", text)
        self.assertIn('jvm_options: "-Xmx4G"', text)

    def test_temporary_override_restores_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            serena = repo / ".serena"
            serena.mkdir()
            local = serena / "project.local.yml"
            local.write_text("original: true\n")
            with probe.temporary_project_local_override(repo, "-Xmx6G"):
                self.assertIn("-Xmx6G", local.read_text())
            self.assertEqual(local.read_text(), "original: true\n")

    def test_choose_lowest_stable_uses_first_zero_fail_value(self) -> None:
        results = [
            {"jvm_options": "-Xmx2G", "assertions": {"summary": {"fail": 1}}, "rows": [], "process_delta": {}},
            {"jvm_options": "-Xmx4G", "assertions": {"summary": {"fail": 0}}, "rows": [], "process_delta": {"kotlin_lsp": 1}},
            {"jvm_options": "-Xmx6G", "assertions": {"summary": {"fail": 0}}, "rows": [], "process_delta": {"kotlin_lsp": 0}},
        ]
        self.assertEqual(probe.choose_lowest_stable(results), "-Xmx6G")


if __name__ == "__main__":
    unittest.main()
