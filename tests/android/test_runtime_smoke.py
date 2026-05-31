from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "runtime_smoke.py"
spec = importlib.util.spec_from_file_location("android_runtime_smoke", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidRuntimeSmokeTests(unittest.TestCase):
    def test_variant_gate_suffix_handles_flavors(self) -> None:
        self.assertEqual(probe.variant_suffix("stagingDebug"), "StagingDebug")
        self.assertEqual(probe.variant_gate_suffix("stagingDebug"), "staging_debug")
        self.assertEqual(probe.variant_gate_suffix("debug"), "debug")

    def test_gradle_task_normalizes_module_path(self) -> None:
        self.assertEqual(probe.gradle_task(":android:app", "assembleStagingDebug"), ":android:app:assembleStagingDebug")
        self.assertEqual(probe.gradle_task("android:app", "installStagingDebug"), ":android:app:installStagingDebug")
        self.assertEqual(probe.gradle_task("", "help"), "help")

    def test_command_gate_records_failures_without_throwing(self) -> None:
        result = {
            "argv": ["fake"],
            "exit_code": 1,
            "timed_out": False,
            "wall_seconds": 0.1,
            "stdout": "out",
            "stderr": "err",
            "line_count": 2,
            "byte_count": 6,
            "estimated_tokens": 2,
        }
        gate = probe.command_gate("assemble_staging_debug", "build", "gradle", result, "ok", "bad")
        self.assertEqual(gate["level"], "fail")
        self.assertIn("details_json", gate)

    def test_local_property_keys_do_not_return_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "local.properties").write_text("sdk.dir=/secret/path\nstaging.sample.map.api.key=secret\n")
            self.assertEqual(probe.local_property_keys(repo), ["sdk.dir", "staging.sample.map.api.key"])

    def test_validate_args_requires_package_for_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "gradlew").write_text("#!/bin/sh\n")
            args = Namespace(
                repo=str(repo),
                variant="stagingDebug",
                package_name="",
                skip_launch=False,
                timeout=1,
                gradle_timeout=1,
            )
            errors = probe.validate_args(args)
            self.assertIn("--package-name is required unless --skip-launch is used", errors)


if __name__ == "__main__":
    unittest.main()
