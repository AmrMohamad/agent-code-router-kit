from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "serena_source_symbol_probe.py"
spec = importlib.util.spec_from_file_location("serena_source_symbol_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class SerenaSourceSymbolProbeTests(unittest.TestCase):
    def test_symbol_count_prefers_saved_count(self) -> None:
        text = (
            "  - MainActivity at line 34 of kind 5\n"
            "Successfully indexed file 'MainActivity.kt', 12 symbols saved to cache.\n"
        )
        self.assertEqual(probe.symbol_count_from(text), 12)

    def test_classify_detects_multiple_editing_sessions(self) -> None:
        status = probe.classify(
            exit_code=1,
            stdout="",
            stderr="Multiple editing sessions for one workspace are not supported yet",
            timed_out=False,
            symbol_count=0,
        )
        self.assertEqual(status, "multiple-editing-sessions")

    def test_validate_requires_existing_source_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            cases = [
                {
                    "case_id": "missing",
                    "repo": "sample",
                    "source_file": "src/MainActivity.kt",
                    "expected_status": "pass",
                    "min_symbol_count": "1",
                    "purpose": "test",
                }
            ]
            errors = probe.validate(cases, {"sample": repo}, require_repos=True)
            self.assertEqual(len(errors), 1)
            self.assertIn("source_file missing", errors[0])


if __name__ == "__main__":
    unittest.main()
