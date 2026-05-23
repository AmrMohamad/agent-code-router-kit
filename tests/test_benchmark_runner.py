from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "benchmarks" / "benchmark_runner.py"
spec = importlib.util.spec_from_file_location("benchmark_runner", RUNNER_PATH)
assert spec and spec.loader
benchmark_runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark_runner)


class BenchmarkRunnerTests(unittest.TestCase):
    def test_sample_manifest_validates(self) -> None:
        cases = benchmark_runner.load_cases(ROOT / "benchmarks" / "swift-ios-router" / "cases.example.tsv")
        errors = benchmark_runner.validate_cases(cases, {}, require_repos=False)
        self.assertEqual(errors, [])

    def test_rejects_execution_or_mutation_flags(self) -> None:
        cases = [
            {
                "case_id": "exec_fd",
                "repo": "sample",
                "category": "discovery",
                "tool": "fd",
                "command_label": "bad",
                "metric_mode": "path_lines",
                "command": "fd -x echo .",
                "expected_first_tool": "fd",
                "purpose": "bad",
            },
            {
                "case_id": "pre_rg",
                "repo": "sample",
                "category": "literal_key",
                "tool": "rg",
                "command_label": "bad",
                "metric_mode": "rg_lines",
                "command": "rg --pre cat example",
                "expected_first_tool": "rg / fd",
                "purpose": "bad",
            },
            {
                "case_id": "rewrite_ast_grep",
                "repo": "sample",
                "category": "structural_swift_pattern",
                "tool": "ast-grep",
                "command_label": "bad",
                "metric_mode": "ast_grep",
                "command": "ast-grep --rewrite 'x' -p 'y' .",
                "expected_first_tool": "ast-grep",
                "purpose": "bad",
            },
        ]
        errors = benchmark_runner.validate_cases(cases, {}, require_repos=False)
        self.assertEqual(len(errors), 3)
        self.assertTrue(all("not allowed" in error for error in errors))

    def test_rg_json_parser_uses_json_path_field(self) -> None:
        payload = {
            "type": "match",
            "data": {
                "path": {"text": "Sources/App/ExampleRouter.swift"},
                "lines": {"text": "final class ExampleRouter {}\n"},
            },
        }
        paths, matches, errors = benchmark_runner.parse_rg_json(json.dumps(payload) + "\n")
        self.assertEqual(paths, {"Sources/App/ExampleRouter.swift"})
        self.assertEqual(matches, 1)
        self.assertEqual(errors, 0)


if __name__ == "__main__":
    unittest.main()
