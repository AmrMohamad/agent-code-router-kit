from __future__ import annotations

import asyncio
import json
import shutil
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_code_router_codegraph_gateway.budgets import FRESHNESS_RETRY_WAIT_SECONDS
from agent_code_router_codegraph_gateway.config import GatewayConfig
from agent_code_router_codegraph_gateway.freshness import parse_status_payload
from agent_code_router_codegraph_gateway.telemetry import TelemetryWriter


class ProviderNotReadyError(RuntimeError):
    pass


class ProviderCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedProvider:
    freshness_payload: dict[str, Any]
    freshness_status: Any


class CodeGraphChildSession:
    def __init__(self, config: GatewayConfig, telemetry: TelemetryWriter) -> None:
        self._config = config
        self._telemetry = telemetry
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._initialized = False
        self._required_tools = self._load_required_tools()
        self._required_input_schema_types, self._required_input_properties = self._load_schema_requirements()

    def _load_required_tools(self) -> list[str]:
        manifest = json.loads(self._config.compat_manifest_path.read_text(encoding="utf-8"))
        return [str(item) for item in manifest.get("required_tools", [])]

    def _load_schema_requirements(self) -> tuple[dict[str, str], dict[str, list[str]]]:
        manifest = json.loads(self._config.compat_manifest_path.read_text(encoding="utf-8"))
        return (
            {str(key): str(value) for key, value in manifest.get("required_input_schema_types", {}).items()},
            {str(key): [str(item) for item in value] for key, value in manifest.get("required_input_properties", {}).items()},
        )

    def _server_params(self) -> StdioServerParameters:
        if self._config.fake_provider_command:
            return StdioServerParameters(
                command=self._config.fake_provider_command,
                args=list(self._config.fake_provider_args),
                env={},
                cwd=str(self._config.repo_root),
            )
        resolved = shutil.which(self._config.codegraph_bin)
        if not resolved:
            raise ProviderNotReadyError("codegraph binary not found")
        return StdioServerParameters(
            command=resolved,
            args=["serve", "--mcp"],
            env={"PWD": str(self._config.repo_root)},
            cwd=str(self._config.repo_root),
        )

    async def prepare(self) -> PreparedProvider:
        if not self._initialized:
            await self._start()
        assert self._session is not None
        status_result = await asyncio.wait_for(self.call_tool("codegraph_status", {}), timeout=self._config.tool_timeout_sec)
        parsed = parse_status_payload(status_result)
        self._telemetry.emit("freshness_checked", freshness_status=parsed.status, pending_files=len(parsed.pending_files))
        if parsed.status == "partially_stale" and parsed.pending_files:
            await asyncio.sleep(min(FRESHNESS_RETRY_WAIT_SECONDS, max(0.1, self._config.tool_timeout_sec / 2)))
            status_result = await asyncio.wait_for(self.call_tool("codegraph_status", {}), timeout=self._config.tool_timeout_sec)
            parsed = parse_status_payload(status_result)
            self._telemetry.emit("freshness_checked", freshness_status=parsed.status, pending_files=len(parsed.pending_files))
        return PreparedProvider(freshness_payload=parsed.as_dict(), freshness_status=parsed)

    async def _start(self) -> None:
        self._telemetry.emit("child_start_requested", repo_root=str(self._config.repo_root))
        self._stack = AsyncExitStack()
        params = self._server_params()
        read_stream, write_stream = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
        await asyncio.wait_for(self._session.initialize(), timeout=self._config.startup_timeout_sec)
        tools = await asyncio.wait_for(self._session.list_tools(), timeout=self._config.tool_timeout_sec)
        available = {tool.name for tool in tools.tools}
        tool_map = {tool.name: tool for tool in tools.tools}
        missing = [tool for tool in self._required_tools if tool not in available]
        if missing:
            await self.aclose()
            raise ProviderCompatibilityError("missing required codegraph tools: " + ",".join(missing))
        for tool_name in self._required_tools:
            tool = tool_map[tool_name]
            input_schema = getattr(tool, "inputSchema", None) or {}
            required_type = self._required_input_schema_types.get(tool_name)
            if required_type and input_schema.get("type") != required_type:
                await self.aclose()
                raise ProviderCompatibilityError(f"incompatible input schema for {tool_name}: expected {required_type}")
            properties = input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
            missing_properties = [name for name in self._required_input_properties.get(tool_name, []) if name not in properties]
            if missing_properties:
                await self.aclose()
                raise ProviderCompatibilityError(
                    f"incompatible input schema for {tool_name}: missing properties {','.join(missing_properties)}"
                )
        self._initialized = True
        self._telemetry.emit("child_initialized", available_tools=sorted(available))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._initialized:
            await self._start()
        assert self._session is not None
        self._telemetry.emit("child_tool_called", tool=name)
        result = await asyncio.wait_for(self._session.call_tool(name, arguments=arguments), timeout=self._config.tool_timeout_sec)
        structured = getattr(result, "structuredContent", None)
        if structured:
            return structured
        content = []
        for item in getattr(result, "content", []):
            if getattr(item, "type", "") == "text":
                content.append({"type": "text", "text": getattr(item, "text", "")})
        return {"content": content, "is_error": getattr(result, "isError", False)}

    async def aclose(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._session = None
            self._initialized = False
            self._telemetry.emit("child_stopped")
