from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SUITE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "run_benchmark_suite.py"
spec = importlib.util.spec_from_file_location("run_android_benchmark_suite", SUITE_PATH)
assert spec and spec.loader
suite = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = suite
spec.loader.exec_module(suite)


class RunAndroidBenchmarkSuiteTests(unittest.TestCase):
    def args(self, **overrides: object) -> argparse.Namespace:
        values = {
            "sample_b2b_repo": "/tmp/sample_b2b",
            "sample_retail_repo": "/tmp/sample_retail",
            "results_root": "/tmp/results",
            "default_warmups": 1,
            "default_repeats": 3,
            "semantic_repeats": 3,
            "serena_repeats": 1,
            "serena_project_warmups": 1,
            "serena_project_repeats": 3,
            "project_model_repeats": 1,
            "timeout": 30.0,
            "serena_timeout": 180.0,
            "serena_project_timeout": 180.0,
            "serena_project_step_timeout": 900.0,
            "serena_project_port": 24392,
            "gradle_timeout": 180.0,
            "step_timeout": 600.0,
            "run_gradle_project_model": False,
            "require_clean_process_state": False,
            "enforce_assertions": False,
            "validate_only": False,
            "no_report": False,
            "report_name": "report.md",
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_build_steps_use_shell_safe_python_commands(self) -> None:
        steps = suite.build_steps(self.args())
        self.assertEqual([step.name for step in steps], [
            "default-search",
            "android-studio-semantic",
            "serena-source-symbol",
            "serena-project-server",
            "process-state",
            "project-model",
            "combined-report",
            "goal-audit",
        ])
        for step in steps:
            self.assertEqual(step.argv[0], sys.executable)
            self.assertNotIn(";", step.argv)
            self.assertNotIn("|", step.argv)

    def test_validate_only_omits_run_and_report(self) -> None:
        steps = suite.build_steps(self.args(validate_only=True))
        self.assertEqual([step.name for step in steps], [
            "default-search",
            "android-studio-semantic",
            "serena-source-symbol",
            "serena-project-server",
            "process-state",
            "project-model",
        ])
        for step in steps:
            self.assertIn("--validate", step.argv)
            self.assertNotIn("--run", step.argv)

    def test_gradle_project_model_flag_is_opt_in(self) -> None:
        plain = suite.build_steps(self.args())[5]
        with_gradle = suite.build_steps(self.args(run_gradle_project_model=True))[5]
        self.assertNotIn("--run-gradle", plain.argv)
        self.assertIn("--run-gradle", with_gradle.argv)

    def test_clean_process_state_flag_is_opt_in(self) -> None:
        plain = suite.build_steps(self.args())[4]
        strict = suite.build_steps(self.args(require_clean_process_state=True))[4]
        self.assertNotIn("--require-clean", plain.argv)
        self.assertIn("--require-clean", strict.argv)

    def test_goal_audit_writes_json_and_markdown(self) -> None:
        steps = suite.build_steps(self.args())
        audit = steps[-1]
        self.assertEqual(audit.name, "goal-audit")
        self.assertIn("scripts/benchmarks/android/goal_audit.py", audit.argv)
        self.assertIn("--output-json", audit.argv)
        self.assertIn("--output-md", audit.argv)

    def test_project_server_port_and_step_timeout_are_explicit(self) -> None:
        steps = suite.build_steps(self.args(serena_project_port=25001, serena_project_step_timeout=12.0))
        project_server = steps[3]
        self.assertEqual(project_server.name, "serena-project-server")
        self.assertEqual(project_server.timeout_seconds, 12.0)
        self.assertIn("--port", project_server.argv)
        self.assertIn("25001", project_server.argv)

    def test_run_step_times_out_process_group(self) -> None:
        step = suite.Step(
            "timeout-smoke",
            [sys.executable, "-c", "import time; time.sleep(10)"],
            0.1,
        )
        self.assertEqual(suite.run_step(step), 124)


if __name__ == "__main__":
    unittest.main()
