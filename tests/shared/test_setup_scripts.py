from __future__ import annotations

import json
import subprocess
import tempfile
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
            "scripts/setup/agent-self-install.sh",
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

    def test_agent_self_install_supports_claude_without_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw)
            existing = target / "CLAUDE.md"
            existing.write_text("existing instructions\n", encoding="utf-8")

            result = self.run_script(
                "bash",
                "scripts/setup/agent-self-install.sh",
                "--target-repo",
                str(target),
                "--agent",
                "claude",
                "--profile",
                "python",
                "--apply",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(existing.read_text(encoding="utf-8"), "existing instructions\n")
            self.assertTrue((target / ".agent-code-router" / "CLAUDE.fragment.md").exists())
            self.assertTrue((target / ".agent-code-router" / "claude-mcp.example.json").exists())

    def test_agent_self_install_cursor_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw)
            result = self.run_script(
                "bash",
                "scripts/setup/agent-self-install.sh",
                "--target-repo",
                str(target),
                "--agent",
                "cursor",
                "--profile",
                "python",
                "--dry-run",
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Cursor Serena routing rule will be installed", result.stdout)
            self.assertFalse((target / ".cursor").exists())

    def test_client_mcp_examples_are_valid_json(self) -> None:
        for path in [
            ROOT / "templates" / "claude" / "mcp.example.json",
            ROOT / "templates" / "cursor" / "mcp.example.json",
        ]:
            with self.subTest(path=path):
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertIn("serena", payload["mcpServers"])


if __name__ == "__main__":
    unittest.main()
