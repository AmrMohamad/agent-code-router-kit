from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "studio_semantic_probe.py"
spec = importlib.util.spec_from_file_location("android_studio_semantic_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AndroidStudioSemanticProbeTests(unittest.TestCase):
    def test_validate_requires_existing_context_file_when_repos_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            cases = [
                {
                    "case_id": "missing_context",
                    "repo": "sample",
                    "project": "sample",
                    "command_type": "find-declaration",
                    "symbol": "MainActivity",
                    "context_file": "src/main/MainActivity.kt",
                    "expected_status": "probe",
                    "purpose": "test",
                }
            ]
            errors = probe.validate(cases, {"sample": repo}, require_repos=True)
            self.assertEqual(len(errors), 1)
            self.assertIn("context_file missing", errors[0])

    def test_validate_accepts_existing_relative_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            source = repo / "src" / "main" / "MainActivity.kt"
            source.parent.mkdir(parents=True)
            source.write_text("class MainActivity\n")
            cases = [
                {
                    "case_id": "existing_context",
                    "repo": "sample",
                    "project": "sample",
                    "command_type": "find-declaration",
                    "symbol": "MainActivity",
                    "context_file": "src/main/MainActivity.kt",
                    "expected_status": "probe",
                    "purpose": "test",
                }
            ]
            errors = probe.validate(cases, {"sample": repo}, require_repos=True)
            self.assertEqual(errors, [])

    def test_repeated_pass_case_with_one_timeout_is_warning_not_failure(self) -> None:
        rows = [
            {
                "repo": "sample",
                "case_id": "studio_check_sample",
                "expected_status": "pass",
                "status": "timeout",
                "pass_index": 1,
            },
            {
                "repo": "sample",
                "case_id": "studio_check_sample",
                "expected_status": "pass",
                "status": "pass",
                "pass_index": 2,
            },
        ]
        payload = probe.build_assertions(rows)
        self.assertEqual(payload["summary"]["fail"], 0)
        self.assertEqual(payload["summary"]["warn"], 2)


if __name__ == "__main__":
    unittest.main()
