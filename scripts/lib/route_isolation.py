from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.lib.agent_session import AgentProfile, RouteProfile, to_json_file
from scripts.lib.hermetic_agent_environment import HermeticAgentEnvironment


SEARCH_ONLY_TOOL_NAMES = {
    "read": "Read",
    "grep": "Grep",
    "glob": "Glob",
    "bash": "Bash",
}


@dataclass(frozen=True)
class RouteIsolation:
    agent_id: str
    profile_id: str
    command: str
    args: list[str]
    env: dict[str, str]
    mode: str
    hard_controls: list[str]
    weak_controls: list[str]
    config_files: list[str]
    observations: dict[str, object]


def _append_once(values: list[str], *items: str) -> None:
    for item in items:
        if item not in values:
            values.append(item)


def _has_option(values: list[str], option: str) -> bool:
    return option in values or any(value.startswith(f"{option}=") for value in values)


def _append_codex_exec_option(args: list[str], *items: str) -> None:
    insert_at = args.index("-") if "-" in args else len(args)
    for item in items:
        if item not in args:
            args.insert(insert_at, item)
            insert_at += 1


def _append_codex_exec_pair(args: list[str], option: str, value: str) -> None:
    insert_at = args.index("-") if "-" in args else len(args)
    for index in range(len(args) - 1):
        if args[index] == option and args[index + 1] == value:
            return
    args.insert(insert_at, option)
    args.insert(insert_at + 1, value)


def _write_empty_mcp_config(run_dir: Path) -> Path:
    path = run_dir / "empty-mcp-config.json"
    path.write_text(json.dumps({"mcpServers": {}}, indent=2) + "\n", encoding="utf-8")
    return path


def _resolve_agent_command(agent_profile: AgentProfile) -> str:
    for candidate in [agent_profile.command, *agent_profile.fallback_commands]:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return agent_profile.command


def _cursor_mcp_status(*, command: str, cwd: str | Path) -> dict[str, object]:
    completed = subprocess.run(
        [command, "mcp", "list"],
        cwd=Path(cwd).expanduser().resolve(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    loaded_lines = [
        line
        for line in lines
        if ":" in line
        and not any(marker in line.lower() for marker in ("not loaded", "needs approval", "disabled"))
    ]
    return {
        "returncode": completed.returncode,
        "lines": lines,
        "loaded_lines": loaded_lines,
    }


def materialize_route_isolation(
    *,
    agent_profile: AgentProfile,
    route_profile: RouteProfile,
    run_dir: str | Path,
    workspace_cwd: str | Path | None = None,
    probe_cursor_mcp: bool = False,
    terminal_mode: str | None = None,
    hermetic_environment: HermeticAgentEnvironment | None = None,
) -> RouteIsolation:
    """Build the effective live invocation for a route arm.

    This is intentionally explicit: prompt-only policy is not enough for the
    benchmark. When a CLI exposes a config/tool switch, record and use it.
    """

    out = Path(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    args = list(agent_profile.args)
    env = dict(agent_profile.env)
    hard_controls: list[str] = []
    weak_controls: list[str] = []
    config_files: list[str] = []
    observations: dict[str, object] = {}
    command = _resolve_agent_command(agent_profile)

    blocked = {tool.lower() for tool in route_profile.blocked_tools}
    blocks_semantic = any(
        token in " ".join(blocked)
        for token in ("serena", "lsp", "semantic", "android studio")
    )

    env.update(
        {
            "RARB_AGENT_ID": agent_profile.agent_id,
            "RARB_ROUTE_PROFILE": route_profile.profile_id,
            "RARB_ALLOWED_TOOLS": ",".join(route_profile.allowed_tools),
            "RARB_BLOCKED_TOOLS": ",".join(route_profile.blocked_tools),
        }
    )

    if hermetic_environment is not None:
        env.update(hermetic_environment.env)
        weak_controls.extend(hermetic_environment.weak_controls)
        config_files.extend(
            [
                str(out / "effective-agent-config.json"),
                str(out / "effective-agent-config.sha256"),
                str(out / "treatment-diff.json"),
            ]
        )
        observations["effective_agent_config_sha256"] = hermetic_environment.effective_config_sha256
        observations["semantic_access_enabled"] = hermetic_environment.semantic_access_enabled
        observations["routing_discipline_enabled"] = hermetic_environment.routing_discipline_enabled
        if agent_profile.agent_id == "codex" and terminal_mode == "codex-tui":
            weak_controls.append("codex_tui_visible_mode_does_not_apply_hermetic_exec_config")
        elif agent_profile.agent_id == "codex":
            hard_controls.extend(hermetic_environment.hard_controls)
            _append_codex_exec_option(args, "--ignore-user-config", "--ignore-rules", "--disable", "plugins")
            for override in hermetic_environment.codex_config_overrides:
                _append_codex_exec_pair(args, "-c", override)
        else:
            weak_controls.append("hermetic_agent_home_not_supported_for_agent")
    elif blocks_semantic:
        env["RARB_SEMANTIC_TOOLS_DISABLED"] = "1"
        if agent_profile.agent_id == "codex" and terminal_mode == "codex-tui":
            weak_controls.append("codex_tui_visible_mode_does_not_apply_exec_hard_isolation")
        elif agent_profile.agent_id == "codex":
            _append_codex_exec_option(args, "--ignore-user-config", "--ignore-rules", "--disable", "plugins", "-c", "mcp_servers={}")
            hard_controls.extend(["codex_ignore_user_config", "codex_ignore_rules", "codex_plugins_disabled", "codex_empty_mcp_servers_config"])
        elif agent_profile.agent_id == "claude-code":
            empty_mcp = _write_empty_mcp_config(out)
            config_files.append(str(empty_mcp))
            if not _has_option(args, "--mcp-config"):
                args.extend(["--mcp-config", str(empty_mcp)])
            _append_once(args, "--strict-mcp-config")
            if not _has_option(args, "--tools") and not _has_option(args, "--allowedTools"):
                args.extend(["--tools", ",".join(SEARCH_ONLY_TOOL_NAMES.values())])
            hard_controls.extend(["claude_strict_empty_mcp_config", "claude_builtin_search_tools_only"])
        elif agent_profile.agent_id == "cursor-agent":
            if not _has_option(args, "--mode"):
                args.extend(["--mode", "ask"])
            if not _has_option(args, "--sandbox"):
                args.extend(["--sandbox", "enabled"])
            hard_controls.extend(["cursor_ask_mode_read_only", "cursor_sandbox_enabled"])
            if _has_option(args, "--approve-mcps"):
                weak_controls.append("cursor_approve_mcps_allows_mcp_tools")
            elif probe_cursor_mcp:
                try:
                    status = _cursor_mcp_status(command=command, cwd=workspace_cwd or out)
                    observations["cursor_mcp_list"] = status
                    if status["returncode"] == 0 and not status["loaded_lines"]:
                        hard_controls.extend(["cursor_no_approve_mcps", "cursor_mcp_list_no_loaded_servers"])
                    elif status["returncode"] != 0:
                        weak_controls.append("cursor_mcp_list_probe_failed")
                    else:
                        weak_controls.append("cursor_mcp_servers_loaded")
                except (OSError, subprocess.SubprocessError) as exc:
                    observations["cursor_mcp_list_error"] = str(exc)
                    weak_controls.append("cursor_mcp_list_probe_failed")
            else:
                weak_controls.append("cursor_mcp_state_not_probed")
        else:
            weak_controls.append("unknown_agent_no_hard_tool_isolation")

    isolation = RouteIsolation(
        agent_id=agent_profile.agent_id,
        profile_id=route_profile.profile_id,
        command=command,
        args=args,
        env=env,
        mode="config" if hard_controls else "prompt-plus-env",
        hard_controls=hard_controls,
        weak_controls=weak_controls,
        config_files=config_files,
        observations=observations,
    )
    to_json_file(out / "route-isolation.json", asdict(isolation))
    return isolation
