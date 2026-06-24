from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_code_router_codegraph_gateway.config import GatewayConfig
from agent_code_router_codegraph_gateway.security import ensure_repo_root
from agent_code_router_codegraph_gateway.server import GatewayApp
from agent_code_router_codegraph_gateway.telemetry import TelemetryWriter


FAKE_SERVER = Path(__file__).resolve().parent / "fakes" / "fake_codegraph_server.py"
COMPAT_MANIFEST = Path(__file__).resolve().parents[1] / "compat" / "codegraph-tools-v1.json"


class GatewayAppTests(unittest.TestCase):
    def build_config(self, *, scenario: str, telemetry_path: Path | None = None) -> GatewayConfig:
        return GatewayConfig(
            repo_root=Path.cwd(),
            codegraph_bin="codegraph",
            telemetry_path=telemetry_path,
            startup_timeout_sec=2,
            tool_timeout_sec=2,
            compat_manifest_path=COMPAT_MANIFEST,
            fake_provider_command=sys.executable,
            fake_provider_args=(str(FAKE_SERVER), "--scenario", scenario),
        )

    def test_architecture_context_preserves_relationships(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="normal"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            result = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["relationships"]), 2)
            await app.child.aclose()

        asyncio.run(runner())

    def test_pending_freshness_blocks_architecture_when_anchors_touch_pending_files(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="pending_file"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            architecture = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            self.assertEqual(architecture["status"], "blocked_graph_evidence")
            self.assertIn("Pending files overlap", architecture["uncertainties"][0])
            await app.child.aclose()

        asyncio.run(runner())

    def test_pending_freshness_allows_architecture_when_pending_files_are_unrelated(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="pending_unrelated_file"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            architecture = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            flow = await app._trace_code_flow({"start": "CheckoutController.submit"}, started_at=0.0)
            self.assertEqual(architecture["status"], "ok")
            self.assertEqual(architecture["freshness"]["status"], "partially_stale")
            self.assertEqual(flow["status"], "blocked_graph_evidence")
            await app.child.aclose()

        asyncio.run(runner())

    def test_expand_evidence_returns_expanded_items(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="normal"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            result = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            scope_id = result["scope_id"]
            evidence_id = result["anchors"][0]["id"]
            expanded = await app._expand_evidence({"scope_id": scope_id, "evidence_ids": [evidence_id]}, started_at=0.0)
            self.assertEqual(expanded["status"], "ok")
            self.assertTrue(expanded["expanded_evidence"])
            await app.child.aclose()

        asyncio.run(runner())

    def test_expand_evidence_checks_freshness_instead_of_fabricating_current(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="pending_unrelated_file"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            result = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            expanded = await app._expand_evidence({"scope_id": result["scope_id"], "evidence_ids": [result["anchors"][0]["id"]]}, started_at=0.0)
            self.assertEqual(expanded["status"], "ok")
            self.assertEqual(expanded["freshness"]["status"], "partially_stale")
            await app.child.aclose()

        asyncio.run(runner())

    def test_expand_evidence_preserves_original_scope_intent(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="normal"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            result = await app._impact_scope({"target": "PaymentProvider", "change_kind": "signature"}, started_at=0.0)
            expanded = await app._expand_evidence({"scope_id": result["scope_id"], "evidence_ids": [result["anchors"][0]["id"]]}, started_at=0.0)
            self.assertEqual(expanded["status"], "ok")
            self.assertEqual(expanded["intent"], "impact")
            await app.child.aclose()

        asyncio.run(runner())

    def test_incompatible_provider_returns_not_ready(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="missing_tool"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            result = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            self.assertEqual(result["status"], "not_ready")
            await app.child.aclose()

        asyncio.run(runner())

    def test_scope_budget_blocks_third_call(self) -> None:
        async def runner() -> None:
            app = GatewayApp(config=self.build_config(scenario="normal"), telemetry=TelemetryWriter(None, repo_root=Path.cwd()))
            first = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            second = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            third = await app._architecture_context({"question": "How does checkout reach payments?", "intent": "architecture"}, started_at=0.0)
            self.assertEqual(first["status"], "ok")
            self.assertEqual(second["status"], "ok")
            self.assertEqual(third["status"], "blocked_graph_evidence")
            await app.child.aclose()

        asyncio.run(runner())

    def test_telemetry_sanitizes_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            telemetry_path = Path(raw) / "telemetry.jsonl"
            writer = TelemetryWriter(telemetry_path, repo_root=Path.cwd())
            writer.emit("child_start_requested", repo_root=str(Path.cwd()))
            payload = json.loads(telemetry_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertNotIn("repo_root", payload)
            self.assertIn("repository_id", payload)

    def test_telemetry_hashes_error_and_drops_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            telemetry_path = Path(raw) / "telemetry.jsonl"
            writer = TelemetryWriter(telemetry_path, repo_root=Path.cwd())
            writer.emit("gateway_error", error=f"failed in {Path.cwd() / 'src/private.py'}", traceback="raw traceback with source")
            payload = json.loads(telemetry_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("error_hash", payload)
            self.assertNotIn("error", payload)
            self.assertNotIn("traceback", payload)
            self.assertNotIn(str(Path.cwd()), json.dumps(payload))

    def test_allowed_repo_root_env_blocks_outside_roots(self) -> None:
        with tempfile.TemporaryDirectory() as allowed_raw, tempfile.TemporaryDirectory() as outside_raw:
            with mock.patch.dict(os.environ, {"ACR_ALLOWED_REPO_ROOT": allowed_raw}):
                self.assertEqual(ensure_repo_root(Path(allowed_raw)), Path(allowed_raw).resolve())
                with self.assertRaises(ValueError):
                    ensure_repo_root(Path(outside_raw))


if __name__ == "__main__":
    unittest.main()
