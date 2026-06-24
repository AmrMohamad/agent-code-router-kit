from __future__ import annotations

import json
from dataclasses import dataclass


ARCHITECTURE_MAX_BYTES = 4000
FLOW_MAX_BYTES = 3500
IMPACT_MAX_BYTES = 3500
EXPAND_MAX_BYTES = 2500
SCOPE_MAX_BYTES = 6000
MAX_GATEWAY_CALLS_PER_SCOPE = 2
MAX_CHILD_CALLS_PER_GATEWAY_CALL = 2
MAX_FILES = 5
MAX_ANCHORS = 8
MAX_RELATIONSHIPS = 12
MAX_EXPANDED_EVIDENCE_IDS = 2
MAX_ACTIVE_SCOPES = 16
SCOPE_TTL_SECONDS = 600
STARTUP_TIMEOUT_SECONDS = 20
TOOL_TIMEOUT_SECONDS = 40
FRESHNESS_RETRY_WAIT_SECONDS = 2.5
MAX_QUESTION_CHARS = 1000
MAX_SYMBOL_CHARS = 256
MAX_FOCUS_PATHS = 3


@dataclass(frozen=True)
class ToolBudget:
    tool_name: str
    max_bytes: int


TOOL_BUDGETS = {
    "architecture_context": ToolBudget("architecture_context", ARCHITECTURE_MAX_BYTES),
    "trace_code_flow": ToolBudget("trace_code_flow", FLOW_MAX_BYTES),
    "impact_scope": ToolBudget("impact_scope", IMPACT_MAX_BYTES),
    "expand_evidence": ToolBudget("expand_evidence", EXPAND_MAX_BYTES),
}


def utf8_size(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8"))
