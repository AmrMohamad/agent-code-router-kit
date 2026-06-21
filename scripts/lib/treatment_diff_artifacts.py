from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from scripts.lib.treatment_config import FACTORIAL_ARM_ORDER, FACTORIAL_COMPARISONS, diff_effective_agent_configs


def load_effective_config(row: dict[str, object]) -> dict[str, object] | None:
    path = Path(str(row.get("run_dir", ""))) / "effective-agent-config.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def block_key(row: dict[str, object]) -> tuple[str, str, str, int]:
    return (
        str(row.get("agent", "")),
        str(row.get("task_id", "")),
        str(row.get("repo", "")),
        int(row.get("repeat_index", 0)),
    )


def build_treatment_diff_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    by_block: dict[tuple[str, str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        by_block[block_key(row)][str(row.get("profile", ""))] = row

    artifacts: list[dict[str, object]] = []
    for key, profile_rows in sorted(by_block.items()):
        missing = [arm for arm in FACTORIAL_ARM_ORDER if arm not in profile_rows]
        exemplar = next(iter(profile_rows.values()), {})
        comparisons: list[dict[str, object]] = []
        valid = not missing
        if not missing:
            configs = {profile: load_effective_config(row) for profile, row in profile_rows.items()}
            missing_configs = [profile for profile, config in configs.items() if config is None]
            if missing_configs:
                valid = False
                comparisons.append(
                    {
                        "status": "missing_effective_config",
                        "missing_profiles": sorted(missing_configs),
                    }
                )
            else:
                for left, right in FACTORIAL_COMPARISONS:
                    diff = diff_effective_agent_configs(
                        configs[left] or {},
                        configs[right] or {},
                        left_profile_id=left,
                        right_profile_id=right,
                    )
                    comparisons.append(diff)
                    valid = valid and bool(diff.get("valid"))
        artifacts.append(
            {
                "agent": key[0],
                "task_id": key[1],
                "repo": key[2],
                "repeat_index": key[3],
                "block_id": exemplar.get("block_id", ""),
                "task_family": exemplar.get("task_family", ""),
                "missing_profiles": missing,
                "comparisons": comparisons,
                "valid": valid,
            }
        )
    return artifacts


def write_treatment_diff_artifact(*, rows: list[dict[str, object]], out: str | Path) -> None:
    path = Path(out)
    with path.open("w", encoding="utf-8") as handle:
        for row in build_treatment_diff_rows(rows):
            handle.write(json.dumps(row, sort_keys=True) + "\n")
