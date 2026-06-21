from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scripts.lib.agent_session import load_simple_yaml
from scripts.lib.treatment_config import FACTORIAL_ARM_ORDER, validate_factorial_arm_set


BALANCED_LATIN_SQUARE_4 = [
    ["A-search-only", "B-search-summary", "D-full-router", "C-lsp-naive"],
    ["B-search-summary", "C-lsp-naive", "A-search-only", "D-full-router"],
    ["C-lsp-naive", "D-full-router", "B-search-summary", "A-search-only"],
    ["D-full-router", "A-search-only", "C-lsp-naive", "B-search-summary"],
]


@dataclass(frozen=True)
class StudyPlan:
    study_id: str
    design_type: str
    order_design: str
    minimum_repeats: int
    parallelism: int
    require_clean_snapshots: bool
    require_block_snapshots: bool
    require_fresh_agent_home: bool
    require_isolated_serena: bool
    require_prewarm_semantic_layer: bool
    require_clean_serena_process_state: bool
    require_capture_versions: bool
    require_explicit_reasoning_effort: bool
    require_external_oracles: bool
    agents: list[str]
    arms: list[str]
    protocol_path: str
    analysis_plan_path: str
    pilot_tasks_path: str
    confirmatory_tasks_path: str
    task_oracles_path: str


def balanced_latin_square(arms: list[str]) -> list[list[str]]:
    if arms == FACTORIAL_ARM_ORDER:
        return [list(sequence) for sequence in BALANCED_LATIN_SQUARE_4]
    if len(arms) != 4:
        raise ValueError("balanced-latin-square study mode currently requires exactly four arms")
    validate_factorial_arm_set(arms)
    return [list(sequence) for sequence in BALANCED_LATIN_SQUARE_4]


def assign_sequence(task_id: str, block_index: int, *, arms: list[str] | None = None) -> list[str]:
    del task_id
    sequences = balanced_latin_square(arms or FACTORIAL_ARM_ORDER)
    return list(sequences[block_index % len(sequences)])


def load_study_plan(path: str | Path) -> StudyPlan:
    source = Path(path).expanduser().resolve()
    data = load_simple_yaml(source)
    arms = [item.strip() for item in str(data.get("arms", ",".join(FACTORIAL_ARM_ORDER))).split(",") if item.strip()]
    validate_factorial_arm_set(arms)
    agents = [item.strip() for item in str(data.get("agents", "codex")).split(",") if item.strip()]
    if not agents:
        raise ValueError("study plan must declare at least one agent")
    return StudyPlan(
        study_id=str(data.get("study_id", source.stem)),
        design_type=str(data.get("design_type", "2x2_factorial")),
        order_design=str(data.get("order_design", "balanced-latin-square")),
        minimum_repeats=int(data.get("minimum_repeats", 4)),
        parallelism=int(data.get("parallelism", 1)),
        require_clean_snapshots=bool(data.get("require_clean_snapshots", True)),
        require_block_snapshots=bool(data.get("require_block_snapshots", True)),
        require_fresh_agent_home=bool(data.get("require_fresh_agent_home", True)),
        require_isolated_serena=bool(data.get("require_isolated_serena", True)),
        require_prewarm_semantic_layer=bool(data.get("require_prewarm_semantic_layer", True)),
        require_clean_serena_process_state=bool(data.get("require_clean_serena_process_state", True)),
        require_capture_versions=bool(data.get("require_capture_versions", True)),
        require_explicit_reasoning_effort=bool(data.get("require_explicit_reasoning_effort", True)),
        require_external_oracles=bool(data.get("require_external_oracles", True)),
        agents=agents,
        arms=arms,
        protocol_path=str((source.parent / str(data.get("protocol_path", "protocol.md"))).resolve()),
        analysis_plan_path=str((source.parent / str(data.get("analysis_plan_path", "analysis-plan.yaml"))).resolve()),
        pilot_tasks_path=str((source.parent / str(data.get("pilot_tasks_path", "pilot-tasks.tsv"))).resolve()),
        confirmatory_tasks_path=str(
            (source.parent / str(data.get("confirmatory_tasks_path", "confirmatory-tasks.tsv"))).resolve()
        ),
        task_oracles_path=str((source.parent / str(data.get("task_oracles_path", "task-oracles.json"))).resolve()),
    )


def sequence_metadata(sequence: list[str], *, position: int, block_index: int) -> dict[str, object]:
    profile = sequence[position]
    previous = sequence[position - 1] if position > 0 else ""
    return {
        "block_id": f"block-{block_index + 1:03d}",
        "sequence_id": f"balanced-latin-square-{(block_index % len(BALANCED_LATIN_SQUARE_4)) + 1}",
        "sequence_position": position + 1,
        "previous_arm": previous,
        "order_design": "balanced-latin-square",
        "profile": profile,
    }
