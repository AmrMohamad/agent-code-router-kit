from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class SetupScriptsTests(unittest.TestCase):
    def run_script(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(argv),
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_setup_scripts_have_valid_bash_syntax(self) -> None:
        scripts = [
            "scripts/setup/check-android-prereqs.sh",
            "scripts/setup/create-android-serena-project.sh",
            "scripts/setup/repair-serena-android-sessions.sh",
        ]
        result = self.run_script("bash", "-n", *scripts)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repair_serena_android_sessions_defaults_to_dry_run(self) -> None:
        result = self.run_script("bash", "scripts/setup/repair-serena-android-sessions.sh")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Mode: dry-run", result.stdout)
        self.assertIn("No processes were stopped.", result.stdout)


if __name__ == "__main__":
    unittest.main()
