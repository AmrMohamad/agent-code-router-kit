from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agent_code_router_codegraph_gateway.child_session import CodeGraphChildSession, ProviderCompatibilityError
from agent_code_router_codegraph_gateway.config import GatewayConfig
from agent_code_router_codegraph_gateway.telemetry import TelemetryWriter


FAKE_SERVER = Path(__file__).resolve().parent / "fakes" / "fake_codegraph_server.py"
COMPAT_MANIFEST = Path(__file__).resolve().parents[1] / "compat" / "codegraph-tools-v1.json"


class FakeServerTests(unittest.TestCase):
    def test_fake_server_lists_tools(self) -> None:
        async def runner() -> None:
            params = StdioServerParameters(command=sys.executable, args=[str(FAKE_SERVER), "--scenario", "normal"], env={})
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    self.assertIn("codegraph_explore", names)

        asyncio.run(runner())

    def test_child_session_detects_missing_tool(self) -> None:
        async def runner() -> None:
            config = GatewayConfig(
                repo_root=Path.cwd(),
                codegraph_bin="codegraph",
                telemetry_path=None,
                startup_timeout_sec=2,
                tool_timeout_sec=2,
                compat_manifest_path=COMPAT_MANIFEST,
                fake_provider_command=sys.executable,
                fake_provider_args=(str(FAKE_SERVER), "--scenario", "missing_tool"),
            )
            child = CodeGraphChildSession(config, TelemetryWriter(None))
            with self.assertRaises(ProviderCompatibilityError):
                await child.prepare()

        asyncio.run(runner())

    def test_child_session_detects_schema_drift(self) -> None:
        async def runner() -> None:
            config = GatewayConfig(
                repo_root=Path.cwd(),
                codegraph_bin="codegraph",
                telemetry_path=None,
                startup_timeout_sec=2,
                tool_timeout_sec=2,
                compat_manifest_path=COMPAT_MANIFEST,
                fake_provider_command=sys.executable,
                fake_provider_args=(str(FAKE_SERVER), "--scenario", "schema_drift"),
            )
            child = CodeGraphChildSession(config, TelemetryWriter(None))
            with self.assertRaises(ProviderCompatibilityError):
                await child.prepare()

        asyncio.run(runner())


if __name__ == "__main__":
    unittest.main()
