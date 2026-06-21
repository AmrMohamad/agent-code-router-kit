#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file
from scripts.lib.environment_capture import file_sha256
from scripts.benchmarks.audit_real_agent_study import audit


PUBLIC_ROW_FIELDS = [
    "run_id",
    "study_id",
    "protocol_commit",
    "controller_commit",
    "controller_tree_hash",
    "block_id",
    "sequence_id",
    "sequence_position",
    "previous_arm",
    "order_design",
    "repeat_index",
    "agent",
    "profile",
    "semantic_access_enabled",
    "routing_discipline_enabled",
    "task_family",
    "completion_reason",
    "oracle_status",
    "correctness_status",
    "policy_adherence",
    "token_source",
    "exact_input_tokens",
    "exact_cached_input_tokens",
    "exact_uncached_input_tokens",
    "exact_output_tokens",
    "exact_total_tokens",
    "exact_uncached_total_tokens",
    "exact_reasoning_output_tokens",
    "exact_usage_event_count",
    "model_visible_bytes",
    "tool_output_bytes",
    "wall_seconds",
    "semantic_setup_seconds",
    "task_execution_seconds",
    "end_to_end_seconds",
    "tool_call_count",
    "files_opened_count",
    "search_count",
    "semantic_tool_count",
    "runtime_tool_count",
    "ast_grep_count",
    "agent_config_hash",
    "route_profile_hash",
    "task_prompt_hmac",
    "source_state_hmac",
    "snapshot_state_hmac",
    "semantic_session_mode",
    "semantic_session_isolated",
    "semantic_session_artifact",
    "semantic_session_id_hmac",
    "semantic_project_path_hmac",
    "semantic_lifecycle_owner",
    "semantic_teardown_verified",
    "semantic_process_survivor_count",
    "semantic_child_lsp_survivor_count",
    "serena_process_state_before",
    "serena_process_state_after",
    "codex_version",
    "serena_version",
    "sourcekit_lsp_version",
    "kotlin_language_server_version",
    "json_language_server_version",
    "rg_version",
    "fd_version",
    "ast_grep_version",
    "git_version",
    "python_version",
    "os_version",
]


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def public_id_map(values: list[str], *, prefix: str) -> dict[str, str]:
    return {value: f"{prefix}_{index + 1:03d}" for index, value in enumerate(sorted(set(values)))}


def public_row(row: dict[str, object], *, task_ids: dict[str, str], repo_ids: dict[str, str]) -> dict[str, object]:
    sanitized = {key: row.get(key) for key in PUBLIC_ROW_FIELDS if key in row}
    sanitized["task_public_id"] = task_ids.get(str(row.get("task_id", "")), "")
    sanitized["repo_public_id"] = repo_ids.get(str(row.get("repo", "")), "")
    sanitized.pop("prompt", None)
    sanitized.pop("repo_path", None)
    sanitized.pop("run_dir", None)
    return sanitized


def sanitized_audit_summary(
    root: Path,
    *,
    confirmatory: bool,
    min_task_families: int,
    min_tasks_per_family: int,
) -> dict[str, object]:
    result = audit(
        root,
        confirmatory=confirmatory,
        min_task_families=min_task_families,
        min_tasks_per_family=min_tasks_per_family,
    )
    issues = result.get("issues", []) if isinstance(result.get("issues"), list) else []
    return {
        "audit_mode": "confirmatory" if confirmatory else "exploratory",
        "status": result.get("status"),
        "run_count": result.get("run_count", 0),
        "arm_counts": result.get("arm_counts", {}),
        "min_task_families": min_task_families,
        "min_tasks_per_family": min_tasks_per_family,
        "issue_counts": dict(Counter(str(issue.get("code", "")) for issue in issues if isinstance(issue, dict))),
        "fail_count": sum(1 for issue in issues if isinstance(issue, dict) and issue.get("severity") == "fail"),
    }


def sanitized_study_package(manifest: dict[str, object]) -> dict[str, object]:
    package = manifest.get("study_package")
    if not isinstance(package, dict):
        return {}
    allowed_fields = [
        "hash_algorithm",
        "private_fingerprint_algorithm",
        "task_split",
        "task_oracles_source",
        "study_plan_sha256",
        "protocol_sha256",
        "analysis_plan_sha256",
        "study_plan_hmac",
        "protocol_hmac",
        "analysis_plan_hmac",
        "task_oracles_hmac",
        "task_manifest_hmac",
        "pilot_task_manifest_hmac",
        "confirmatory_task_manifest_hmac",
    ]
    return {field: package[field] for field in allowed_fields if field in package}


def sanitize_repo_grouped_effects(payload: object, *, repo_ids: dict[str, str]) -> object:
    if not isinstance(payload, dict):
        return payload
    sanitized: dict[str, object] = {}
    for comparison, groups in payload.items():
        if not isinstance(groups, dict):
            sanitized[str(comparison)] = groups
            continue
        sanitized[str(comparison)] = {
            repo_ids.get(str(repo), "repo_unknown"): value
            for repo, value in sorted(groups.items(), key=lambda item: str(item[0]))
        }
    return sanitized


def sanitize_analysis_payload(analysis: dict[str, object], *, repo_ids: dict[str, str]) -> dict[str, object]:
    sanitized = dict(analysis)
    for key in ("pairwise_effects_by_repo", "factorial_effects_by_repo"):
        if key in sanitized:
            sanitized[key] = sanitize_repo_grouped_effects(sanitized[key], repo_ids=repo_ids)
    return sanitized


def sanitized_treatment_diff_row(row: dict[str, object], *, task_ids: dict[str, str], repo_ids: dict[str, str]) -> dict[str, object]:
    sanitized = dict(row)
    sanitized["task_public_id"] = task_ids.get(str(row.get("task_id", "")), "")
    sanitized["repo_public_id"] = repo_ids.get(str(row.get("repo", "")), "")
    sanitized.pop("task_id", None)
    sanitized.pop("repo", None)
    return sanitized


def build_public_bundle(
    *,
    root: Path,
    out: Path,
    min_task_families: int = 5,
    min_tasks_per_family: int = 3,
) -> dict[str, object]:
    audit_summary = sanitized_audit_summary(
        root,
        confirmatory=True,
        min_task_families=min_task_families,
        min_tasks_per_family=min_tasks_per_family,
    )
    if audit_summary.get("status") != "pass":
        raise SystemExit("public study bundle requires a passing confirmatory audit before export")
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "run-manifest.json").read_text(encoding="utf-8"))
    rows = load_jsonl(root / "runs.jsonl")
    task_ids = public_id_map([str(row.get("task_id", "")) for row in rows], prefix="task")
    repo_ids = public_id_map([str(row.get("repo", "")) for row in rows], prefix="repo")
    public_manifest = {
        "study_id": manifest.get("study_id"),
        "order_design": manifest.get("order_design"),
        "parallelism": manifest.get("parallelism"),
        "agents": manifest.get("agents", []),
        "snapshot_repos": manifest.get("snapshot_repos"),
        "isolated_agent_home": manifest.get("isolated_agent_home"),
        "isolated_serena_session": manifest.get("isolated_serena_session"),
        "require_clean_serena_process_state": manifest.get("require_clean_serena_process_state"),
        "require_explicit_reasoning_effort": manifest.get("require_explicit_reasoning_effort"),
        "model_id": manifest.get("model_id"),
        "reasoning_effort": manifest.get("reasoning_effort"),
        "tool_versions": manifest.get("tool_versions", {}),
        "controller_commit": manifest.get("controller_commit", ""),
        "controller_tree_hash": manifest.get("controller_tree_hash", ""),
        "controller_dirty": manifest.get("controller_dirty"),
        "route_profile_hashes": manifest.get("route_profile_hashes", {}),
        "study_package": sanitized_study_package(manifest),
        "task_count": len(task_ids),
        "repo_count": len(repo_ids),
        "privacy": {
            "private_paths_removed": True,
            "private_prompts_removed": True,
            "private_task_ids_removed": True,
            "private_repo_ids_removed": True,
            "private_value_hmac_fields_only": True,
            "private_task_oracle_and_manifest_hashes_omitted": True,
        },
    }
    to_json_file(out / "manifest.sanitized.json", public_manifest)
    with (out / "runs.sanitized.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(public_row(row, task_ids=task_ids, repo_ids=repo_ids), sort_keys=True) + "\n")
    to_json_file(out / "audit.sanitized.json", audit_summary)
    analysis_path = root / "study-analysis.json"
    if analysis_path.exists():
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        to_json_file(out / "analysis.sanitized.json", sanitize_analysis_payload(analysis, repo_ids=repo_ids))
    power_path = root / "study-power.json"
    if power_path.exists():
        to_json_file(out / "power.sanitized.json", json.loads(power_path.read_text(encoding="utf-8")))
    treatment_diffs_path = root / "treatment-diffs.jsonl"
    if treatment_diffs_path.exists():
        with (out / "treatment-diffs.sanitized.jsonl").open("w", encoding="utf-8") as handle:
            for row in load_jsonl(treatment_diffs_path):
                handle.write(
                    json.dumps(
                        sanitized_treatment_diff_row(row, task_ids=task_ids, repo_ids=repo_ids),
                        sort_keys=True,
                    )
                    + "\n"
                )
    readme = (
        "# Router Effect V1 Public Evidence\n\n"
        "This bundle contains sanitized study metadata and run rows. It intentionally "
        "omits private repository paths, repository names, task ids, prompts, source snippets, "
        "and concrete target symbols.\n"
    )
    (out / "README.md").write_text(readme, encoding="utf-8")
    artifact_hashes = {
        path.name: file_sha256(path)
        for path in sorted(out.iterdir())
        if path.is_file() and path.name != "artifact-hashes.sha256.json"
    }
    to_json_file(out / "artifact-hashes.sha256.json", artifact_hashes)
    return {"out": str(out), "artifact_hashes": artifact_hashes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a privacy-safe public bundle from router-effect-v1 study output.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-task-families", type=int, default=5)
    parser.add_argument("--min-tasks-per-family", type=int, default=3)
    args = parser.parse_args(argv)
    if args.min_task_families < 1:
        parser.error("--min-task-families must be >= 1")
    if args.min_tasks_per_family < 1:
        parser.error("--min-tasks-per-family must be >= 1")
    result = build_public_bundle(
        root=Path(args.root).expanduser().resolve(),
        out=Path(args.out).expanduser().resolve(),
        min_task_families=args.min_task_families,
        min_tasks_per_family=args.min_tasks_per_family,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
