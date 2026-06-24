from __future__ import annotations

import asyncio
import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class GatewayServerTests(unittest.TestCase):
    def test_wrong_route_does_not_require_provider(self) -> None:
        async def runner() -> None:
            params = StdioServerParameters(
                command=sys.executable,
                args=[
                    "-m",
                    "agent_code_router_codegraph_gateway",
                    "--repo",
                    ".",
                ],
                env={},
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "architecture_context",
                        arguments={"question": "\"/api/login\" usage", "intent": "architecture"},
                    )
                    payload = result.structuredContent
                    self.assertEqual(payload["status"], "wrong_route")

        asyncio.run(runner())


if __name__ == "__main__":
    unittest.main()
