from __future__ import annotations

from dataclasses import asdict, dataclass


CODEGRAPH_ARM_ORDER = [
    "CG-A-control",
    "CG-B-policy-only",
    "CG-C-capability-only",
    "CG-D-bounded-router",
]

OPTIONAL_CODEGRAPH_ARMS = ["CG-X-raw-codegraph"]


@dataclass(frozen=True)
class CodeGraphTreatment:
    arm_id: str
    gateway_access_enabled: bool
    graph_routing_discipline_enabled: bool
    max_graph_calls: int
    max_graph_output_bytes: int


CODEGRAPH_TREATMENTS = {
    "CG-A-control": CodeGraphTreatment("CG-A-control", False, False, 0, 0),
    "CG-B-policy-only": CodeGraphTreatment("CG-B-policy-only", False, True, 0, 0),
    "CG-C-capability-only": CodeGraphTreatment("CG-C-capability-only", True, False, 2, 6000),
    "CG-D-bounded-router": CodeGraphTreatment("CG-D-bounded-router", True, True, 2, 6000),
    "CG-X-raw-codegraph": CodeGraphTreatment("CG-X-raw-codegraph", True, False, 999, 24000),
}


def codegraph_treatment_for_arm(arm_id: str) -> CodeGraphTreatment:
    try:
        return CODEGRAPH_TREATMENTS[arm_id]
    except KeyError as exc:
        raise ValueError(f"unknown CodeGraph arm: {arm_id}") from exc


def validate_codegraph_arm_set(arms: list[str], *, allow_optional_raw: bool = False) -> None:
    allowed = list(CODEGRAPH_ARM_ORDER)
    if allow_optional_raw:
        allowed.extend(OPTIONAL_CODEGRAPH_ARMS)
    missing = [arm for arm in CODEGRAPH_ARM_ORDER if arm not in arms]
    extra = [arm for arm in arms if arm not in allowed]
    if missing or extra:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if extra:
            details.append("extra=" + ",".join(extra))
        raise ValueError("invalid CodeGraph arm set (" + "; ".join(details) + ")")


def public_codegraph_factor_payload(arm_id: str) -> dict[str, object]:
    return asdict(codegraph_treatment_for_arm(arm_id))
