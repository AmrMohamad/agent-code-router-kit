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
            "scripts/setup/install-codegraph-gateway.sh",
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
            ROOT / "templates" / "codegraph" / "claude-mcp.example.json",
            ROOT / "templates" / "codegraph" / "cursor-mcp.example.json",
            ROOT / "templates" / "codegraph" / "opencode.example.json",
        ]:
            with self.subTest(path=path):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if "mcpServers" in payload:
                    self.assertTrue(payload["mcpServers"])
                else:
                    self.assertTrue(payload["mcp"])

    def test_agent_self_install_opencode_with_codegraph_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw)
            result = self.run_script(
                "bash",
                "scripts/setup/agent-self-install.sh",
                "--target-repo",
                str(target),
                "--agent",
                "opencode",
                "--profile",
                "python",
                "--with-codegraph",
                "--dry-run",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("OpenCode CodeGraph MCP example", result.stdout)
            self.assertFalse((target / ".agent-code-router").exists())

    def test_agent_self_install_opencode_without_codegraph_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = Path(raw)
            result = self.run_script(
                "bash",
                "scripts/setup/agent-self-install.sh",
                "--target-repo",
                str(target),
                "--agent",
                "opencode",
                "--profile",
                "python",
                "--dry-run",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("no default MCP config will be written unless --with-codegraph is enabled", result.stdout)
            self.assertFalse((target / ".agent-code-router").exists())

    def test_install_codegraph_gateway_dry_run_prints_pinned_versions(self) -> None:
        result = self.run_script("bash", "scripts/setup/install-codegraph-gateway.sh", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Gateway package:", result.stdout)
        self.assertIn("Pinned dependency:", result.stdout)

    def test_install_codegraph_gateway_dry_run_works_outside_repo_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = subprocess.run(
                ["bash", str(ROOT / "scripts" / "setup" / "install-codegraph-gateway.sh"), "--dry-run"],
                cwd=raw,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Gateway package:", result.stdout)

    def test_init_codegraph_project_rejects_missing_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            missing = Path(raw) / "missing"
            result = self.run_script(
                "python3",
                "scripts/setup/init-codegraph-project.py",
                "--target-repo",
                str(missing),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("target repository was not found", result.stderr)


if __name__ == "__main__":
    unittest.main()
