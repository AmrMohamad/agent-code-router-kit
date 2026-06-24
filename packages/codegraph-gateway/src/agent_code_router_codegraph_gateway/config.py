from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from agent_code_router_codegraph_gateway.budgets import STARTUP_TIMEOUT_SECONDS, TOOL_TIMEOUT_SECONDS


SERVER_INSTRUCTIONS = (
    "Use this server only for repository architecture, source-flow, impact, and "
    "mobile-bridge discovery. Do not use it for literals, exact symbol identity, "
    "structural search, or build/runtime proof. Use at most two graph calls, then "
    "verify important symbols with Serena/LSP or focused source reads. Heuristic "
    "bridge edges are discovery only. Never present graph output as build or runtime proof."
)


@dataclass(frozen=True)
class GatewayConfig:
    repo_root: Path
    codegraph_bin: str
    telemetry_path: Path | None
    startup_timeout_sec: int
    tool_timeout_sec: int
    compat_manifest_path: Path
    fake_provider_command: str | None = None
    fake_provider_args: tuple[str, ...] = ()


def default_compat_manifest_path() -> Path:
    source_tree_path = Path(__file__).resolve().parents[2] / "compat" / "codegraph-tools-v1.json"
    if source_tree_path.exists():
        return source_tree_path
    return Path(str(files("agent_code_router_codegraph_gateway").joinpath("compat", "codegraph-tools-v1.json")))


def parse_args(argv: list[str] | None = None) -> GatewayConfig:
    parser = argparse.ArgumentParser(description="Bounded CodeGraph MCP gateway")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--codegraph-bin", default=os.environ.get("ACR_CODEGRAPH_BIN", "codegraph"))
    parser.add_argument("--telemetry-path", default=os.environ.get("ACR_CODEGRAPH_TELEMETRY_PATH", ""))
    parser.add_argument("--startup-timeout-sec", type=int, default=STARTUP_TIMEOUT_SECONDS)
    parser.add_argument("--tool-timeout-sec", type=int, default=TOOL_TIMEOUT_SECONDS)
    parser.add_argument("--provider-command", default=os.environ.get("ACR_CODEGRAPH_PROVIDER_COMMAND", ""))
    parser.add_argument("--provider-args", nargs=argparse.REMAINDER, default=None)
    args = parser.parse_args(argv)
    return GatewayConfig(
        repo_root=Path(args.repo).expanduser().resolve(),
        codegraph_bin=args.codegraph_bin,
        telemetry_path=Path(args.telemetry_path).expanduser().resolve() if args.telemetry_path else None,
        startup_timeout_sec=args.startup_timeout_sec,
        tool_timeout_sec=args.tool_timeout_sec,
        compat_manifest_path=default_compat_manifest_path(),
        fake_provider_command=args.provider_command or None,
        fake_provider_args=tuple(args.provider_args or ()),
    )
