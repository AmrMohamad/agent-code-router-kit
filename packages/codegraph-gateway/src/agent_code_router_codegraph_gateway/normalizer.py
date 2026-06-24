from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from agent_code_router_codegraph_gateway.budgets import MAX_ANCHORS, MAX_EXPANDED_EVIDENCE_IDS, MAX_FILES, MAX_RELATIONSHIPS, TOOL_BUDGETS, utf8_size
from agent_code_router_codegraph_gateway.contracts import ALLOWED_CONFIDENCE, Freshness, Relationship, SourceAnchor
from agent_code_router_codegraph_gateway.evidence_store import evidence_id


def _allowed_confidence(value: object) -> str:
    if isinstance(value, str) and value in ALLOWED_CONFIDENCE:
        return value
    return "unknown"


def _repo_relative_path(path: str, repo_root: Path | None) -> str:
    if repo_root is None:
        return path
    if not path:
        raise ValueError("empty path")
    root = repo_root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    relative = candidate.resolve().relative_to(root)
    return relative.as_posix()


def _text_blocks(raw_result: Any) -> list[str]:
    if raw_result is None:
        return []
    if isinstance(raw_result, str):
        return [raw_result]
    if isinstance(raw_result, dict):
        texts: list[str] = []
        content = raw_result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(str(item.get("text", "")))
        if "text" in raw_result:
            texts.append(str(raw_result["text"]))
        return [item for item in texts if item]
    return [str(raw_result)]


def _provider_payload(raw_result: Any) -> dict[str, Any] | None:
    if isinstance(raw_result, dict):
        if isinstance(raw_result.get("structuredContent"), dict):
            return dict(raw_result["structuredContent"])
        if any(key in raw_result for key in ("summary", "anchors", "relationships")):
            return dict(raw_result)
    for block in _text_blocks(raw_result):
        stripped = block.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_anchor(raw: dict[str, Any], *, repo_root: Path | None) -> tuple[SourceAnchor, set[str]] | None:
    try:
        path = _repo_relative_path(str(raw.get("path", "")), repo_root)
    except (ValueError, RuntimeError):
        return None
    line_start = int(raw.get("line_start", raw.get("start_line", 1)))
    line_end = int(raw.get("line_end", raw.get("end_line", line_start)))
    symbol = str(raw.get("symbol", raw.get("name", path)))
    anchor = SourceAnchor(
        id=evidence_id(path=path, line_start=line_start, line_end=line_end, symbol=symbol),
        path=path,
        line_start=line_start,
        line_end=line_end,
        symbol=symbol,
        role=str(raw.get("role", "context")),
        confidence=_allowed_confidence(raw.get("confidence")),
    )
    provider_keys = {
        anchor.id,
        f"path:{path}",
        f"symbol:{symbol}",
        f"path_symbol:{path}:{symbol}",
    }
    for key_name in ("id", "node_id", "provider_id"):
        if raw.get(key_name):
            provider_keys.add(str(raw[key_name]))
    return anchor, provider_keys


def _resolve_relationship_endpoint(
    raw: dict[str, Any],
    *,
    direct_keys: tuple[str, ...],
    symbol_keys: tuple[str, ...],
    path_keys: tuple[str, ...],
    mapping: dict[str, str],
    repo_root: Path | None,
) -> str | None:
    candidates: list[str] = []
    for key in direct_keys:
        value = raw.get(key)
        if value:
            candidates.append(str(value))
    symbol_value = next((str(raw[key]) for key in symbol_keys if raw.get(key)), "")
    path_value = next((str(raw[key]) for key in path_keys if raw.get(key)), "")
    if path_value:
        try:
            path_value = _repo_relative_path(path_value, repo_root)
        except (ValueError, RuntimeError):
            path_value = ""
    if symbol_value and path_value:
        candidates.append(f"path_symbol:{path_value}:{symbol_value}")
    if symbol_value:
        candidates.append(f"symbol:{symbol_value}")
    if path_value:
        candidates.append(f"path:{path_value}")
    for candidate in candidates:
        if candidate in mapping:
            return mapping[candidate]
    return None


def _normalize_relationship(raw: dict[str, Any], endpoint_mapping: dict[str, str], *, repo_root: Path | None) -> Relationship | None:
    from_id = _resolve_relationship_endpoint(
        raw,
        direct_keys=("from", "from_id", "source", "caller"),
        symbol_keys=("from_symbol", "source_symbol", "caller_symbol"),
        path_keys=("from_path", "source_path", "caller_path"),
        mapping=endpoint_mapping,
        repo_root=repo_root,
    )
    to_id = _resolve_relationship_endpoint(
        raw,
        direct_keys=("to", "to_id", "target", "callee"),
        symbol_keys=("to_symbol", "target_symbol", "callee_symbol"),
        path_keys=("to_path", "target_path", "callee_path"),
        mapping=endpoint_mapping,
        repo_root=repo_root,
    )
    if from_id is None or to_id is None:
        return None
    return Relationship(
        from_id=from_id,
        relation=str(raw.get("relation", "related_to")),
        to_id=to_id,
        confidence=_allowed_confidence(raw.get("confidence")),
        provenance=str(raw.get("provenance", "source")),
    )


def _cap_files(anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_files: set[str] = set()
    capped: list[dict[str, Any]] = []
    for anchor in anchors:
        path = str(anchor["path"])
        if path not in allowed_files and len(allowed_files) >= MAX_FILES:
            continue
        allowed_files.add(path)
        capped.append(anchor)
    return capped


def _shrink_summary(summary: list[str], *, max_items: int = 3) -> list[str]:
    return [item[:200] for item in summary[:max_items]]


def _normalize_expanded_evidence(items: list[dict[str, Any]], *, repo_root: Path | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items[:MAX_EXPANDED_EVIDENCE_IDS]:
        try:
            path = _repo_relative_path(str(item.get("path", "")), repo_root)
        except (ValueError, RuntimeError):
            continue
        symbol = str(item.get("symbol", path))
        line_start = int(item.get("line_start", 1))
        line_end = int(item.get("line_end", line_start))
        provider_result = item.get("provider_result")
        payload = _provider_payload(provider_result)
        excerpt = ""
        summary = ""
        if payload is not None:
            summaries = [str(value) for value in payload.get("summary", [])]
            summary = summaries[0][:160] if summaries else ""
            excerpt = json.dumps(payload, sort_keys=True)[:400]
        else:
            excerpt = "\n".join(_text_blocks(provider_result))[:400]
        normalized.append(
            {
                "id": str(item.get("evidence_id", evidence_id(path=path, line_start=line_start, line_end=line_end, symbol=symbol))),
                "path": path,
                "symbol": symbol,
                "line_start": line_start,
                "line_end": line_end,
                "summary": summary,
                "bounded_excerpt": excerpt,
            }
        )
    return normalized


def enforce_budget(payload: dict[str, Any], max_bytes: int) -> tuple[dict[str, Any], bool]:
    bounded = deepcopy(payload)
    truncated = False
    while utf8_size(bounded) > max_bytes:
        truncated = True
        relationships = bounded.get("relationships", [])
        anchors = bounded.get("anchors", [])
        expanded_evidence = bounded.get("expanded_evidence", [])
        summary = bounded.get("summary", [])
        uncertainties = bounded.get("uncertainties", [])
        if relationships:
            relationships.pop()
            continue
        if anchors and expanded_evidence:
            anchors.pop()
            continue
        if expanded_evidence:
            expanded_evidence.pop()
            continue
        if anchors:
            anchors.pop()
            continue
        if len(summary) > 1:
            summary.pop()
            continue
        if summary and len(summary[0]) > 80:
            summary[0] = summary[0][:80]
            continue
        if uncertainties:
            uncertainties.pop()
            continue
        excerpt = bounded.get("bounded_excerpt", "")
        if excerpt and len(excerpt) > 80:
            bounded["bounded_excerpt"] = excerpt[:80]
            continue
        break
    bounded.setdefault("budget", {})
    bounded["budget"]["truncated"] = truncated
    bounded["budget"]["emitted_bytes"] = utf8_size(bounded)
    return bounded, truncated


def normalize_gateway_result(
    *,
    tool_name: str,
    intent: str,
    scope_id: str,
    freshness: Freshness,
    raw_result: Any,
    child_tool_calls: int,
    duration_ms: int,
    recommended_tool_family: str,
    recommended_reason: str,
    fallback_uncertainty: str | None = None,
    max_bytes: int | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    provider_payload = _provider_payload(raw_result)
    status = "ok"
    parse_quality = "complete"
    if provider_payload is None:
        status = "partial"
        parse_quality = "bounded_raw"
        provider_payload = {
            "summary": ["CodeGraph returned output that could not be fully normalized."],
            "anchors": [],
            "relationships": [],
            "uncertainties": [fallback_uncertainty or "The provider response format was not fully parseable."],
            "bounded_excerpt": "\n".join(_text_blocks(raw_result))[:800],
        }

    summary = _shrink_summary([str(item) for item in provider_payload.get("summary", [])] or ["No summary returned."])
    raw_anchors_with_refs = []
    for item in provider_payload.get("anchors", []):
        if not isinstance(item, dict):
            continue
        normalized_anchor = _normalize_anchor(item, repo_root=repo_root)
        if normalized_anchor is not None:
            raw_anchors_with_refs.append(normalized_anchor)
    deduped: dict[str, dict[str, Any]] = {}
    endpoint_mapping: dict[str, str] = {}
    for anchor, provider_refs in raw_anchors_with_refs:
        anchor_dict = anchor.as_dict()
        deduped[str(anchor_dict["id"])] = anchor_dict
        for provider_ref in provider_refs:
            endpoint_mapping[provider_ref] = str(anchor_dict["id"])
    anchors = list(deduped.values())[:MAX_ANCHORS]
    anchors = _cap_files(anchors)
    known_ids = {str(anchor["id"]) for anchor in anchors}
    endpoint_mapping = {key: value for key, value in endpoint_mapping.items() if value in known_ids}
    raw_relationships = []
    for item in provider_payload.get("relationships", []):
        if not isinstance(item, dict):
            continue
        relationship = _normalize_relationship(item, endpoint_mapping, repo_root=repo_root)
        if relationship is not None:
            raw_relationships.append(relationship.as_dict())
    relationships = raw_relationships[:MAX_RELATIONSHIPS]
    expanded_evidence = _normalize_expanded_evidence(
        [item for item in provider_payload.get("expanded_evidence", provider_payload.get("expanded", [])) if isinstance(item, dict)],
        repo_root=repo_root,
    )
    payload = {
        "schema_version": 1,
        "status": status,
        "provider": "codegraph",
        "intent": intent,
        "scope_id": scope_id,
        "proof_level": "discovery",
        "freshness": freshness.as_dict(),
        "summary": summary,
        "anchors": anchors,
        "relationships": relationships,
        "uncertainties": [str(item) for item in provider_payload.get("uncertainties", [])][:4],
        "recommended_next_step": {
            "tool_family": recommended_tool_family,
            "reason": recommended_reason,
        },
        "budget": {
            "max_bytes": max_bytes or TOOL_BUDGETS[tool_name].max_bytes,
            "emitted_bytes": 0,
            "truncated": False,
        },
        "telemetry": {
            "child_tool_calls": child_tool_calls,
            "duration_ms": duration_ms,
            "parse_quality": parse_quality,
        },
    }
    if expanded_evidence:
        payload["expanded_evidence"] = expanded_evidence
    if status == "partial":
        payload["bounded_excerpt"] = str(provider_payload.get("bounded_excerpt", ""))[:800]
    if tool_name == "impact_scope":
        payload["uncertainties"].insert(0, "This is potential static source impact, not proof of runtime breakage.")
    bounded, _ = enforce_budget(payload, max_bytes or TOOL_BUDGETS[tool_name].max_bytes)
    return bounded


def now_duration_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)
