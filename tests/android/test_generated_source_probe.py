from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "generated_source_probe.py"
spec = importlib.util.spec_from_file_location("android_generated_source_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidGeneratedSourceProbeTests(unittest.TestCase):
    def test_detects_android_generation_features(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            gradle = repo / "build.gradle.kts"
            gradle.write_text(
                "alias(libs.plugins.ksp)\n"
                "alias(libs.plugins.apollo3)\n"
                "implementation(libs.room.runtime)\n"
                "android { buildFeatures.viewBinding = true }\n"
            )
            features = probe.detect_features(repo)

            self.assertTrue(features["apollo"]["present"])
            self.assertTrue(features["ksp"]["present"])
            self.assertTrue(features["room"]["present"])
            self.assertTrue(features["view_binding"]["present"])

    def test_find_generated_dirs_classifies_apollo_and_ksp(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            (repo / "feature" / "build" / "generated" / "operationOutput").mkdir(parents=True)
            (repo / "app" / "build" / "generated" / "ksp" / "debug").mkdir(parents=True)

            rows = probe.find_generated_dirs(repo, limit=20)
            kinds = {row["kind"] for row in rows}

            self.assertIn("apollo", kinds)
            self.assertIn("ksp", kinds)

    def test_assertions_do_not_fail_when_generated_dirs_exist(self) -> None:
        payload = {
            "generated_dir_count": 1,
            "features": {
                "apollo": {"present": True, "file_count": 1},
                "ksp": {"present": True, "file_count": 1},
                "room": {"present": True, "file_count": 1},
                "build_config": {"present": True, "file_count": 1},
            },
        }
        assertions = probe.build_assertions(payload)
        self.assertEqual(assertions["summary"]["fail"], 0)


if __name__ == "__main__":
    unittest.main()
