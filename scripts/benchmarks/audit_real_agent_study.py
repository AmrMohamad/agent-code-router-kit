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


def semantic_session_for_row(row: dict[str, object]) -> dict[str, object] | None:
    artifact = str(row.get("semantic_session_artifact") or "semantic-session.json")
    path = Path(str(row.get("run_dir", ""))) / artifact
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
    if manifest.get("private_hmac_configured") is not True:
        add_issue(issues, "fail", "private_hmac", "study requires private HMAC key configuration")

    arms = set(str(row.get("profile", "")) for row in rows)
    missing_arms = [arm for arm in FACTORIAL_ARM_ORDER if arm not in arms]
    if missing_arms:
        add_issue(issues, "fail", "arm_coverage", f"missing arms: {','.join(missing_arms)}")

    positions_by_arm: Counter[tuple[str, int]] = Counter()
    positions_by_task_arm: Counter[tuple[str, str, str, int]] = Counter()
    cells_by_block: dict[tuple[str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    live = manifest.get("live") is True
    for row in rows:
        profile = str(row.get("profile", ""))
        position = row.get("sequence_position")
        if isinstance(position, int):
            positions_by_arm[(profile, position)] += 1
            positions_by_task_arm[(str(row.get("agent", "")), str(row.get("task_id", "")), profile, position)] += 1
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
        weak_controls = row.get("route_weak_controls")
        if isinstance(weak_controls, list) and weak_controls:
            add_issue(issues, "fail", "weak_route_controls", f"run {row.get('run_id')} has weak route controls: {','.join(str(item) for item in weak_controls)}")
        hard_controls = row.get("route_hard_controls")
        required_hard = {"codex_fresh_home", "codex_auth_preserved", "codex_ignore_user_config", "codex_ignore_rules", "codex_plugins_disabled", "codex_controlled_mcp_servers"}
        if not isinstance(hard_controls, list) or not required_hard.issubset({str(item) for item in hard_controls}):
            add_issue(issues, "fail", "hard_route_controls", f"run {row.get('run_id')} lacks required hermetic Codex hard controls")
        if not row.get("agent_config_hash"):
            add_issue(issues, "fail", "agent_config_hash", f"run {row.get('run_id')} has no agent config hash")
        else:
            config_hash_path = Path(str(row.get("run_dir", ""))) / "effective-agent-config.sha256"
            if not config_hash_path.exists():
                add_issue(issues, "fail", "agent_config_hash_file", f"run {row.get('run_id')} has no effective-agent-config.sha256")
            elif config_hash_path.read_text(encoding="utf-8").strip() != row.get("agent_config_hash"):
                add_issue(issues, "fail", "agent_config_hash_match", f"run {row.get('run_id')} config hash does not match row")
        if not row.get("task_prompt_hmac"):
            add_issue(issues, "fail", "task_prompt_hmac", f"run {row.get('run_id')} has no task prompt HMAC")
        if not row.get("source_state_hmac"):
            add_issue(issues, "fail", "source_state_hmac", f"run {row.get('run_id')} has no source state HMAC")
        if not row.get("snapshot_tree_hash"):
            add_issue(issues, "fail", "snapshot_tree_hash", f"run {row.get('run_id')} has no snapshot tree hash")
        if "lockfile_hash" not in row or row.get("lockfile_hash") in {"", None}:
            add_issue(issues, "fail", "lockfile_hash", f"run {row.get('run_id')} has no lockfile hash marker")
        if live:
            for field in ("codex_version", "serena_version", "os_version"):
                value = str(row.get(field, ""))
                if not value or value.startswith("not_available"):
                    add_issue(issues, "fail", field, f"live study run {row.get('run_id')} lacks usable {field}")
            if row.get("token_source") != "exact":
                add_issue(issues, "fail", "exact_token_source", f"live study run {row.get('run_id')} is not exact-token sourced")
            if not isinstance(row.get("exact_uncached_input_tokens"), int):
                add_issue(issues, "fail", "exact_uncached_input_tokens", f"live study run {row.get('run_id')} lacks exact uncached input tokens")
        semantic_session = semantic_session_for_row(row)
        if semantic_session is None:
            add_issue(issues, "fail", "semantic_session_artifact", f"run {row.get('run_id')} has no semantic-session.json")
        else:
            if semantic_session.get("semantic_access_enabled") != factors.semantic_access_enabled:
                add_issue(issues, "fail", "semantic_session_factor", f"run {row.get('run_id')} semantic-session factor mismatch")
            if factors.semantic_access_enabled:
                if semantic_session.get("mode") != "codex_mcp_stdio_per_run":
                    add_issue(issues, "fail", "semantic_session_mode", f"run {row.get('run_id')} semantic session is not per-run Codex MCP stdio")
                if semantic_session.get("isolated") is not True:
                    add_issue(issues, "fail", "semantic_session_isolation", f"run {row.get('run_id')} semantic session is not isolated")
                if semantic_session.get("mcp_server_configured") is not True:
                    add_issue(issues, "fail", "semantic_mcp_config", f"run {row.get('run_id')} has no semantic MCP config")
            else:
                if semantic_session.get("mode") != "disabled" or semantic_session.get("mcp_server_configured") is not False:
                    add_issue(issues, "fail", "semantic_session_disabled", f"run {row.get('run_id')} search-only semantic session is not disabled")
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
    task_ids = sorted({(str(row.get("agent", "")), str(row.get("task_id", ""))) for row in rows})
    for agent, task_id in task_ids:
        for arm in FACTORIAL_ARM_ORDER:
            counts = [positions_by_task_arm[(agent, task_id, arm, position)] for position in range(1, 5)]
            if len(set(counts)) > 1:
                add_issue(issues, "fail", "task_position_balance", f"{agent}/{task_id}/{arm} position counts are not balanced: {counts}")

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
        prompt_hashes = {str(row.get("task_prompt_sha256", "")) for row in profile_rows.values()}
        if len(prompt_hashes) != 1:
            add_issue(issues, "fail", "block_prompt_match", f"{key} task prompt hash differs across arms")
        source_hmacs = {str(row.get("source_state_hmac", "")) for row in profile_rows.values()}
        if len(source_hmacs) != 1:
            add_issue(issues, "fail", "block_source_state_match", f"{key} source state HMAC differs across arms")
        tree_hashes = {str(row.get("snapshot_tree_hash", "")) for row in profile_rows.values()}
        if len(tree_hashes) != 1:
            add_issue(issues, "fail", "block_snapshot_tree_match", f"{key} snapshot tree hash differs across arms")
        model_ids = {str(row.get("model_id", "")) for row in profile_rows.values()}
        reasoning_efforts = {str(row.get("reasoning_effort", "")) for row in profile_rows.values()}
        if len(model_ids) != 1 or len(reasoning_efforts) != 1:
            add_issue(issues, "fail", "block_model_config_match", f"{key} model or reasoning effort differs across arms")
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
