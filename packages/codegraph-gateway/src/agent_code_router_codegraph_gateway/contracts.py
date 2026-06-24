from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


ALLOWED_CONFIDENCE = {"extracted", "heuristic", "ambiguous", "unknown"}
ALLOWED_STATUSES = {
    "ok",
    "partial",
    "not_ready",
    "wrong_route",
    "blocked_graph_evidence",
    "error",
}
ALLOWED_INTENTS = {"architecture", "code_flow", "impact", "mobile_bridge"}


ARCHITECTURE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["question", "intent"],
    "properties": {
        "question": {"type": "string", "maxLength": 1000},
        "intent": {"type": "string", "enum": ["architecture", "mobile_bridge"]},
        "focus_paths": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
        "detail": {"type": "string", "enum": ["summary", "anchors"]},
    },
}

TRACE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["start"],
    "properties": {
        "start": {"type": "string", "maxLength": 256},
        "end": {"type": "string", "maxLength": 256},
        "direction": {"type": "string", "enum": ["forward", "backward", "both"]},
        "max_hops": {"type": "integer", "minimum": 1, "maximum": 6},
    },
}

IMPACT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["target"],
    "properties": {
        "target": {"type": "string", "maxLength": 256},
        "change_kind": {
            "type": "string",
            "enum": ["behavior", "signature", "deletion", "unknown"],
        },
        "include_tests": {"type": "boolean"},
    },
}

EXPAND_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scope_id", "evidence_ids"],
    "properties": {
        "scope_id": {"type": "string", "minLength": 1},
        "evidence_ids": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}},
    },
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "schema_version",
        "status",
        "provider",
        "intent",
        "scope_id",
        "proof_level",
        "freshness",
        "summary",
        "anchors",
        "relationships",
        "uncertainties",
        "recommended_next_step",
        "budget",
        "telemetry",
    ],
}


@dataclass(frozen=True)
class SourceAnchor:
    id: str
    path: str
    line_start: int
    line_end: int
    symbol: str
    role: str
    confidence: str = "unknown"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "symbol": self.symbol,
            "role": self.role,
            "confidence": self.confidence if self.confidence in ALLOWED_CONFIDENCE else "unknown",
        }


@dataclass(frozen=True)
class Relationship:
    from_id: str
    relation: str
    to_id: str
    confidence: str
    provenance: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_id,
            "relation": self.relation,
            "to": self.to_id,
            "confidence": self.confidence if self.confidence in ALLOWED_CONFIDENCE else "unknown",
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class Freshness:
    status: str
    index_present: bool
    pending_files: list[str] = field(default_factory=list)
    worktree_mismatch: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "index_present": self.index_present,
            "pending_files": list(self.pending_files),
            "worktree_mismatch": self.worktree_mismatch,
            "detail": self.detail,
        }


def validate_minimal_schema(payload: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = schema.get("required", [])
    for key in required:
        if key not in payload:
            errors.append(f"missing required field: {key}")
    properties = schema.get("properties", {})
    for key, rules in properties.items():
        if key not in payload:
            continue
        value = payload[key]
        expected_type = rules.get("type")
        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"{key} must be a string")
        elif expected_type == "integer" and not isinstance(value, int):
            errors.append(f"{key} must be an integer")
        elif expected_type == "boolean" and not isinstance(value, bool):
            errors.append(f"{key} must be a boolean")
        elif expected_type == "array" and not isinstance(value, list):
            errors.append(f"{key} must be an array")
        if isinstance(value, str):
            if "maxLength" in rules and len(value) > int(rules["maxLength"]):
                errors.append(f"{key} exceeds maxLength")
            if "minLength" in rules and len(value) < int(rules["minLength"]):
                errors.append(f"{key} is shorter than minLength")
        if isinstance(value, list):
            if "maxItems" in rules and len(value) > int(rules["maxItems"]):
                errors.append(f"{key} exceeds maxItems")
            if "minItems" in rules and len(value) < int(rules["minItems"]):
                errors.append(f"{key} is shorter than minItems")
        if "enum" in rules and value not in set(rules["enum"]):
            errors.append(f"{key} must be one of {rules['enum']}")
        if isinstance(value, int):
            if "minimum" in rules and value < int(rules["minimum"]):
                errors.append(f"{key} is below minimum")
            if "maximum" in rules and value > int(rules["maximum"]):
                errors.append(f"{key} exceeds maximum")
    return errors
