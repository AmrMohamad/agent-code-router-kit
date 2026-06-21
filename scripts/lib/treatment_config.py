from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, dataclass
from typing import Any

from scripts.lib.agent_session import RouteProfile


FACTORIAL_ARM_ORDER = [
    "A-search-only",
    "B-search-summary",
    "C-lsp-naive",
    "D-full-router",
]

FACTORIAL_COMPARISONS = [
    ("A-search-only", "B-search-summary"),
    ("A-search-only", "C-lsp-naive"),
    ("C-lsp-naive", "D-full-router"),
    ("B-search-summary", "D-full-router"),
    ("A-search-only", "D-full-router"),
]


@dataclass(frozen=True)
class TreatmentFactors:
    profile_id: str
    semantic_access_enabled: bool
    routing_discipline_enabled: bool


TREATMENT_FACTORS: dict[str, TreatmentFactors] = {
    "A-search-only": TreatmentFactors("A-search-only", False, False),
    "B-search-summary": TreatmentFactors("B-search-summary", False, True),
    "C-lsp-naive": TreatmentFactors("C-lsp-naive", True, False),
    "D-full-router": TreatmentFactors("D-full-router", True, True),
}


BASELINE_INVARIANT_FIELDS = {
    "agent_id",
    "agent_command",
    "sandbox",
    "timeout_seconds",
    "model_id",
    "reasoning_effort",
    "ignore_user_config",
    "ignore_rules",
    "plugins_disabled",
    "ephemeral",
    "response_contract",
}


SEMANTIC_TREATMENT_FIELDS = {
    "semantic_access_enabled",
    "mcp_servers",
    "serena",
}


ROUTING_TREATMENT_FIELDS = {
    "routing_discipline_enabled",
    "router_policy",
    "high_fanout_policy",
    "max_raw_output_bytes",
}


CONTROLLED_METADATA_FIELDS = {
    "profile_id",
    "route_profile_hash",
}


def factors_for_profile(profile_id: str) -> TreatmentFactors:
    try:
        return TREATMENT_FACTORS[profile_id]
    except KeyError as exc:
        raise ValueError(f"profile is not part of the factorial study design: {profile_id}") from exc


def route_profile_hash(profile: RouteProfile) -> str:
    payload = {
        "profile_id": profile.profile_id,
        "allowed_tools": profile.allowed_tools,
        "blocked_tools": profile.blocked_tools,
        "required_first_tool": profile.required_first_tool,
        "high_fanout_policy": profile.high_fanout_policy,
        "max_raw_output_bytes": profile.max_raw_output_bytes,
        "instructions": profile.instructions,
    }
    return stable_json_sha256(payload)


def stable_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hmac_sha256_hex(value: str, *, key: str, length: int = 24) -> str:
    digest = hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:length]


def public_factor_payload(profile_id: str) -> dict[str, object]:
    return asdict(factors_for_profile(profile_id))


def allowed_config_diff_fields(left_profile_id: str, right_profile_id: str) -> set[str]:
    left = factors_for_profile(left_profile_id)
    right = factors_for_profile(right_profile_id)
    allowed: set[str] = set(CONTROLLED_METADATA_FIELDS)
    if left.semantic_access_enabled != right.semantic_access_enabled:
        allowed.update(SEMANTIC_TREATMENT_FIELDS)
    if left.routing_discipline_enabled != right.routing_discipline_enabled:
        allowed.update(ROUTING_TREATMENT_FIELDS)
    return allowed


def diff_effective_agent_configs(
    left: dict[str, object],
    right: dict[str, object],
    *,
    left_profile_id: str,
    right_profile_id: str,
) -> dict[str, object]:
    keys = sorted(set(left) | set(right))
    changed = {
        key: {"left": left.get(key), "right": right.get(key)}
        for key in keys
        if left.get(key) != right.get(key)
    }
    allowed = allowed_config_diff_fields(left_profile_id, right_profile_id)
    disallowed = sorted(key for key in changed if key not in allowed)
    return {
        "left_profile": left_profile_id,
        "right_profile": right_profile_id,
        "allowed_fields": sorted(allowed),
        "changed_fields": changed,
        "disallowed_fields": disallowed,
        "valid": not disallowed,
    }


def validate_factorial_arm_set(arms: list[str]) -> None:
    missing = [arm for arm in FACTORIAL_ARM_ORDER if arm not in arms]
    extra = [arm for arm in arms if arm not in FACTORIAL_ARM_ORDER]
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"extra={','.join(extra)}")
        raise ValueError("study mode requires exactly the A/B/C/D factorial arms (" + "; ".join(details) + ")")
