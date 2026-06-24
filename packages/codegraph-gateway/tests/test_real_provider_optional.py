from __future__ import annotations

import asyncio
import os
import shutil
import unittest
from pathlib import Path

from agent_code_router_codegraph_gateway.config import GatewayConfig
from agent_code_router_codegraph_gateway.server import GatewayApp
from agent_code_router_codegraph_gateway.telemetry import TelemetryWriter


COMPAT_MANIFEST = Path(__file__).resolve().parents[1] / "compat" / "codegraph-tools-v1.json"


@unittest.skipUnless(os.environ.get("ACR_CODEGRAPH_RUN_REAL_TESTS") == "1", "set ACR_CODEGRAPH_RUN_REAL_TESTS=1 to run real CodeGraph checks")
class RealProviderOptionalTests(unittest.TestCase):
    def test_real_provider_returns_bounded_result_or_not_ready(self) -> None:
        codegraph_bin = os.environ.get("ACR_CODEGRAPH_BIN") or shutil.which("codegraph")
        if not codegraph_bin:
            self.skipTest("codegraph executable is unavailable")

        async def runner() -> None:
            config = GatewayConfig(
                repo_root=Path.cwd(),
                codegraph_bin=codegraph_bin,
                telemetry_path=None,
                startup_timeout_sec=5,
                tool_timeout_sec=10,
                compat_manifest_path=COMPAT_MANIFEST,
            )
            app = GatewayApp(config=config, telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            result = await app._architecture_context({"question": "How does this repository route code understanding?", "intent": "architecture"}, started_at=0.0)
            self.assertIn(result["status"], {"ok", "partial", "not_ready", "blocked_graph_evidence"})
            self.assertLessEqual(int(result["budget"]["emitted_bytes"]), 4000)
            await app.child.aclose()

        asyncio.run(runner())


if __name__ == "__main__":
    unittest.main()
