from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "serena_project_server_probe.py"
spec = importlib.util.spec_from_file_location("serena_project_server_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class SerenaProjectServerProbeTests(unittest.TestCase):
    def test_validate_rejects_invalid_json_params(self) -> None:
        cases = [
            {
                "case_id": "bad",
                "repo": "sample",
                "project": "sample",
                "tool_name": "find_symbol",
                "tool_params_json": "{bad",
                "expected_status": "pass",
                "min_byte_count": "1",
                "purpose": "test",
            }
        ]
        errors = probe.validate(cases, {}, require_repos=False)
        self.assertEqual(len(errors), 1)
        self.assertIn("invalid tool_params_json", errors[0])

    def test_validate_accepts_registered_repo_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            cases = [
                {
                    "case_id": "good",
                    "repo": "sample",
                    "project": "sample-project",
                    "tool_name": "find_symbol",
                    "tool_params_json": '{"name_path_pattern":"MainActivity","max_answer_chars":6000}',
                    "expected_status": "pass",
                    "min_byte_count": "1",
                    "purpose": "test",
                }
            ]
            self.assertEqual(probe.validate(cases, {"sample": repo}, require_repos=True), [])

    def test_validate_requires_bounded_answer_chars(self) -> None:
        cases = [
            {
                "case_id": "unbounded",
                "repo": "sample",
                "project": "sample",
                "tool_name": "find_referencing_symbols",
                "tool_params_json": '{"name_path":"BaseViewModel"}',
                "expected_status": "pass",
                "min_byte_count": "1",
                "purpose": "test",
            },
            {
                "case_id": "too_large",
                "repo": "sample",
                "project": "sample",
                "tool_name": "find_symbol",
                "tool_params_json": '{"name_path_pattern":"BaseViewModel","max_answer_chars":20000}',
                "expected_status": "pass",
                "min_byte_count": "1",
                "purpose": "test",
            },
        ]
        errors = probe.validate(cases, {}, require_repos=False)
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("max_answer_chars is required" in error for error in errors))
        self.assertTrue(any("max_answer_chars must be between" in error for error in errors))

    def test_classify_marks_errors_and_short_outputs(self) -> None:
        self.assertEqual(probe.classify("Error executing tool: bad", "", False, 1), "error")
        self.assertEqual(probe.classify("", "boom", False, 1), "error")
        self.assertEqual(probe.classify("ok", "", False, 10), "empty")
        self.assertEqual(probe.classify("long enough", "", False, 1), "pass")

    def test_build_assertions_adds_case_stability_check(self) -> None:
        rows = [
            {
                "repo": "sample",
                "case_id": "symbol",
                "pass_index": 1,
                "expected_status": "pass",
                "status": "pass",
                "estimated_tokens": 10,
            },
            {
                "repo": "sample",
                "case_id": "symbol",
                "pass_index": 2,
                "expected_status": "pass",
                "status": "pass",
                "estimated_tokens": 10,
            },
        ]
        payload = probe.build_assertions(rows, expected_repeats=2)
        self.assertEqual(payload["summary"]["fail"], 0)
        self.assertTrue(any(item["check"] == "stable_status" for item in payload["assertions"]))
        self.assertTrue(any(item["check"] == "measured_pass_count" for item in payload["assertions"]))

    def test_build_assertions_fails_when_measured_pass_count_is_short(self) -> None:
        rows = [
            {
                "repo": "sample",
                "case_id": "symbol",
                "pass_index": 1,
                "expected_status": "pass",
                "status": "pass",
                "estimated_tokens": 10,
            }
        ]
        payload = probe.build_assertions(rows, expected_repeats=2)
        self.assertEqual(payload["summary"]["fail"], 1)
        self.assertTrue(
            any(item["check"] == "measured_pass_count" and item["status"] == "fail" for item in payload["assertions"])
        )


if __name__ == "__main__":
    unittest.main()
