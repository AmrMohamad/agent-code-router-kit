from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "project_model_probe.py"
spec = importlib.util.spec_from_file_location("android_project_model_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AndroidProjectModelProbeTests(unittest.TestCase):
    def test_required_local_property_keys_detects_build_logic_calls(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            build_logic = repo / "build-logic" / "convention" / "src" / "main" / "kotlin"
            build_logic.mkdir(parents=True)
            (build_logic / "Configure.kt").write_text(
                'val key = getPropertyFromLocalPropertiesFile("staging.sample.map.api.key")\n'
                'val id = localProps.getProperty("sample_analytics_id") ?: error("sample_analytics_id not found in local.properties")\n'
            )
            self.assertEqual(
                probe.required_local_property_keys(repo),
                ["sample_analytics_id", "staging.sample.map.api.key"],
            )

    def test_classify_prefers_missing_local_properties(self) -> None:
        status = probe.classify(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            missing_keys=["sample_analytics_id"],
            argv=["gradle", "help"],
        )
        self.assertEqual(status, "missing-local-properties")

    def test_gradle_wrapper_status_reports_missing_script_with_wrapper_props(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            props = repo / "gradle" / "wrapper" / "gradle-wrapper.properties"
            props.parent.mkdir(parents=True)
            props.write_text("distributionUrl=https\\://services.gradle.org/distributions/gradle-8.13-bin.zip\n")

            self.assertEqual(probe.gradle_wrapper_status(repo), "wrapper-script-missing")

    def test_gradle_command_reports_wrapper_source(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            wrapper = repo / "gradlew"
            wrapper.write_text("#!/usr/bin/env sh\n")
            wrapper.chmod(0o755)

            argv, source = probe.gradle_command(repo)

            self.assertEqual(source, "wrapper")
            self.assertEqual(argv[:1], [str(wrapper)])


if __name__ == "__main__":
    unittest.main()
