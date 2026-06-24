from __future__ import annotations

import re
from dataclasses import dataclass

from agent_code_router_codegraph_gateway.budgets import MAX_EXPANDED_EVIDENCE_IDS, MAX_FOCUS_PATHS, MAX_QUESTION_CHARS, MAX_SYMBOL_CHARS
from agent_code_router_codegraph_gateway.contracts import (
    ARCHITECTURE_INPUT_SCHEMA,
    EXPAND_INPUT_SCHEMA,
    IMPACT_INPUT_SCHEMA,
    TRACE_INPUT_SCHEMA,
    validate_minimal_schema,
)


LITERAL_PATTERNS = [
    re.compile(r"\"[^\"]+\""),
    re.compile(r"'[^']+'"),
    re.compile(r"/api/[A-Za-z0-9/_-]+"),
]
SEMANTIC_PATTERNS = [re.compile(r"\bdefinition\b", re.I), re.compile(r"\breferences?\b", re.I), re.compile(r"\brename\b", re.I), re.compile(r"\btype of\b", re.I)]
STRUCTURAL_PATTERNS = [re.compile(r"\bsyntax\b", re.I), re.compile(r"\bmigration\b", re.I), re.compile(r"\baudit\b", re.I)]
RUNTIME_PATTERNS = [re.compile(r"\bbuild\b", re.I), re.compile(r"\btest\b", re.I), re.compile(r"\bcrash\b", re.I), re.compile(r"\bsimulator\b", re.I), re.compile(r"\bruntime\b", re.I)]
ARCHITECTURE_PATTERNS = [
    re.compile(r"\bhow does\b", re.I),
    re.compile(r"\btrace\b", re.I),
    re.compile(r"\bflow\b", re.I),
    re.compile(r"\btravel through\b", re.I),
    re.compile(r"\barchitecture\b", re.I),
    re.compile(r"\bsubsystem\b", re.I),
    re.compile(r"\bimpact\b", re.I),
    re.compile(r"\bbridge\b", re.I),
    re.compile(r"\bwhich callers?\b", re.I),
    re.compile(r"\bwhich components?\b", re.I),
    re.compile(r"\bwhat calls\b", re.I),
]
LITERAL_SEARCH_PATTERNS = [
    re.compile(r"\bwhere is\b", re.I),
    re.compile(r"\bfind\b", re.I),
    re.compile(r"\bsearch\b", re.I),
    re.compile(r"\bgrep\b", re.I),
    re.compile(r"\boccurr", re.I),
    re.compile(r"\bused\b", re.I),
    re.compile(r"\busage\b", re.I),
    re.compile(r"\bliteral\b", re.I),
    re.compile(r"\bstring\b", re.I),
    re.compile(r"\bresource key\b", re.I),
    re.compile(r"\bendpoint\b", re.I),
]


@dataclass(frozen=True)
class RouteDecision:
    allowed: bool
    status: str
    recommended_tool_family: str
    reason: str


def validate_architecture_input(payload: dict[str, object]) -> list[str]:
    return validate_minimal_schema(payload, ARCHITECTURE_INPUT_SCHEMA)


def validate_trace_input(payload: dict[str, object]) -> list[str]:
    return validate_minimal_schema(payload, TRACE_INPUT_SCHEMA)


def validate_impact_input(payload: dict[str, object]) -> list[str]:
    return validate_minimal_schema(payload, IMPACT_INPUT_SCHEMA)


def validate_expand_input(payload: dict[str, object]) -> list[str]:
    return validate_minimal_schema(payload, EXPAND_INPUT_SCHEMA)


def classify_graph_request(text: str) -> RouteDecision:
    stripped = text.strip()
    if len(stripped) > MAX_QUESTION_CHARS:
        return RouteDecision(False, "wrong_route", "input_validation", "question exceeds maximum length")
    has_architecture_signal = any(pattern.search(stripped) for pattern in ARCHITECTURE_PATTERNS)
    has_literal_token = any(pattern.search(stripped) for pattern in LITERAL_PATTERNS)
    has_literal_search_signal = any(pattern.search(stripped) for pattern in LITERAL_SEARCH_PATTERNS)
    if any(pattern.search(stripped) for pattern in RUNTIME_PATTERNS):
        return RouteDecision(False, "wrong_route", "build_runtime", "runtime or build proof belongs to runtime tools")
    if any(pattern.search(stripped) for pattern in SEMANTIC_PATTERNS):
        return RouteDecision(False, "wrong_route", "serena_lsp", "definition/reference/type questions belong to Serena/LSP")
    if any(pattern.search(stripped) for pattern in STRUCTURAL_PATTERNS):
        return RouteDecision(False, "wrong_route", "ast_grep", "syntax-shaped work belongs to ast-grep")
    if has_architecture_signal:
        return RouteDecision(True, "ok", "codegraph", "architecture/flow/impact request accepted")
    if has_literal_token and has_literal_search_signal:
        return RouteDecision(False, "wrong_route", "rg_fd", "quoted literals, endpoints, and keys belong to rg/fd")
    return RouteDecision(True, "ok", "codegraph", "architecture/flow/impact request accepted")


def ensure_evidence_id_count(ids: list[str]) -> None:
    if not ids or len(ids) > MAX_EXPANDED_EVIDENCE_IDS:
        raise ValueError("expand_evidence requires one or two evidence ids")


def ensure_symbol_length(value: str, field_name: str) -> None:
    if len(value) > MAX_SYMBOL_CHARS:
        raise ValueError(f"{field_name} exceeds maximum length")


def ensure_focus_path_count(values: list[str]) -> None:
    if len(values) > MAX_FOCUS_PATHS:
        raise ValueError("focus_paths exceeds maximum count")
