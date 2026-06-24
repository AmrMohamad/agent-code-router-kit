from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_code_router_codegraph_gateway.contracts import Freshness


@dataclass(frozen=True)
class FreshnessDecision:
    allowed: bool
    blocked_status: str | None
    detail: str


def parse_status_payload(payload: Any) -> Freshness:
    if isinstance(payload, dict):
        status = str(payload.get("status", "unknown"))
        pending = [str(item) for item in payload.get("pending_files", [])]
        return Freshness(
            status=status,
            index_present=bool(payload.get("index_present", False)),
            pending_files=pending,
            worktree_mismatch=bool(payload.get("worktree_mismatch", False)),
            detail=str(payload.get("detail", "")),
        )
    text = str(payload or "").strip().lower()
    if "missing" in text and "index" in text:
        return Freshness(status="stale", index_present=False, detail=text)
    if "pending" in text:
        return Freshness(status="partially_stale", index_present=True, pending_files=["<unknown>"], detail=text)
    if "current" in text or "ready" in text:
        return Freshness(status="current", index_present=True, detail=text)
    return Freshness(status="unknown", index_present=False, detail=text)


def apply_freshness_policy(intent: str, freshness: Freshness) -> FreshnessDecision:
    if freshness.status == "current":
        return FreshnessDecision(True, None, "")
    if freshness.status == "partially_stale":
        if intent in {"architecture", "mobile_bridge"}:
            return FreshnessDecision(True, None, "Architecture orientation proceeding with partial-staleness warning.")
        return FreshnessDecision(False, "blocked_graph_evidence", "Pending files make flow/impact evidence unreliable.")
    return FreshnessDecision(False, "blocked_graph_evidence", "CodeGraph index is stale or unknown.")
