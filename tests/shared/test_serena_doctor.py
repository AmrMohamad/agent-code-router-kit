from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
DOCTOR_PATH = ROOT / "scripts" / "setup" / "serena-doctor.py"
spec = importlib.util.spec_from_file_location("serena_doctor", DOCTOR_PATH)
serena_doctor = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["serena_doctor"] = serena_doctor
spec.loader.exec_module(serena_doctor)


class SerenaDoctorTests(unittest.TestCase):
    def stable_args(self, repo: Path, **overrides: str) -> Namespace:
        values = {
            "target_repo": str(repo),
            "profile": "android",
            "expected_languages": "",
            "source_file": "",
            "symbol_smoke": "",
            "json": True,
        }
        values.update(overrides)
        return Namespace(**values)

    def stable_payload(self, args: Namespace) -> dict:
        with patch.object(serena_doctor, "serena_version", return_value=("serena 1.0", "serena 1.0")), patch.object(
            serena_doctor,
            "process_counts",
            return_value={
                "serena_mcp": 0,
                "kotlin_lsp": 0,
                "json_lsp": 0,
                "java_jdtls": 0,
                "sourcekit_lsp": 0,
                "python_lsp": 0,
            },
        ):
            return serena_doctor.build_payload(args)

    def test_parse_project_languages_from_block_list(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / ".serena" / "project.yml"
            project.parent.mkdir()
            project.write_text("languages:\n  - kotlin\n  - json\n", encoding="utf-8")

            self.assertEqual(serena_doctor.parse_project_languages(project), ["kotlin", "json"])

    def test_missing_project_config_fails_with_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            payload = self.stable_payload(self.stable_args(Path(raw)))

            self.assertEqual(payload["status"], "fail")
            config = next(check for check in payload["checks"] if check["name"] == "project_config")
            self.assertEqual(config["status"], "fail")
            self.assertIn("next_action", config["details"])

    def test_android_java_extra_is_warning_not_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            project = repo / ".serena" / "project.yml"
            project.parent.mkdir()
            project.write_text("languages: [kotlin, java, json]\n", encoding="utf-8")

            payload = self.stable_payload(self.stable_args(repo))

            config = next(check for check in payload["checks"] if check["name"] == "project_config")
            self.assertEqual(config["status"], "warn")
            self.assertIn("java", config["details"]["risk_notes"])
            self.assertNotEqual(payload["status"], "fail")

    def test_source_symbol_smoke_reports_local_match_as_precondition(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            project = repo / ".serena" / "project.yml"
            source = repo / "app" / "FeatureViewModel.kt"
            project.parent.mkdir()
            source.parent.mkdir()
            project.write_text("languages: [kotlin, json]\n", encoding="utf-8")
            source.write_text("class FeatureViewModel\n", encoding="utf-8")

            payload = self.stable_payload(
                self.stable_args(repo, source_file="app/FeatureViewModel.kt", symbol_smoke="FeatureViewModel")
            )

            smoke = next(check for check in payload["checks"] if check["name"] == "source_symbol_smoke")
            self.assertEqual(smoke["status"], "warn")
            self.assertTrue(smoke["details"]["local_text_match"])
            self.assertIn("semantic proof", smoke["details"]["proof_boundary"])

    def test_source_symbol_smoke_rejects_relative_path_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as raw, tempfile.NamedTemporaryFile("w", encoding="utf-8") as outside:
            repo = Path(raw)
            project = repo / ".serena" / "project.yml"
            project.parent.mkdir()
            project.write_text("languages: [python]\n", encoding="utf-8")
            outside.write("class OutsideSymbol:\n    pass\n")
            outside.flush()

            payload = self.stable_payload(
                self.stable_args(
                    repo,
                    profile="python",
                    source_file=os.path.relpath(outside.name, repo),
                    symbol_smoke="OutsideSymbol",
                )
            )

            smoke = next(check for check in payload["checks"] if check["name"] == "source_symbol_smoke")
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(smoke["status"], "fail")
            self.assertIn("outside the target repo", smoke["message"])

    def test_source_symbol_smoke_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            source = repo / "Feature.py"
            project = repo / ".serena" / "project.yml"
            project.parent.mkdir()
            project.write_text("languages: [python]\n", encoding="utf-8")
            source.write_text("class Feature:\n    pass\n", encoding="utf-8")

            payload = self.stable_payload(
                self.stable_args(repo, profile="python", source_file=str(source), symbol_smoke="Feature")
            )

            smoke = next(check for check in payload["checks"] if check["name"] == "source_symbol_smoke")
            self.assertEqual(payload["status"], "fail")
            self.assertEqual(smoke["status"], "fail")
            self.assertIn("must be relative", smoke["message"])

    def test_generic_profile_does_not_warn_on_project_languages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            project = repo / ".serena" / "project.yml"
            project.parent.mkdir()
            project.write_text("languages: [python]\n", encoding="utf-8")

            payload = self.stable_payload(self.stable_args(repo, profile="generic"))

            config = next(check for check in payload["checks"] if check["name"] == "project_config")
            self.assertEqual(config["status"], "pass")
            self.assertIsNone(config["details"]["expected_languages"])
            self.assertEqual(config["details"]["extra_languages"], [])


if __name__ == "__main__":
    unittest.main()
