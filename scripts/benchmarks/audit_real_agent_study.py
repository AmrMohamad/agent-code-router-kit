#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file
from scripts.lib.treatment_config import (
    FACTORIAL_ARM_ORDER,
    diff_effective_agent_configs,
    factors_for_profile,
)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add_issue(issues: list[dict[str, object]], severity: str, code: str, message: str) -> None:
    issues.append({"severity": severity, "code": code, "message": message})


def config_for_row(row: dict[str, object]) -> dict[str, object] | None:
    path = Path(str(row.get("run_dir", ""))) / "effective-agent-config.json"
    if not path.exists():
        return None
    return load_json(path)


def audit(root: str | Path) -> dict[str, object]:
    base = Path(root).expanduser().resolve()
    issues: list[dict[str, object]] = []
    manifest_path = base / "run-manifest.json"
    runs_path = base / "runs.jsonl"
    if not manifest_path.exists():
        add_issue(issues, "fail", "manifest_missing", "run-manifest.json is missing")
        return {"status": "fail", "issues": issues}
    if not runs_path.exists():
        add_issue(issues, "fail", "runs_missing", "runs.jsonl is missing")
        return {"status": "fail", "issues": issues}
    manifest = load_json(manifest_path)
    rows = load_jsonl(runs_path)

    if manifest.get("study_id") != "router-effect-v1":
        add_issue(issues, "fail", "study_id", "manifest does not identify router-effect-v1")
    if manifest.get("order_design") != "balanced-latin-square":
        add_issue(issues, "fail", "order_design", "study requires balanced-latin-square order")
    if manifest.get("parallelism") != 1:
        add_issue(issues, "fail", "parallelism", "study requires sequential execution")
    if manifest.get("snapshot_repos") is not True or manifest.get("require_snapshots") is not True:
        add_issue(issues, "fail", "snapshots", "study requires detached repository snapshots")
    if manifest.get("isolated_agent_home") is not True:
        add_issue(issues, "fail", "isolated_agent_home", "study requires fresh controlled agent home per run")
    if manifest.get("isolated_serena_session") is not True:
        add_issue(issues, "fail", "isolated_serena_session", "study requires isolated semantic sessions")
    if manifest.get("capture_versions") is not True or not manifest.get("tool_versions"):
        add_issue(issues, "fail", "version_capture", "study requires captured tool/controller versions")
    if manifest.get("model_id") in {"", "not_pinned", None}:
        add_issue(issues, "fail", "model_id", "study requires an exact pinned model id")

    arms = set(str(row.get("profile", "")) for row in rows)
    missing_arms = [arm for arm in FACTORIAL_ARM_ORDER if arm not in arms]
    if missing_arms:
        add_issue(issues, "fail", "arm_coverage", f"missing arms: {','.join(missing_arms)}")

    positions_by_arm: Counter[tuple[str, int]] = Counter()
    cells_by_block: dict[tuple[str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        profile = str(row.get("profile", ""))
        position = row.get("sequence_position")
        if isinstance(position, int):
            positions_by_arm[(profile, position)] += 1
        else:
            add_issue(issues, "fail", "sequence_position", f"run {row.get('run_id')} has no sequence position")
        try:
            factors = factors_for_profile(profile)
        except ValueError as exc:
            add_issue(issues, "fail", "factorial_profile", str(exc))
            continue
        if row.get("semantic_access_enabled") != factors.semantic_access_enabled:
            add_issue(issues, "fail", "semantic_factor", f"run {row.get('run_id')} has wrong semantic factor")
        if row.get("routing_discipline_enabled") != factors.routing_discipline_enabled:
            add_issue(issues, "fail", "routing_factor", f"run {row.get('run_id')} has wrong routing factor")
        if not row.get("agent_config_hash"):
            add_issue(issues, "fail", "agent_config_hash", f"run {row.get('run_id')} has no agent config hash")
        if not (Path(str(row.get("run_dir", ""))) / "oracle.json").exists():
            add_issue(issues, "fail", "oracle_artifact", f"run {row.get('run_id')} has no oracle.json")
        if row.get("oracle_status") in {"", "not_configured", None}:
            add_issue(issues, "fail", "oracle_status", f"run {row.get('run_id')} has no configured external oracle")
        key = (str(row.get("agent", "")), str(row.get("task_id", "")), int(row.get("repeat_index", 0)))
        cells_by_block[key][profile] = row

    for arm in FACTORIAL_ARM_ORDER:
        counts = [positions_by_arm[(arm, position)] for position in range(1, 5)]
        if len(set(counts)) > 1:
            add_issue(issues, "fail", "position_balance", f"{arm} position counts are not balanced: {counts}")

    for key, profile_rows in cells_by_block.items():
        missing = [arm for arm in FACTORIAL_ARM_ORDER if arm not in profile_rows]
        if missing:
            add_issue(issues, "fail", "block_arm_completion", f"{key} missing {','.join(missing)}")
            continue
        configs = {profile: config_for_row(row) for profile, row in profile_rows.items()}
        for profile, config in configs.items():
            if config is None:
                add_issue(issues, "fail", "effective_config_missing", f"{key}/{profile} missing effective-agent-config.json")
        if any(config is None for config in configs.values()):
            continue
        comparisons = [
            ("A-search-only", "B-search-summary"),
            ("A-search-only", "C-lsp-naive"),
            ("C-lsp-naive", "D-full-router"),
            ("B-search-summary", "D-full-router"),
        ]
        for left, right in comparisons:
            diff = diff_effective_agent_configs(
                configs[left] or {},
                configs[right] or {},
                left_profile_id=left,
                right_profile_id=right,
            )
            if not diff["valid"]:
                add_issue(
                    issues,
                    "fail",
                    "treatment_diff",
                    f"{key} {left} vs {right} has disallowed config fields: {','.join(diff['disallowed_fields'])}",
                )

    status = "pass" if not any(issue["severity"] == "fail" for issue in issues) else "fail"
    return {
        "status": status,
        "run_count": len(rows),
        "issues": issues,
        "arm_counts": dict(Counter(str(row.get("profile", "")) for row in rows)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a router-effect-v1 real-agent study output.")
    parser.add_argument("--root", required=True, help="Benchmark output directory.")
    parser.add_argument("--out", help="Optional JSON output path.")
    args = parser.parse_args(argv)
    result = audit(args.root)
    if args.out:
        to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
