from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.lib.agent_session import AgentProfile, RouteProfile
from scripts.lib.route_isolation import materialize_route_isolation


def cursor_profile(*, args: list[str] | None = None, fallback_commands: list[str] | None = None) -> AgentProfile:
    return AgentProfile(
        agent_id="cursor-agent",
        display_name="Cursor Agent",
        command="agent",
        fallback_commands=fallback_commands or [],
        args=args or ["-p", "--mode", "ask", "--sandbox", "enabled"],
        env={},
        prompt_mode="argument",
        telemetry_sources=["transcript_proxy"],
        supports_live=True,
        default_timeout_seconds=900,
        terminal_mode="pty",
    )


def codex_profile() -> AgentProfile:
    return AgentProfile(
        agent_id="codex",
        display_name="Codex CLI",
        command="codex",
        fallback_commands=[],
        args=["exec", "--sandbox", "read-only", "--ephemeral", "--json", "-"],
        env={},
        prompt_mode="stdin",
        telemetry_sources=["codex_otel_if_enabled", "transcript_proxy"],
        supports_live=True,
        default_timeout_seconds=900,
        terminal_mode="pty",
    )


def search_only_profile() -> RouteProfile:
    return RouteProfile(
        profile_id="A-search-only",
        display_name="Search-only baseline",
        allowed_tools=["rg", "basic file reads"],
        blocked_tools=["Serena", "Kotlin LSP", "semantic reference tools"],
        required_first_tool="rg_or_fd",
        high_fanout_policy="raw_search_allowed",
        max_raw_output_bytes=50000,
        instructions="Use search only.",
    )


class RouteIsolationTests(unittest.TestCase):
    def test_codex_search_only_uses_empty_mcp_config_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.lib.route_isolation.shutil.which", return_value="/bin/codex"):
                isolation = materialize_route_isolation(
                    agent_profile=codex_profile(),
                    route_profile=search_only_profile(),
                    run_dir=Path(tmp) / "run",
                    probe_cursor_mcp=False,
                )

            self.assertIn("--ignore-user-config", isolation.args)
            self.assertIn("--ignore-rules", isolation.args)
            self.assertIn("--disable", isolation.args)
            self.assertIn("plugins", isolation.args)
            self.assertIn("-c", isolation.args)
            self.assertIn("mcp_servers={}", isolation.args)
            self.assertIn("codex_empty_mcp_servers_config", isolation.hard_controls)
            self.assertIn("codex_plugins_disabled", isolation.hard_controls)
            self.assertEqual(isolation.weak_controls, [])

    def test_codex_tui_search_only_does_not_claim_exec_hard_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.lib.route_isolation.shutil.which", return_value="/bin/codex"):
                isolation = materialize_route_isolation(
                    agent_profile=codex_profile(),
                    route_profile=search_only_profile(),
                    run_dir=Path(tmp) / "run",
                    probe_cursor_mcp=False,
                    terminal_mode="codex-tui",
                )

            self.assertNotIn("--ignore-user-config", isolation.args)
            self.assertNotIn("codex_empty_mcp_servers_config", isolation.hard_controls)
            self.assertIn("codex_tui_visible_mode_does_not_apply_exec_hard_isolation", isolation.weak_controls)

    def test_cursor_search_only_is_hard_when_mcp_probe_finds_no_loaded_servers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            completed = subprocess.CompletedProcess(
                args=["agent", "mcp", "list"],
                returncode=0,
                stdout="context7: not loaded (needs approval)\nfigma-desktop: disabled\n",
                stderr="",
            )
            with patch("scripts.lib.route_isolation.shutil.which", return_value="/bin/agent"), patch(
                "scripts.lib.route_isolation.subprocess.run", return_value=completed
            ) as run:
                isolation = materialize_route_isolation(
                    agent_profile=cursor_profile(),
                    route_profile=search_only_profile(),
                    run_dir=root / "run",
                    workspace_cwd=workspace,
                    probe_cursor_mcp=True,
                )

            self.assertEqual(isolation.command, "/bin/agent")
            self.assertIn("cursor_ask_mode_read_only", isolation.hard_controls)
            self.assertIn("cursor_sandbox_enabled", isolation.hard_controls)
            self.assertIn("cursor_no_approve_mcps", isolation.hard_controls)
            self.assertIn("cursor_mcp_list_no_loaded_servers", isolation.hard_controls)
            self.assertEqual(isolation.weak_controls, [])
            self.assertEqual(run.call_args.kwargs["cwd"], workspace.resolve())

    def test_cursor_search_only_stays_weak_when_mcp_servers_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = subprocess.CompletedProcess(
                args=["agent", "mcp", "list"],
                returncode=0,
                stdout="context7: loaded\n",
                stderr="",
            )
            with patch("scripts.lib.route_isolation.shutil.which", return_value="/bin/agent"), patch(
                "scripts.lib.route_isolation.subprocess.run", return_value=completed
            ):
                isolation = materialize_route_isolation(
                    agent_profile=cursor_profile(),
                    route_profile=search_only_profile(),
                    run_dir=root / "run",
                    workspace_cwd=root,
                    probe_cursor_mcp=True,
                )

            self.assertIn("cursor_mcp_servers_loaded", isolation.weak_controls)

    def test_cursor_approve_mcps_flag_keeps_route_isolation_weak(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch("scripts.lib.route_isolation.shutil.which", return_value="/bin/agent"), patch(
                "scripts.lib.route_isolation.subprocess.run"
            ) as run:
                isolation = materialize_route_isolation(
                    agent_profile=cursor_profile(args=["-p", "--approve-mcps"]),
                    route_profile=search_only_profile(),
                    run_dir=Path(tmp) / "run",
                    workspace_cwd=tmp,
                    probe_cursor_mcp=True,
                )

            self.assertIn("cursor_approve_mcps_allows_mcp_tools", isolation.weak_controls)
            run.assert_not_called()

    def test_agent_command_resolution_uses_fallback_when_primary_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            def which(candidate: str) -> str | None:
                return "/bin/cursor-agent" if candidate == "cursor-agent" else None

            with patch("scripts.lib.route_isolation.shutil.which", side_effect=which):
                isolation = materialize_route_isolation(
                    agent_profile=cursor_profile(fallback_commands=["cursor-agent"]),
                    route_profile=search_only_profile(),
                    run_dir=Path(tmp) / "run",
                    probe_cursor_mcp=False,
                )

            self.assertEqual(isolation.command, "/bin/cursor-agent")


if __name__ == "__main__":
    unittest.main()
