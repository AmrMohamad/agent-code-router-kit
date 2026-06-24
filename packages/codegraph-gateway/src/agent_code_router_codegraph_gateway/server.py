from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from agent_code_router_codegraph_gateway.budgets import MAX_CHILD_CALLS_PER_GATEWAY_CALL, TOOL_BUDGETS
from agent_code_router_codegraph_gateway.child_session import CodeGraphChildSession, ProviderCompatibilityError, ProviderNotReadyError
from agent_code_router_codegraph_gateway.config import SERVER_INSTRUCTIONS, GatewayConfig, parse_args
from agent_code_router_codegraph_gateway.contracts import (
    ARCHITECTURE_INPUT_SCHEMA,
    EXPAND_INPUT_SCHEMA,
    IMPACT_INPUT_SCHEMA,
    TRACE_INPUT_SCHEMA,
    Freshness,
)
from agent_code_router_codegraph_gateway.evidence_store import EvidenceStore, ScopeBudgetExceeded, UnknownScope, scope_key
from agent_code_router_codegraph_gateway.freshness import FreshnessDecision, apply_freshness_policy
from agent_code_router_codegraph_gateway.normalizer import normalize_gateway_result, now_duration_ms
from agent_code_router_codegraph_gateway.policy import (
    classify_graph_request,
    ensure_evidence_id_count,
    ensure_focus_path_count,
    ensure_symbol_length,
    validate_architecture_input,
    validate_expand_input,
    validate_impact_input,
    validate_trace_input,
)
from agent_code_router_codegraph_gateway.security import ensure_repo_root, normalize_focus_paths, repo_relative_path
from agent_code_router_codegraph_gateway.telemetry import TelemetryWriter


TOOL_DEFINITIONS = [
    types.Tool(
        name="architecture_context",
        description="Return compact repository architecture or mobile-bridge discovery evidence.",
        inputSchema=ARCHITECTURE_INPUT_SCHEMA,
    ),
    types.Tool(
        name="trace_code_flow",
        description="Trace bounded source-code flow between known points.",
        inputSchema=TRACE_INPUT_SCHEMA,
    ),
    types.Tool(
        name="impact_scope",
        description="Return likely static source-level impact around a symbol or file.",
        inputSchema=IMPACT_INPUT_SCHEMA,
    ),
    types.Tool(
        name="expand_evidence",
        description="Expand only source anchors returned by a previous gateway scope.",
        inputSchema=EXPAND_INPUT_SCHEMA,
    ),
]


@dataclass
class GatewayApp:
    config: GatewayConfig
    telemetry: TelemetryWriter

    def __post_init__(self) -> None:
        self.config = GatewayConfig(
            repo_root=ensure_repo_root(self.config.repo_root),
            codegraph_bin=self.config.codegraph_bin,
            telemetry_path=self.config.telemetry_path,
            startup_timeout_sec=self.config.startup_timeout_sec,
            tool_timeout_sec=self.config.tool_timeout_sec,
            compat_manifest_path=self.config.compat_manifest_path,
            fake_provider_command=self.config.fake_provider_command,
            fake_provider_args=self.config.fake_provider_args,
        )
        self.child = CodeGraphChildSession(self.config, self.telemetry)
        self.store = EvidenceStore()

    def _wrong_route(self, *, intent: str, reason: str, tool_family: str) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "status": "wrong_route",
            "provider": "codegraph",
            "intent": intent,
            "scope_id": "",
            "proof_level": "discovery",
            "freshness": Freshness(status="unknown", index_present=False).as_dict(),
            "summary": [reason],
            "anchors": [],
            "relationships": [],
            "uncertainties": [],
            "recommended_next_step": {"tool_family": tool_family, "reason": reason},
            "budget": {"max_bytes": 0, "emitted_bytes": 0, "truncated": False},
            "telemetry": {"child_tool_calls": 0, "duration_ms": 0, "parse_quality": "none"},
        }
        return payload

    def _not_ready(self, *, intent: str, reason: str) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "status": "not_ready",
            "provider": "codegraph",
            "intent": intent,
            "scope_id": "",
            "proof_level": "discovery",
            "freshness": Freshness(status="unknown", index_present=False, detail=reason).as_dict(),
            "summary": ["CodeGraph is not ready for this repository."],
            "anchors": [],
            "relationships": [],
            "uncertainties": [reason],
            "recommended_next_step": {
                "tool_family": "existing_router",
                "reason": "Use rg for discovery or Serena/LSP for known symbols.",
            },
            "budget": {"max_bytes": 0, "emitted_bytes": 0, "truncated": False},
            "telemetry": {"child_tool_calls": 0, "duration_ms": 0, "parse_quality": "none"},
        }
        return payload

    def _blocked(self, *, intent: str, freshness: Freshness, detail: str, scope_id: str = "") -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "status": "blocked_graph_evidence",
            "provider": "codegraph",
            "intent": intent,
            "scope_id": scope_id,
            "proof_level": "discovery",
            "freshness": freshness.as_dict(),
            "summary": ["CodeGraph evidence was blocked by freshness policy."],
            "anchors": [],
            "relationships": [],
            "uncertainties": [detail],
            "recommended_next_step": {
                "tool_family": "existing_router",
                "reason": "Use direct file reads, rg/fd, or Serena/LSP until the graph is current.",
            },
            "budget": {"max_bytes": 0, "emitted_bytes": 0, "truncated": False},
            "telemetry": {"child_tool_calls": 0, "duration_ms": 0, "parse_quality": "none"},
        }
        return payload

    def _anchors_touch_pending_files(self, result: dict[str, Any], freshness: Freshness) -> bool:
        if freshness.status != "partially_stale":
            return False
        pending: set[str] = set()
        for path in freshness.pending_files:
            if not path or path == "<unknown>":
                return True
            try:
                pending.add(repo_relative_path(self.config.repo_root, path))
            except ValueError:
                return True
        anchor_paths = {str(anchor.get("path", "")) for anchor in result.get("anchors", []) if isinstance(anchor, dict)}
        return bool(anchor_paths & pending)

    def _scope_limit_result(self, *, intent: str, detail: str, scope_id: str = "") -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "blocked_graph_evidence",
            "provider": "codegraph",
            "intent": intent,
            "scope_id": scope_id,
            "proof_level": "discovery",
            "freshness": Freshness(status="unknown", index_present=False, detail=detail).as_dict(),
            "summary": ["CodeGraph scope budget blocked additional graph exploration."],
            "anchors": [],
            "relationships": [],
            "uncertainties": [detail],
            "recommended_next_step": {
                "tool_family": "serena_lsp",
                "reason": "Use Serena/LSP or focused source reads instead of another graph expansion.",
            },
            "budget": {"max_bytes": 0, "emitted_bytes": 0, "truncated": False},
            "telemetry": {"child_tool_calls": 0, "duration_ms": 0, "parse_quality": "none"},
        }

    async def _prepare_graph(self, intent: str) -> tuple[Freshness | None, FreshnessDecision | None, str | None]:
        try:
            prepared = await self.child.prepare()
        except (ProviderNotReadyError, ProviderCompatibilityError) as exc:
            return None, None, str(exc)
        freshness = Freshness(
            status=str(prepared.freshness_payload["status"]),
            index_present=bool(prepared.freshness_payload["index_present"]),
            pending_files=[str(item) for item in prepared.freshness_payload.get("pending_files", [])],
            worktree_mismatch=bool(prepared.freshness_payload.get("worktree_mismatch", False)),
            detail=str(prepared.freshness_payload.get("detail", "")),
        )
        return freshness, apply_freshness_policy(intent, freshness), None

    async def _call_child(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return await self.child.call_tool(tool_name, arguments)

    async def _architecture_context(self, arguments: dict[str, Any], *, started_at: float) -> dict[str, Any]:
        errors = validate_architecture_input(arguments)
        if errors:
            raise ValueError("; ".join(errors))
        question = str(arguments["question"])
        decision = classify_graph_request(question)
        if not decision.allowed:
            return self._wrong_route(intent=str(arguments["intent"]), reason=decision.reason, tool_family=decision.recommended_tool_family)
        focus_paths = normalize_focus_paths(self.config.repo_root, list(arguments.get("focus_paths", []) or []))
        ensure_focus_path_count(focus_paths)
        requested_intent = str(arguments["intent"])
        freshness, policy, not_ready_reason = await self._prepare_graph(requested_intent)
        if freshness is None or policy is None:
            return self._not_ready(intent=requested_intent, reason=not_ready_reason or "codegraph binary not found")
        if not policy.allowed:
            return self._blocked(intent=requested_intent, freshness=freshness, detail=policy.detail)
        scope = self.store.get_or_create_scope(
            intent=requested_intent,
            scope_key_value=scope_key(
                "architecture_context",
                {"intent": arguments["intent"], "question": question, "focus_paths": focus_paths, "detail": arguments.get("detail", "summary")},
            )
        )
        try:
            self.store.ensure_can_call(scope.scope_id)
            max_bytes = self.store.remaining_bytes(scope.scope_id, tool_max_bytes=TOOL_BUDGETS["architecture_context"].max_bytes)
        except ScopeBudgetExceeded as exc:
            return self._scope_limit_result(intent=requested_intent, detail=str(exc), scope_id=scope.scope_id)
        raw = await self._call_child(
            "codegraph_explore",
            {"question": question, "focus_paths": focus_paths, "detail": arguments.get("detail", "summary")},
        )
        result = normalize_gateway_result(
            tool_name="architecture_context",
            intent=str(arguments["intent"]),
            scope_id=scope.scope_id,
            freshness=freshness,
            raw_result=raw,
            child_tool_calls=1,
            duration_ms=now_duration_ms(started_at),
            recommended_tool_family="serena_lsp",
            recommended_reason="Verify important symbols and implementations with Serena/LSP before making semantic claims.",
            max_bytes=max_bytes,
            repo_root=self.config.repo_root,
        )
        if self._anchors_touch_pending_files(result, freshness):
            blocked = self._blocked(
                intent=requested_intent,
                freshness=freshness,
                detail="Pending files overlap returned graph anchors, so partial graph evidence is blocked.",
                scope_id=scope.scope_id,
            )
            self.store.register_result(scope.scope_id, emitted_bytes=0, anchors=[])
            self.telemetry.emit("gateway_tool_completed", tool="architecture_context", scope_id=scope.scope_id, emitted_bytes=0, child_tool_calls=1)
            return blocked
        self.store.register_result(scope.scope_id, emitted_bytes=int(result["budget"]["emitted_bytes"]), anchors=list(result["anchors"]))
        self.telemetry.emit("gateway_tool_completed", tool="architecture_context", scope_id=scope.scope_id, emitted_bytes=result["budget"]["emitted_bytes"], child_tool_calls=1)
        return result

    async def _trace_code_flow(self, arguments: dict[str, Any], *, started_at: float) -> dict[str, Any]:
        errors = validate_trace_input(arguments)
        if errors:
            raise ValueError("; ".join(errors))
        start = str(arguments["start"])
        ensure_symbol_length(start, "start")
        if arguments.get("end"):
            ensure_symbol_length(str(arguments["end"]), "end")
        freshness, policy, not_ready_reason = await self._prepare_graph("code_flow")
        if freshness is None or policy is None:
            return self._not_ready(intent="code_flow", reason=not_ready_reason or "codegraph binary not found")
        if not policy.allowed:
            return self._blocked(intent="code_flow", freshness=freshness, detail=policy.detail)
        scope = self.store.get_or_create_scope(
            intent="code_flow",
            scope_key_value=scope_key(
                "trace_code_flow",
                {
                    "start": start,
                    "end": str(arguments.get("end", "")),
                    "direction": str(arguments.get("direction", "forward")),
                    "max_hops": int(arguments.get("max_hops", 4)),
                },
            ),
        )
        try:
            self.store.ensure_can_call(scope.scope_id)
            max_bytes = self.store.remaining_bytes(scope.scope_id, tool_max_bytes=TOOL_BUDGETS["trace_code_flow"].max_bytes)
        except ScopeBudgetExceeded as exc:
            return self._scope_limit_result(intent="code_flow", detail=str(exc), scope_id=scope.scope_id)
        child_calls = 0
        resolution = await self._call_child("codegraph_search", {"query": start})
        child_calls += 1
        raw = await self._call_child(
            "codegraph_explore",
            {
                "start": start,
                "end": arguments.get("end", ""),
                "direction": arguments.get("direction", "forward"),
                "max_hops": arguments.get("max_hops", 4),
                "resolution": resolution,
            },
        )
        child_calls += 1
        if child_calls > MAX_CHILD_CALLS_PER_GATEWAY_CALL:
            raise ValueError("child call budget exceeded")
        result = normalize_gateway_result(
            tool_name="trace_code_flow",
            intent="code_flow",
            scope_id=scope.scope_id,
            freshness=freshness,
            raw_result=raw,
            child_tool_calls=child_calls,
            duration_ms=now_duration_ms(started_at),
            recommended_tool_family="serena_lsp",
            recommended_reason="Confirm call identity and concrete implementations with Serena/LSP.",
            max_bytes=max_bytes,
            repo_root=self.config.repo_root,
        )
        self.store.register_result(scope.scope_id, emitted_bytes=int(result["budget"]["emitted_bytes"]), anchors=list(result["anchors"]))
        self.telemetry.emit("gateway_tool_completed", tool="trace_code_flow", scope_id=scope.scope_id, emitted_bytes=result["budget"]["emitted_bytes"], child_tool_calls=child_calls)
        return result

    async def _impact_scope(self, arguments: dict[str, Any], *, started_at: float) -> dict[str, Any]:
        errors = validate_impact_input(arguments)
        if errors:
            raise ValueError("; ".join(errors))
        target = str(arguments["target"])
        ensure_symbol_length(target, "target")
        freshness, policy, not_ready_reason = await self._prepare_graph("impact")
        if freshness is None or policy is None:
            return self._not_ready(intent="impact", reason=not_ready_reason or "codegraph binary not found")
        if not policy.allowed:
            return self._blocked(intent="impact", freshness=freshness, detail=policy.detail)
        scope = self.store.get_or_create_scope(
            intent="impact",
            scope_key_value=scope_key(
                "impact_scope",
                {
                    "target": target,
                    "change_kind": str(arguments.get("change_kind", "unknown")),
                    "include_tests": bool(arguments.get("include_tests", False)),
                },
            )
        )
        try:
            self.store.ensure_can_call(scope.scope_id)
            max_bytes = self.store.remaining_bytes(scope.scope_id, tool_max_bytes=TOOL_BUDGETS["impact_scope"].max_bytes)
        except ScopeBudgetExceeded as exc:
            return self._scope_limit_result(intent="impact", detail=str(exc), scope_id=scope.scope_id)
        raw = await self._call_child(
            "codegraph_impact",
            {
                "target": target,
                "change_kind": arguments.get("change_kind", "unknown"),
                "include_tests": bool(arguments.get("include_tests", False)),
            },
        )
        result = normalize_gateway_result(
            tool_name="impact_scope",
            intent="impact",
            scope_id=scope.scope_id,
            freshness=freshness,
            raw_result=raw,
            child_tool_calls=1,
            duration_ms=now_duration_ms(started_at),
            recommended_tool_family="serena_lsp",
            recommended_reason="Use Serena/LSP for precise direct references and build/runtime tools for actual breakage proof.",
            max_bytes=max_bytes,
            repo_root=self.config.repo_root,
        )
        self.store.register_result(scope.scope_id, emitted_bytes=int(result["budget"]["emitted_bytes"]), anchors=list(result["anchors"]))
        self.telemetry.emit("gateway_tool_completed", tool="impact_scope", scope_id=scope.scope_id, emitted_bytes=result["budget"]["emitted_bytes"], child_tool_calls=1)
        return result

    async def _expand_evidence(self, arguments: dict[str, Any], *, started_at: float) -> dict[str, Any]:
        errors = validate_expand_input(arguments)
        if errors:
            raise ValueError("; ".join(errors))
        scope_id = str(arguments["scope_id"])
        evidence_ids = [str(item) for item in arguments["evidence_ids"]]
        ensure_evidence_id_count(evidence_ids)
        try:
            scope = self.store.ensure_can_call(scope_id)
            max_bytes = self.store.remaining_bytes(scope.scope_id, tool_max_bytes=TOOL_BUDGETS["expand_evidence"].max_bytes)
        except UnknownScope:
            raise ValueError("scope_id is unknown or expired")
        except ScopeBudgetExceeded as exc:
            return self._scope_limit_result(intent="unknown", detail=str(exc), scope_id=scope_id)
        freshness, policy, not_ready_reason = await self._prepare_graph(scope.intent)
        if freshness is None or policy is None:
            return self._not_ready(intent=scope.intent, reason=not_ready_reason or "codegraph binary not found")
        if not policy.allowed:
            return self._blocked(intent=scope.intent, freshness=freshness, detail=policy.detail)
        child_calls = 0
        expanded: list[dict[str, Any]] = []
        for evidence_key in evidence_ids:
            if evidence_key not in scope.anchors:
                raise ValueError(f"evidence id is not part of scope {scope_id}: {evidence_key}")
            anchor = scope.anchors[evidence_key]
            raw = await self._call_child(
                "codegraph_node",
                {
                    "path": anchor["path"],
                    "symbol": anchor["symbol"],
                    "line_start": anchor["line_start"],
                    "line_end": anchor["line_end"],
                },
            )
            child_calls += 1
            expanded.append(
                {
                    "evidence_id": evidence_key,
                    "path": anchor["path"],
                    "symbol": anchor["symbol"],
                    "line_start": anchor["line_start"],
                    "line_end": anchor["line_end"],
                    "provider_result": raw,
                }
            )
        if child_calls > MAX_CHILD_CALLS_PER_GATEWAY_CALL:
            raise ValueError("child call budget exceeded")
        result = normalize_gateway_result(
            tool_name="expand_evidence",
            intent=scope.intent,
            scope_id=scope.scope_id,
            freshness=freshness,
            raw_result={"summary": ["Expanded prior evidence anchors."], "anchors": list(scope.anchors.values()), "relationships": [], "uncertainties": [], "expanded": expanded},
            child_tool_calls=child_calls,
            duration_ms=now_duration_ms(started_at),
            recommended_tool_family="focused_source_read",
            recommended_reason="Read the returned anchored files directly for exact surrounding code.",
            max_bytes=max_bytes,
            repo_root=self.config.repo_root,
        )
        self.store.register_result(scope.scope_id, emitted_bytes=int(result["budget"]["emitted_bytes"]), anchors=list(result["anchors"]))
        self.telemetry.emit("gateway_tool_completed", tool="expand_evidence", scope_id=scope.scope_id, emitted_bytes=result["budget"]["emitted_bytes"], child_tool_calls=child_calls)
        return result


def build_server(config: GatewayConfig) -> Server:
    telemetry = TelemetryWriter(config.telemetry_path, repo_root=config.repo_root)
    app = GatewayApp(config=config, telemetry=telemetry)

    @asynccontextmanager
    async def lifespan(_: Server):
        try:
            yield None
        finally:
            await app.child.aclose()

    server = Server("agent-code-router-codegraph-gateway", instructions=SERVER_INSTRUCTIONS, lifespan=lifespan)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        started_at = anyio.current_time()
        try:
            if name == "architecture_context":
                return await app._architecture_context(arguments, started_at=float(started_at))
            if name == "trace_code_flow":
                return await app._trace_code_flow(arguments, started_at=float(started_at))
            if name == "impact_scope":
                return await app._impact_scope(arguments, started_at=float(started_at))
            if name == "expand_evidence":
                return await app._expand_evidence(arguments, started_at=float(started_at))
            raise ValueError(f"unknown tool: {name}")
        except Exception as exc:
            app.telemetry.emit("gateway_error", tool=name, error_kind=type(exc).__name__, error=str(exc))
            return {
                "schema_version": 1,
                "status": "error",
                "provider": "codegraph",
                "intent": "unknown",
                "scope_id": "",
                "proof_level": "discovery",
                "freshness": Freshness(status="unknown", index_present=False).as_dict(),
                "summary": ["Gateway execution failed."],
                "anchors": [],
                "relationships": [],
                "uncertainties": [str(exc)],
                "recommended_next_step": {
                    "tool_family": "existing_router",
                    "reason": "Use the existing router while the gateway failure is diagnosed.",
                },
                "budget": {"max_bytes": 0, "emitted_bytes": 0, "truncated": False},
                "telemetry": {"child_tool_calls": 0, "duration_ms": 0, "parse_quality": "none"},
            }
    return server


def main(argv: list[str] | None = None) -> int:
    config = parse_args(argv)
    server = build_server(config)

    async def runner() -> None:
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    anyio.run(runner)
    return 0
