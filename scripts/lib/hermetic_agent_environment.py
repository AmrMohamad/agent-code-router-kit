from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.lib.agent_session import AgentProfile, RouteProfile, to_json_file
from scripts.lib.treatment_config import factors_for_profile, route_profile_hash, stable_json_sha256


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return _toml_string(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{key} = {_toml_value(item)}" for key, item in value.items()) + "}"
    raise TypeError(f"unsupported TOML override value: {type(value).__name__}")


@dataclass(frozen=True)
class HermeticAgentEnvironment:
    agent_id: str
    profile_id: str
    codex_home: str
    semantic_session_home: str
    semantic_access_enabled: bool
    routing_discipline_enabled: bool
    model_id: str
    reasoning_effort: str
    sandbox: str
    codex_config_overrides: list[str]
    env: dict[str, str]
    effective_config: dict[str, object]
    effective_config_sha256: str
    auth_files_copied: list[str]
    hard_controls: list[str]
    weak_controls: list[str]


def serena_mcp_config(*, repo_path: str | Path, semantic_home: str | Path) -> dict[str, object]:
    return {
        "command": "serena",
        "args": [
            "start-mcp-server",
            "--context=codex",
            "--project",
            str(Path(repo_path).resolve()),
            "--transport",
            "stdio",
            "--enable-web-dashboard",
            "false",
            "--open-web-dashboard",
            "false",
            "--enable-gui-log-window",
            "false",
        ],
        "env": {
            "RARB_SERENA_SESSION_HOME": str(Path(semantic_home).resolve()),
            "XDG_CONFIG_HOME": str((Path(semantic_home).resolve() / "xdg-config")),
        },
        "startup_timeout_sec": 30,
        "tool_timeout_sec": 120,
    }


def copy_codex_auth_files(*, codex_home: Path) -> list[str]:
    source_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    copied: list[str] = []
    for name in ("auth.json", "credentials.json"):
        source = source_home / name
        if not source.exists() or not source.is_file():
            continue
        target = codex_home / name
        shutil.copy2(source, target)
        copied.append(name)
    return copied


def materialize_hermetic_agent_environment(
    *,
    agent_profile: AgentProfile,
    route_profile: RouteProfile,
    run_dir: str | Path,
    repo_path: str | Path,
    model_id: str,
    reasoning_effort: str,
    sandbox: str,
    timeout_seconds: int,
    response_contract: str,
) -> HermeticAgentEnvironment:
    factors = factors_for_profile(route_profile.profile_id)
    out = Path(run_dir)
    codex_home = out / "codex-home"
    semantic_home = out / "serena-session"
    codex_home.mkdir(parents=True, exist_ok=True)
    semantic_home.mkdir(parents=True, exist_ok=True)
    auth_files_copied = copy_codex_auth_files(codex_home=codex_home) if agent_profile.agent_id == "codex" else []
    runtime_mcp_servers: dict[str, object] = {}
    normalized_mcp_servers: dict[str, object] = {}
    if factors.semantic_access_enabled:
        runtime_mcp_servers["serena"] = serena_mcp_config(repo_path=repo_path, semantic_home=semantic_home)
        normalized_mcp_servers["serena"] = {
            "command": "serena",
            "args": [
                "start-mcp-server",
                "--context=codex",
                "--project",
                "<snapshot-repo>",
                "--transport",
                "stdio",
                "--enable-web-dashboard",
                "false",
                "--open-web-dashboard",
                "false",
                "--enable-gui-log-window",
                "false",
            ],
            "env": {
                "RARB_SERENA_SESSION_HOME": "<isolated-serena-session>",
                "XDG_CONFIG_HOME": "<isolated-serena-xdg-config>",
            },
            "startup_timeout_sec": 30,
            "tool_timeout_sec": 120,
        }
    router_policy = {
        "enabled": factors.routing_discipline_enabled,
        "summary_first": factors.routing_discipline_enabled and "summary_first" in route_profile.high_fanout_policy,
    }
    effective_config: dict[str, object] = {
        "agent_id": agent_profile.agent_id,
        "agent_command": agent_profile.command,
        "profile_id": route_profile.profile_id,
        "semantic_access_enabled": factors.semantic_access_enabled,
        "routing_discipline_enabled": factors.routing_discipline_enabled,
        "ignore_user_config": True,
        "ignore_rules": True,
        "plugins_disabled": True,
        "ephemeral": "--ephemeral" in agent_profile.args,
        "sandbox": sandbox,
        "timeout_seconds": timeout_seconds,
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
        "response_contract": response_contract,
        "auth_preserved": bool(auth_files_copied),
        "auth_file_kinds": sorted(auth_files_copied),
        "mcp_servers": normalized_mcp_servers,
        "serena": {
            "enabled": factors.semantic_access_enabled,
            "isolated_session": factors.semantic_access_enabled,
            "project": "<snapshot-repo>" if factors.semantic_access_enabled else "",
        },
        "router_policy": router_policy,
        "max_raw_output_bytes": route_profile.max_raw_output_bytes,
        "route_profile_hash": route_profile_hash(route_profile),
    }
    config_hash = stable_json_sha256(effective_config)
    config_overrides = [
        f"mcp_servers={_toml_value(runtime_mcp_servers)}",
        f"model={_toml_value(model_id)}",
    ]
    if reasoning_effort:
        config_overrides.append(f"model_reasoning_effort={_toml_value(reasoning_effort)}")
    environment = HermeticAgentEnvironment(
        agent_id=agent_profile.agent_id,
        profile_id=route_profile.profile_id,
        codex_home=str(codex_home.resolve()),
        semantic_session_home=str(semantic_home.resolve()),
        semantic_access_enabled=factors.semantic_access_enabled,
        routing_discipline_enabled=factors.routing_discipline_enabled,
        model_id=model_id,
        reasoning_effort=reasoning_effort,
        sandbox=sandbox,
        codex_config_overrides=config_overrides,
        env={
            "CODEX_HOME": str(codex_home.resolve()),
            "RARB_HERMETIC_AGENT_HOME": "1",
            "RARB_SEMANTIC_ACCESS_ENABLED": "1" if factors.semantic_access_enabled else "0",
            "RARB_ROUTING_DISCIPLINE_ENABLED": "1" if factors.routing_discipline_enabled else "0",
        },
        effective_config=effective_config,
        effective_config_sha256=config_hash,
        auth_files_copied=auth_files_copied,
        hard_controls=[
            "codex_fresh_home",
            *([] if not auth_files_copied else ["codex_auth_preserved"]),
            "codex_ignore_user_config",
            "codex_ignore_rules",
            "codex_plugins_disabled",
            "codex_controlled_mcp_servers",
        ],
        weak_controls=[] if auth_files_copied else ["codex_auth_not_found"],
    )
    to_json_file(out / "effective-agent-config.json", effective_config)
    (out / "effective-agent-config.sha256").write_text(config_hash + "\n", encoding="utf-8")
    to_json_file(
        out / "treatment-diff.json",
        {
            "profile_id": route_profile.profile_id,
            "semantic_access_enabled": factors.semantic_access_enabled,
            "routing_discipline_enabled": factors.routing_discipline_enabled,
            "controlled_fields": [
                "semantic_access_enabled",
                "mcp_servers",
                "serena",
                "routing_discipline_enabled",
                "router_policy",
                "high_fanout_policy",
                "max_raw_output_bytes",
            ],
            "effective_config_sha256": config_hash,
        },
    )
    to_json_file(out / "hermetic-agent-environment.json", asdict(environment))
    return environment
