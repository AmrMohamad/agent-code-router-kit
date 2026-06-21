#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from string import hexdigits

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.analyze_real_agent_study import analyze as compute_study_analysis
from scripts.benchmarks.estimate_study_power import estimate as compute_study_power
from scripts.lib.agent_session import to_json_file
from scripts.lib.agent_session import load_simple_yaml, load_tasks
from scripts.lib.environment_capture import file_sha256
from scripts.lib.task_oracles import load_task_oracles, validate_task_oracle_plan
from scripts.lib.treatment_diff_artifacts import build_treatment_diff_rows
from scripts.lib.treatment_config import (
    FACTORIAL_ARM_ORDER,
    FACTORIAL_COMPARISONS,
    diff_effective_agent_configs,
    factors_for_profile,
)


TOOL_VERSION_FIELDS = [
    "codex_version",
    "serena_version",
    "sourcekit_lsp_version",
    "kotlin_language_server_version",
    "json_language_server_version",
    "os_version",
]

LANGUAGE_SERVER_VERSION_FIELDS = {
    "sourcekit-lsp": "sourcekit_lsp_version",
    "kotlin-language-server": "kotlin_language_server_version",
    "vscode-json-languageserver": "json_language_server_version",
}
SERENA_PROCESS_STATE_KEYS = ("serena_mcp", "sourcekit_lsp", "kotlin_lsp", "json_lsp")


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


def route_isolation_for_row(row: dict[str, object]) -> dict[str, object] | None:
    path = Path(str(row.get("run_dir", ""))) / "route-isolation.json"
    if not path.exists():
        return None
    return load_json(path)


def launch_plan_for_row(row: dict[str, object]) -> dict[str, object] | None:
    path = Path(str(row.get("run_dir", ""))) / "launch-plan.json"
    if not path.exists():
        return None
    return load_json(path)


def semantic_session_for_row(row: dict[str, object]) -> dict[str, object] | None:
    artifact = str(row.get("semantic_session_artifact") or "semantic-session.json")
    path = Path(str(row.get("run_dir", ""))) / artifact
    if not path.exists():
        return None
    return load_json(path)


def process_state_is_zero(value: object, *, keys: tuple[str, ...] = SERENA_PROCESS_STATE_KEYS) -> bool:
    if not isinstance(value, dict):
        return False
    for key in keys:
        count = value.get(key)
        if isinstance(count, bool) or not isinstance(count, int) or count != 0:
            return False
    return True


def has_arg_pair(args: list[str], option: str, value: str) -> bool:
    for index in range(len(args) - 1):
        if args[index] == option and args[index + 1] == value:
            return True
    return f"{option}={value}" in args


def codex_config_overrides(args: list[str]) -> list[str]:
    values: list[str] = []
    for index, arg in enumerate(args):
        if arg == "-c" and index + 1 < len(args):
            values.append(args[index + 1])
        elif arg.startswith("-c="):
            values.append(arg.removeprefix("-c="))
    return values


def has_codex_config_override(args: list[str], prefix: str, required_substrings: tuple[str, ...] = ()) -> bool:
    for value in codex_config_overrides(args):
        if not value.startswith(prefix):
            continue
        if all(part in value for part in required_substrings):
            return True
    return False


def has_disable_plugins(args: list[str]) -> bool:
    return has_arg_pair(args, "--disable", "plugins")


def _analysis_has_required_shape(analysis: dict[str, object]) -> bool:
    required = [
        "pairwise_effects",
        "pairwise_effects_by_task_family",
        "pairwise_effects_by_repo",
        "pairwise_effects_by_sequence_position",
        "pass_pass_sensitivity_pairwise_effects",
        "factorial_effects",
        "factorial_effects_by_task_family",
        "factorial_effects_by_repo",
        "correctness_pairwise",
        "multiple_comparison_correction",
        "correctness_noninferiority_margin",
        "cell_key_fields",
        "cluster_unit",
        "cost",
    ]
    if any(key not in analysis for key in required):
        return False
    if analysis.get("cell_key_fields") != ["agent", "task_id", "repo", "repeat_index"]:
        return False
    if analysis.get("cluster_unit") != "repository_task":
        return False
    pairwise = analysis.get("pairwise_effects")
    if not isinstance(pairwise, dict):
        return False
    for row in pairwise.values():
        if isinstance(row, dict) and row.get("pair_count", 0) and "cluster_bootstrap_95ci_percent" not in row:
            return False
    correction = analysis.get("multiple_comparison_correction")
    if not isinstance(correction, dict) or correction.get("method") != "holm":
        return False
    return True


def _analysis_cost_has_required_shape(analysis: dict[str, object], manifest: dict[str, object]) -> bool:
    cost = analysis.get("cost")
    if not isinstance(cost, dict):
        return False
    status = cost.get("status")
    if status == "not_configured":
        return True
    if status != "estimated":
        return False
    if cost.get("pricing_model_id") != manifest.get("model_id"):
        return False
    prices = cost.get("pricing_per_1m_tokens")
    required_prices = {
        "input_per_1m",
        "cached_input_per_1m",
        "output_per_1m",
        "reasoning_output_per_1m",
    }
    if not isinstance(prices, dict) or not required_prices.issubset(set(prices)):
        return False
    for field in required_prices:
        value = prices.get(field)
        if not isinstance(value, int | float) or value < 0:
            return False
    by_arm = cost.get("by_arm")
    if not isinstance(by_arm, dict) or not set(FACTORIAL_ARM_ORDER).issubset(set(by_arm)):
        return False
    required_arm_fields = {
        "run_count",
        "successful_task_count",
        "total_estimated_cost",
        "median_estimated_cost",
        "estimated_cost_per_run",
        "estimated_cost_per_successful_task",
    }
    for arm in FACTORIAL_ARM_ORDER:
        value = by_arm.get(arm)
        if not isinstance(value, dict) or not required_arm_fields.issubset(set(value)):
            return False
        for field in ("run_count", "successful_task_count"):
            if not isinstance(value.get(field), int):
                return False
        for field in ("total_estimated_cost", "median_estimated_cost", "estimated_cost_per_run"):
            if not isinstance(value.get(field), int | float):
                return False
        success_cost = value.get("estimated_cost_per_successful_task")
        if success_cost is not None and not isinstance(success_cost, int | float):
            return False
    return True


def _analysis_matches_preregistered_primary(analysis: dict[str, object]) -> bool:
    return analysis.get("metric") == "exact_uncached_input_tokens"


def _pricing_from_analysis(analysis: dict[str, object]) -> dict[str, object] | None:
    cost = analysis.get("cost")
    if not isinstance(cost, dict) or cost.get("status") != "estimated":
        return None
    prices = cost.get("pricing_per_1m_tokens")
    if not isinstance(prices, dict):
        return None
    pricing = dict(prices)
    pricing["model_id"] = cost.get("pricing_model_id", "")
    return pricing


def _analysis_matches_rows(analysis: dict[str, object], root: Path) -> bool:
    expected = compute_study_analysis(
        root,
        metric="exact_uncached_input_tokens",
        pricing=_pricing_from_analysis(analysis),
    )
    return analysis == expected


def _power_matches_preregistered_primary(power: dict[str, object]) -> bool:
    return (
        power.get("metric") == "exact_uncached_input_tokens"
        and power.get("minimum_effect") == 0.15
        and power.get("alpha") == 0.05
        and power.get("power") == 0.80
    )


def _power_has_required_shape(power: dict[str, object]) -> bool:
    pairwise = power.get("pairwise_power")
    required = {
        "A-search-only_to_B-search-summary",
        "A-search-only_to_C-lsp-naive",
        "C-lsp-naive_to_D-full-router",
        "A-search-only_to_D-full-router",
    }
    return (
        power.get("method") == "normal_approximation_on_paired_log_ratios"
        and power.get("cell_key_fields") == ["agent", "task_id", "repo", "repeat_index"]
        and power.get("cluster_unit") == "repository_task"
        and isinstance(power.get("z_alpha_two_sided"), int | float)
        and isinstance(power.get("z_power"), int | float)
        and isinstance(pairwise, dict)
        and required.issubset(set(pairwise))
        and power.get("all_preregistered_comparisons_power_target_met") is True
    )


def _power_matches_rows(power: dict[str, object], rows: list[dict[str, object]]) -> bool:
    expected = compute_study_power(
        rows,
        metric="exact_uncached_input_tokens",
        minimum_effect=0.15,
        floor_repeats=4,
        alpha=0.05,
        power=0.80,
    )
    return power == expected


def is_sha256_hex(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in hexdigits for char in value)


def is_hmac_fingerprint(value: object) -> bool:
    return isinstance(value, str) and len(value) == 24 and all(char in hexdigits for char in value)


def is_git_object_id(value: object) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and all(char in hexdigits for char in value)


def lock_hash_present(value: object) -> bool:
    return value == "none" or is_sha256_hex(value)


def manifest_repo_state(manifest: dict[str, object], key: str, field: str) -> dict[str, object]:
    payload = manifest.get(field)
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key) or payload.get("default")
    return value if isinstance(value, dict) else {}


def path_is_under(path: str, parent: str) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (OSError, ValueError):
        return False


def audit_confirmatory_study_package(
    *,
    manifest: dict[str, object],
    rows: list[dict[str, object]],
    issues: list[dict[str, object]],
) -> None:
    package = manifest.get("study_package")
    if not isinstance(package, dict):
        add_issue(issues, "fail", "study_package", "confirmatory study requires frozen study_package metadata")
        return
    required_hashes = [
        "study_plan_sha256",
        "protocol_sha256",
        "analysis_plan_sha256",
        "task_oracles_sha256",
        "task_manifest_sha256",
    ]
    for field in required_hashes:
        if not is_sha256_hex(package.get(field)):
            add_issue(issues, "fail", "study_package_hash", f"study_package.{field} is missing or not a SHA-256 hex digest")
    for name in ("study_plan", "protocol", "analysis_plan", "task_oracles", "task_manifest"):
        path = Path(str(package.get(f"{name}_path", "")))
        expected_hash = str(package.get(f"{name}_sha256", ""))
        if not path.exists():
            add_issue(issues, "fail", "study_package_file", f"study_package.{name}_path is not readable")
            continue
        if is_sha256_hex(expected_hash) and file_sha256(path) != expected_hash:
            add_issue(issues, "fail", "study_package_hash_match", f"study_package.{name}_sha256 does not match the frozen file")
    required_hmacs = ["study_plan_hmac", "protocol_hmac", "analysis_plan_hmac", "task_oracles_hmac", "task_manifest_hmac"]
    for field in required_hmacs:
        if not is_hmac_fingerprint(package.get(field)):
            add_issue(issues, "fail", "study_package_hmac", f"study_package.{field} is missing or not a keyed HMAC fingerprint")
    if package.get("task_split") != "confirmatory":
        add_issue(issues, "fail", "confirmatory_task_manifest", "confirmatory audit requires the frozen confirmatory task manifest")
    if package.get("task_oracles_source") != "study_plan":
        add_issue(issues, "fail", "confirmatory_task_oracles", "confirmatory audit requires the study-plan oracle file")
    manifest_task_hash = str(package.get("task_manifest_sha256", ""))
    row_task_hashes = {str(row.get("task_manifest_hash", "")) for row in rows}
    if len(row_task_hashes) != 1 or manifest_task_hash not in row_task_hashes:
        add_issue(issues, "fail", "task_manifest_hash_match", "row task_manifest_hash values must match the frozen study package")


def audit_confirmatory_oracle_plan(*, manifest: dict[str, object], issues: list[dict[str, object]]) -> None:
    package = manifest.get("study_package")
    if not isinstance(package, dict):
        return
    task_manifest_path = Path(str(package.get("task_manifest_path", "")))
    task_oracles_path = Path(str(package.get("task_oracles_path", "")))
    if not task_manifest_path.exists() or not task_oracles_path.exists():
        add_issue(issues, "fail", "task_oracle_plan", "confirmatory audit requires readable frozen task and oracle files")
        return
    result = validate_task_oracle_plan(
        tasks=load_tasks(task_manifest_path),
        oracles=load_task_oracles(task_oracles_path),
        require_task_specific=True,
    )
    if result["status"] != "pass":
        issue_codes = sorted({str(issue.get("code", "")) for issue in result.get("issues", []) if isinstance(issue, dict)})
        add_issue(
            issues,
            "fail",
            "task_oracle_plan",
            "confirmatory task oracle plan failed: " + ",".join(code for code in issue_codes if code),
        )


def _study_plan_arms_and_repeats(path: Path) -> tuple[list[str], int]:
    plan = load_simple_yaml(path)
    arms = [item.strip() for item in str(plan.get("arms", ",".join(FACTORIAL_ARM_ORDER))).split(",") if item.strip()]
    minimum_repeats = int(plan.get("minimum_repeats", 4))
    return arms, minimum_repeats


def audit_confirmatory_matrix_completion(
    *,
    manifest: dict[str, object],
    rows: list[dict[str, object]],
    issues: list[dict[str, object]],
) -> None:
    package = manifest.get("study_package")
    if not isinstance(package, dict):
        return
    task_manifest_path = Path(str(package.get("task_manifest_path", "")))
    study_plan_path = Path(str(package.get("study_plan_path", "")))
    if not task_manifest_path.exists() or not study_plan_path.exists():
        add_issue(issues, "fail", "confirmatory_matrix_files", "confirmatory matrix audit requires readable study plan and task manifest")
        return
    try:
        expected_arms, minimum_repeats = _study_plan_arms_and_repeats(study_plan_path)
    except (TypeError, ValueError, OSError) as exc:
        add_issue(issues, "fail", "confirmatory_matrix_plan", f"could not load study plan arms/repeats: {exc}")
        return
    if expected_arms != FACTORIAL_ARM_ORDER:
        add_issue(issues, "fail", "confirmatory_matrix_arms", "confirmatory matrix requires the preregistered A/B/C/D arm order")
    declared_repeats = manifest.get("repeats")
    if isinstance(declared_repeats, bool) or not isinstance(declared_repeats, int):
        add_issue(issues, "fail", "confirmatory_repeats", "manifest must record an integer repeat count")
        repeat_count = minimum_repeats
    else:
        if declared_repeats < minimum_repeats:
            add_issue(issues, "fail", "confirmatory_repeats", "manifest repeat count is below the preregistered minimum")
        repeat_count = max(declared_repeats, minimum_repeats)
    agents_value = manifest.get("agents")
    if isinstance(agents_value, list) and agents_value and all(isinstance(item, str) and item for item in agents_value):
        expected_agents = sorted(set(str(item) for item in agents_value))
    elif isinstance(manifest.get("agent"), str) and manifest.get("agent"):
        expected_agents = [str(manifest.get("agent"))]
    else:
        add_issue(issues, "fail", "confirmatory_matrix_agents", "manifest must record the expected study agent(s)")
        return
    expected_tasks = sorted({(str(task.repo), str(task.task_id)) for task in load_tasks(task_manifest_path)})
    if not expected_tasks:
        add_issue(issues, "fail", "confirmatory_matrix_tasks", "frozen confirmatory task manifest has no tasks")
        return

    observed_counts: Counter[tuple[str, str, str, str, int]] = Counter()
    unexpected_cells: list[tuple[str, str, str, str, object]] = []
    expected_task_set = set(expected_tasks)
    expected_arm_set = set(expected_arms)
    expected_agent_set = set(expected_agents)
    for row in rows:
        repeat = row.get("repeat_index")
        agent = str(row.get("agent", ""))
        repo = str(row.get("repo", ""))
        task_id = str(row.get("task_id", ""))
        profile = str(row.get("profile", ""))
        if (
            agent not in expected_agent_set
            or (repo, task_id) not in expected_task_set
            or profile not in expected_arm_set
            or isinstance(repeat, bool)
            or not isinstance(repeat, int)
            or repeat < 0
            or repeat >= repeat_count
        ):
            unexpected_cells.append((agent, repo, task_id, profile, repeat))
            continue
        observed_counts[(agent, repo, task_id, profile, repeat)] += 1

    missing: list[tuple[str, str, str, str, int]] = []
    duplicates: list[tuple[str, str, str, str, int, int]] = []
    for agent in expected_agents:
        for repo, task_id in expected_tasks:
            for profile in expected_arms:
                for repeat in range(repeat_count):
                    key = (agent, repo, task_id, profile, repeat)
                    count = observed_counts[key]
                    if count == 0:
                        missing.append(key)
                    elif count > 1:
                        duplicates.append((*key, count))

    expected_cell_count = len(expected_agents) * len(expected_tasks) * len(expected_arms) * repeat_count
    if len(rows) != expected_cell_count:
        add_issue(
            issues,
            "fail",
            "confirmatory_matrix_cell_count",
            f"confirmatory matrix expected {expected_cell_count} rows; observed {len(rows)}",
        )
    if missing:
        examples = ["%s/%s/%s/%s/%s" % item for item in missing[:8]]
        add_issue(issues, "fail", "confirmatory_matrix_missing", "missing preregistered cells: " + ",".join(examples))
    if duplicates:
        examples = ["%s/%s/%s/%s/%s(count=%s)" % item for item in duplicates[:8]]
        add_issue(issues, "fail", "confirmatory_matrix_duplicate", "duplicate preregistered cells: " + ",".join(examples))
    if unexpected_cells:
        examples = ["%s/%s/%s/%s/%s" % item for item in unexpected_cells[:8]]
        add_issue(issues, "fail", "confirmatory_matrix_unexpected", "unexpected non-preregistered cells: " + ",".join(examples))


def _plan_bool(plan: dict[str, object], key: str) -> bool | None:
    value = plan.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return None


def _plan_float(plan: dict[str, object], key: str) -> float | None:
    value = plan.get(key)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def audit_confirmatory_analysis_plan(*, manifest: dict[str, object], issues: list[dict[str, object]]) -> None:
    package = manifest.get("study_package")
    if not isinstance(package, dict):
        return
    analysis_plan_path = Path(str(package.get("analysis_plan_path", "")))
    if not analysis_plan_path.exists():
        add_issue(issues, "fail", "analysis_plan", "confirmatory audit requires a readable frozen analysis-plan file")
        return
    plan = load_simple_yaml(analysis_plan_path)
    required_scalars = {
        "primary_correctness": "external_oracle_pass",
        "primary_context_metric": "exact_uncached_input_tokens",
        "cluster_unit": "repository_task",
        "continuous_effect": "paired_log_ratio",
        "correctness_effect": "paired_binary_mcnemar_or_bootstrap",
        "multiple_comparison_correction": "holm",
        "public_repository_effects": "opaque_repo_ids_only",
    }
    wrong_scalars = [
        key
        for key, expected in required_scalars.items()
        if str(plan.get(key, "")) != expected
    ]
    required_booleans = {
        "intention_to_treat": True,
        "pass_pass_sensitivity": True,
    }
    wrong_booleans = [
        key
        for key, expected in required_booleans.items()
        if _plan_bool(plan, key) is not expected
    ]
    required_floats = {
        "minimum_meaningful_uncached_input_reduction": 0.15,
        "correctness_noninferiority_margin": 0.05,
        "alpha": 0.05,
        "power": 0.80,
        "confidence_interval": 0.95,
    }
    wrong_floats = [
        key
        for key, expected in required_floats.items()
        if _plan_float(plan, key) != expected
    ]
    list_like_fields = {
        "factorial_effects": {"semantic_access", "routing_discipline", "interaction"},
        "stratified_effects": {"task_family", "repository", "sequence_position"},
    }
    wrong_list_like = []
    for key, expected in list_like_fields.items():
        raw = plan.get(key, "")
        observed = {item.strip() for item in str(raw).split(",") if item.strip()}
        if not expected.issubset(observed):
            wrong_list_like.append(key)
    wrong_fields = sorted(wrong_scalars + wrong_booleans + wrong_floats + wrong_list_like)
    if wrong_fields:
        add_issue(
            issues,
            "fail",
            "analysis_plan",
            "confirmatory analysis-plan fields do not match the preregistered router-effect-v1 analysis: "
            + ",".join(wrong_fields),
        )


def audit_confirmatory_controller_provenance(
    *,
    manifest: dict[str, object],
    rows: list[dict[str, object]],
    issues: list[dict[str, object]],
) -> None:
    controller_commit = manifest.get("controller_commit")
    controller_tree_hash = manifest.get("controller_tree_hash")
    if not is_git_object_id(controller_commit):
        add_issue(issues, "fail", "controller_commit", "confirmatory study requires controller_commit in the manifest")
    if not is_git_object_id(controller_tree_hash):
        add_issue(issues, "fail", "controller_tree_hash", "confirmatory study requires controller_tree_hash in the manifest")
    if manifest.get("controller_dirty") is not False:
        add_issue(issues, "fail", "controller_clean", "confirmatory study requires a clean controller checkout")
    row_protocol_commits = {str(row.get("protocol_commit", "")) for row in rows}
    row_controller_commits = {str(row.get("controller_commit", "")) for row in rows}
    row_controller_trees = {str(row.get("controller_tree_hash", "")) for row in rows}
    if len(row_protocol_commits) != 1 or str(controller_commit) not in row_protocol_commits:
        add_issue(issues, "fail", "row_protocol_commit_match", "row protocol_commit values must match manifest controller_commit")
    if len(row_controller_commits) != 1 or str(controller_commit) not in row_controller_commits:
        add_issue(issues, "fail", "row_controller_commit_match", "row controller_commit values must match the manifest")
    if len(row_controller_trees) != 1 or str(controller_tree_hash) not in row_controller_trees:
        add_issue(issues, "fail", "row_controller_tree_match", "row controller_tree_hash values must match the manifest")


def audit_confirmatory_rerun_policy(*, manifest: dict[str, object], issues: list[dict[str, object]]) -> None:
    if manifest.get("rerun_failed") is True:
        add_issue(
            issues,
            "fail",
            "confirmatory_rerun_failed",
            "confirmatory studies must not rerun failed agent outcomes",
        )
    count_fields = {
        "invalid_carried_forward_runs": "confirmatory_invalid_carried_forward",
        "rerun_carried_forward_runs": "confirmatory_rerun_carried_forward",
        "missing_artifact_carried_forward_runs": "confirmatory_missing_artifact_carried_forward",
    }
    for field, code in count_fields.items():
        try:
            count = int(manifest.get(field, 0) or 0)
        except (TypeError, ValueError):
            add_issue(issues, "fail", code, f"confirmatory study has non-numeric {field}")
            continue
        if count != 0:
            add_issue(issues, "fail", code, f"confirmatory study has nonzero {field}")
    list_fields = {
        "invalid_carried_forward_cells": "confirmatory_invalid_carried_forward",
        "rerun_carried_forward_cells": "confirmatory_rerun_carried_forward",
        "missing_artifact_carried_forward_cells": "confirmatory_missing_artifact_carried_forward",
    }
    for field, code in list_fields.items():
        value = manifest.get(field)
        if isinstance(value, list) and value:
            add_issue(issues, "fail", code, f"confirmatory study has nonempty {field}")


def audit_treatment_diff_artifact(*, base: Path, rows: list[dict[str, object]], issues: list[dict[str, object]]) -> None:
    path = base / "treatment-diffs.jsonl"
    if not path.exists():
        add_issue(issues, "fail", "treatment_diff_artifact", "confirmatory study requires treatment-diffs.jsonl")
        return
    actual = load_jsonl(path)
    expected = build_treatment_diff_rows(rows)
    if actual != expected:
        add_issue(issues, "fail", "treatment_diff_artifact_consistency", "treatment-diffs.jsonl does not match recomputed effective-config diffs")
    for row in actual:
        if row.get("valid") is not True:
            add_issue(issues, "fail", "treatment_diff_artifact_valid", f"treatment diff block {row.get('block_id')} is not valid")
        comparisons = row.get("comparisons")
        if not isinstance(comparisons, list) or len(comparisons) != len(FACTORIAL_COMPARISONS):
            add_issue(issues, "fail", "treatment_diff_artifact_shape", f"treatment diff block {row.get('block_id')} does not include every preregistered comparison")


def audit(
    root: str | Path,
    *,
    confirmatory: bool = False,
    min_task_families: int = 5,
    min_tasks_per_family: int = 3,
) -> dict[str, object]:
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

    if confirmatory and manifest.get("live") is not True:
        add_issue(issues, "fail", "confirmatory_live", "confirmatory study audit requires live runs, not dry-run output")
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
    if confirmatory and manifest.get("prewarm_semantic_layer") is not True:
        add_issue(issues, "fail", "prewarm_semantic_layer", "confirmatory study requires semantic readiness prewarm")
    if confirmatory and manifest.get("serena_readiness_enabled") is not True:
        add_issue(issues, "fail", "serena_readiness_enabled", "confirmatory study requires Serena readiness checks")
    if confirmatory and manifest.get("require_clean_serena_process_state") is not True:
        add_issue(issues, "fail", "serena_process_state", "confirmatory study requires clean Serena process-state enforcement")
    if manifest.get("capture_versions") is not True or not manifest.get("tool_versions"):
        add_issue(issues, "fail", "version_capture", "study requires captured tool/controller versions")
    if manifest.get("model_id") in {"", "not_pinned", None}:
        add_issue(issues, "fail", "model_id", "study requires an exact pinned model id")
    if manifest.get("private_hmac_configured") is not True:
        add_issue(issues, "fail", "private_hmac", "study requires private HMAC key configuration")
    source_states = manifest.get("source_repo_states")
    snapshot_states = manifest.get("repo_snapshots")
    if not isinstance(source_states, dict) or not source_states:
        add_issue(issues, "fail", "source_repo_states", "manifest must record clean source repository states")
    if not isinstance(snapshot_states, dict) or not snapshot_states:
        add_issue(issues, "fail", "repo_snapshots", "manifest must record detached repository snapshots")
    if confirmatory:
        audit_confirmatory_study_package(manifest=manifest, rows=rows, issues=issues)
        audit_confirmatory_oracle_plan(manifest=manifest, issues=issues)
        audit_confirmatory_matrix_completion(manifest=manifest, rows=rows, issues=issues)
        audit_confirmatory_analysis_plan(manifest=manifest, issues=issues)
        audit_confirmatory_controller_provenance(manifest=manifest, rows=rows, issues=issues)
        audit_confirmatory_rerun_policy(manifest=manifest, issues=issues)
        audit_treatment_diff_artifact(base=base, rows=rows, issues=issues)

    arms = set(str(row.get("profile", "")) for row in rows)
    missing_arms = [arm for arm in FACTORIAL_ARM_ORDER if arm not in arms]
    if missing_arms:
        add_issue(issues, "fail", "arm_coverage", f"missing arms: {','.join(missing_arms)}")
    if confirmatory:
        tasks_by_family: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for row in rows:
            tasks_by_family[str(row.get("task_family", ""))].add(
                (str(row.get("repo", "")), str(row.get("task_id", "")))
            )
        populated_families = {
            family: tasks
            for family, tasks in tasks_by_family.items()
            if family and all(repo and task_id for repo, task_id in tasks)
        }
        if len(populated_families) < min_task_families:
            add_issue(
                issues,
                "fail",
                "confirmatory_task_family_count",
                f"confirmatory study requires at least {min_task_families} task families; observed {len(populated_families)}",
            )
        for family, tasks in populated_families.items():
            if len(tasks) < min_tasks_per_family:
                add_issue(
                    issues,
                    "fail",
                    "confirmatory_tasks_per_family",
                    f"family {family} has {len(tasks)} tasks; requires at least {min_tasks_per_family}",
                )

    positions_by_arm: Counter[tuple[str, int]] = Counter()
    positions_by_task_arm: Counter[tuple[str, str, str, str, int]] = Counter()
    semantic_session_ids: Counter[str] = Counter()
    cells_by_block: dict[tuple[str, str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    live = manifest.get("live") is True
    for row in rows:
        profile = str(row.get("profile", ""))
        position = row.get("sequence_position")
        if isinstance(position, int):
            positions_by_arm[(profile, position)] += 1
            positions_by_task_arm[
                (
                    str(row.get("agent", "")),
                    str(row.get("task_id", "")),
                    str(row.get("repo", "")),
                    profile,
                    position,
                )
            ] += 1
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
        route_isolation = route_isolation_for_row(row)
        launch_plan = launch_plan_for_row(row)
        if route_isolation is None:
            add_issue(issues, "fail", "route_isolation_artifact", f"run {row.get('run_id')} has no route-isolation.json")
        else:
            isolation_args = route_isolation.get("args")
            isolation_env = route_isolation.get("env")
            isolation_hard = route_isolation.get("hard_controls")
            isolation_weak = route_isolation.get("weak_controls")
            if not isinstance(isolation_args, list) or not all(isinstance(item, str) for item in isolation_args):
                add_issue(issues, "fail", "route_isolation_invocation", f"run {row.get('run_id')} route isolation lacks argv")
                isolation_args = []
            if not isinstance(isolation_env, dict):
                add_issue(issues, "fail", "route_isolation_invocation", f"run {row.get('run_id')} route isolation lacks env")
                isolation_env = {}
            if isolation_hard != row.get("route_hard_controls") or isolation_weak != row.get("route_weak_controls"):
                add_issue(issues, "fail", "route_isolation_controls", f"run {row.get('run_id')} row controls differ from route-isolation artifact")
            if route_isolation.get("mode") != row.get("route_isolation_mode"):
                add_issue(issues, "fail", "route_isolation_mode", f"run {row.get('run_id')} row mode differs from route-isolation artifact")
            if route_isolation.get("agent_id") != row.get("agent") or route_isolation.get("profile_id") != profile:
                add_issue(issues, "fail", "route_isolation_identity", f"run {row.get('run_id')} route-isolation identity differs from row")
            if row.get("agent") == "codex":
                if "--ignore-user-config" not in isolation_args or "--ignore-rules" not in isolation_args or not has_disable_plugins(isolation_args):
                    add_issue(issues, "fail", "route_isolation_invocation", f"run {row.get('run_id')} Codex argv lacks hermetic config/rules/plugin controls")
                model_id = str(row.get("model_id", ""))
                reasoning_effort = str(row.get("reasoning_effort", ""))
                if model_id and not has_codex_config_override(isolation_args, f"model={json.dumps(model_id)}"):
                    add_issue(issues, "fail", "route_isolation_model", f"run {row.get('run_id')} Codex argv does not pin model")
                if reasoning_effort and not has_codex_config_override(isolation_args, f"model_reasoning_effort={json.dumps(reasoning_effort)}"):
                    add_issue(issues, "fail", "route_isolation_reasoning", f"run {row.get('run_id')} Codex argv does not pin reasoning effort")
                if factors.semantic_access_enabled:
                    if not has_codex_config_override(isolation_args, "mcp_servers=", ("serena", "start-mcp-server", "stdio")):
                        add_issue(issues, "fail", "route_isolation_semantic_mcp", f"run {row.get('run_id')} semantic arm lacks controlled Serena MCP override")
                elif not has_codex_config_override(isolation_args, "mcp_servers={}"):
                    add_issue(issues, "fail", "route_isolation_empty_mcp", f"run {row.get('run_id')} nonsemantic arm lacks empty MCP override")
                if isolation_env.get("RARB_HERMETIC_AGENT_HOME") != "1":
                    add_issue(issues, "fail", "route_isolation_env", f"run {row.get('run_id')} route isolation lacks hermetic home env marker")
                if isolation_env.get("RARB_SEMANTIC_ACCESS_ENABLED") != ("1" if factors.semantic_access_enabled else "0"):
                    add_issue(issues, "fail", "route_isolation_env", f"run {row.get('run_id')} semantic env marker differs from treatment factor")
                if isolation_env.get("RARB_ROUTING_DISCIPLINE_ENABLED") != ("1" if factors.routing_discipline_enabled else "0"):
                    add_issue(issues, "fail", "route_isolation_env", f"run {row.get('run_id')} routing env marker differs from treatment factor")
        if launch_plan is None:
            add_issue(issues, "fail", "launch_plan_artifact", f"run {row.get('run_id')} has no launch-plan.json")
        elif route_isolation is not None:
            command = launch_plan.get("command")
            if not isinstance(command, list) or command != [route_isolation.get("command"), *(route_isolation.get("args") or [])]:
                add_issue(issues, "fail", "launch_plan_invocation", f"run {row.get('run_id')} launch plan command differs from route isolation")
            if launch_plan.get("env") != route_isolation.get("env"):
                add_issue(issues, "fail", "launch_plan_env", f"run {row.get('run_id')} launch plan env differs from route isolation")
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
        if not row.get("snapshot_state_hmac"):
            add_issue(issues, "fail", "snapshot_state_hmac", f"run {row.get('run_id')} has no snapshot state HMAC")
        for field in ("source_commit", "snapshot_commit", "source_tree_hash", "snapshot_tree_hash"):
            if not is_git_object_id(row.get(field)):
                add_issue(issues, "fail", field, f"run {row.get('run_id')} has no valid {field}")
        if row.get("source_commit") and row.get("snapshot_commit") and row.get("source_commit") != row.get("snapshot_commit"):
            add_issue(issues, "fail", "source_snapshot_commit_match", f"run {row.get('run_id')} source and snapshot commits differ")
        if row.get("source_tree_hash") and row.get("snapshot_tree_hash") and row.get("source_tree_hash") != row.get("snapshot_tree_hash"):
            add_issue(issues, "fail", "source_snapshot_tree_match", f"run {row.get('run_id')} source and snapshot trees differ")
        if not row.get("snapshot_tree_hash"):
            add_issue(issues, "fail", "snapshot_tree_hash", f"run {row.get('run_id')} has no snapshot tree hash")
        if "lockfile_hash" not in row or row.get("lockfile_hash") in {"", None}:
            add_issue(issues, "fail", "lockfile_hash", f"run {row.get('run_id')} has no lockfile hash marker")
        if not lock_hash_present(row.get("source_lockfile_hash")) or not lock_hash_present(row.get("lockfile_hash")):
            add_issue(issues, "fail", "lockfile_hash_shape", f"run {row.get('run_id')} has invalid lockfile hash markers")
        if row.get("source_lockfile_hash") != row.get("lockfile_hash"):
            add_issue(issues, "fail", "source_snapshot_lockfile_match", f"run {row.get('run_id')} source and snapshot lockfile hashes differ")
        repo_key = str(row.get("repo", "")) or "default"
        source_state = manifest_repo_state(manifest, repo_key, "source_repo_states")
        snapshot_state = manifest_repo_state(manifest, repo_key, "repo_snapshots")
        if source_state:
            if source_state.get("dirty") is not False:
                add_issue(issues, "fail", "source_repo_clean", f"run {row.get('run_id')} source repository state is not clean")
            if row.get("source_commit") != source_state.get("commit"):
                add_issue(issues, "fail", "row_source_commit_match", f"run {row.get('run_id')} source commit does not match manifest")
            if row.get("source_tree_hash") != source_state.get("tree_hash"):
                add_issue(issues, "fail", "row_source_tree_match", f"run {row.get('run_id')} source tree hash does not match manifest")
            if row.get("source_lockfile_hash") != source_state.get("lockfile_hash"):
                add_issue(issues, "fail", "row_source_lockfile_match", f"run {row.get('run_id')} source lockfile hash does not match manifest")
        if snapshot_state:
            if snapshot_state.get("snapshot_dirty") is not False:
                add_issue(issues, "fail", "snapshot_repo_clean", f"run {row.get('run_id')} snapshot repository state is not clean")
            if row.get("snapshot_commit") != snapshot_state.get("snapshot_commit"):
                add_issue(issues, "fail", "row_snapshot_commit_match", f"run {row.get('run_id')} snapshot commit does not match manifest")
            if row.get("snapshot_tree_hash") != snapshot_state.get("snapshot_tree_hash"):
                add_issue(issues, "fail", "row_snapshot_tree_match", f"run {row.get('run_id')} snapshot tree hash does not match manifest")
            if row.get("lockfile_hash") != snapshot_state.get("lockfile_hash"):
                add_issue(issues, "fail", "row_snapshot_lockfile_match", f"run {row.get('run_id')} snapshot lockfile hash does not match manifest")
        if live:
            for field in ("codex_version", "serena_version", "os_version"):
                value = str(row.get(field, ""))
                if not value or value.startswith("not_available"):
                    add_issue(issues, "fail", field, f"live study run {row.get('run_id')} lacks usable {field}")
            if row.get("token_source") != "exact":
                add_issue(issues, "fail", "exact_token_source", f"live study run {row.get('run_id')} is not exact-token sourced")
            if not isinstance(row.get("exact_uncached_input_tokens"), int):
                add_issue(issues, "fail", "exact_uncached_input_tokens", f"live study run {row.get('run_id')} lacks exact uncached input tokens")
            for timing_field in ("semantic_setup_seconds", "task_execution_seconds", "end_to_end_seconds"):
                value = row.get(timing_field)
                if not isinstance(value, int | float) or value < 0:
                    add_issue(issues, "fail", timing_field, f"live study run {row.get('run_id')} lacks non-negative {timing_field}")
        semantic_session = semantic_session_for_row(row)
        if semantic_session is None:
            add_issue(issues, "fail", "semantic_session_artifact", f"run {row.get('run_id')} has no semantic-session.json")
        else:
            language_versions = semantic_session.get("language_server_versions")
            if not isinstance(language_versions, dict):
                add_issue(issues, "fail", "semantic_language_versions", f"run {row.get('run_id')} semantic session lacks language-server version metadata")
            else:
                for tool_name, row_field in LANGUAGE_SERVER_VERSION_FIELDS.items():
                    if str(language_versions.get(tool_name, "")) != str(row.get(row_field, "")):
                        add_issue(
                            issues,
                            "fail",
                            "semantic_language_version_match",
                            f"run {row.get('run_id')} {tool_name} version differs between row and semantic-session artifact",
                        )
            if semantic_session.get("semantic_access_enabled") != factors.semantic_access_enabled:
                add_issue(issues, "fail", "semantic_session_factor", f"run {row.get('run_id')} semantic-session factor mismatch")
            pre_process_state = semantic_session.get("pre_task_process_state")
            post_process_state = semantic_session.get("post_task_process_state")
            if not isinstance(pre_process_state, dict) or not isinstance(post_process_state, dict):
                add_issue(issues, "fail", "semantic_process_state", f"run {row.get('run_id')} lacks semantic pre/post process-state evidence")
            else:
                if row.get("serena_process_state_before") != pre_process_state:
                    add_issue(issues, "fail", "semantic_process_state_match", f"run {row.get('run_id')} pre-task process state differs between row and artifact")
                if row.get("serena_process_state_after") != post_process_state:
                    add_issue(issues, "fail", "semantic_process_state_match", f"run {row.get('run_id')} post-task process state differs between row and artifact")
                if confirmatory and not process_state_is_zero(pre_process_state):
                    add_issue(issues, "fail", "semantic_process_state_clean", f"run {row.get('run_id')} did not start from zero Serena/LSP process state")
                if confirmatory and not process_state_is_zero(post_process_state):
                    add_issue(issues, "fail", "semantic_teardown", f"run {row.get('run_id')} left Serena/LSP processes after completion")
            if row.get("semantic_lifecycle_owner") != semantic_session.get("lifecycle_owner"):
                add_issue(issues, "fail", "semantic_lifecycle_owner", f"run {row.get('run_id')} lifecycle owner differs between row and artifact")
            if row.get("semantic_teardown_verified") != semantic_session.get("teardown_verified"):
                add_issue(issues, "fail", "semantic_teardown", f"run {row.get('run_id')} teardown verification differs between row and artifact")
            if row.get("semantic_process_survivor_count") != semantic_session.get("process_survivor_count"):
                add_issue(issues, "fail", "semantic_teardown", f"run {row.get('run_id')} survivor count differs between row and artifact")
            if row.get("semantic_child_lsp_survivor_count") != semantic_session.get("child_lsp_survivor_count"):
                add_issue(issues, "fail", "semantic_teardown", f"run {row.get('run_id')} child LSP survivor count differs between row and artifact")
            if confirmatory:
                if semantic_session.get("teardown_verified") is not True or row.get("semantic_teardown_verified") is not True:
                    add_issue(issues, "fail", "semantic_teardown", f"run {row.get('run_id')} lacks verified semantic teardown")
                if semantic_session.get("process_survivor_count") != 0 or row.get("semantic_process_survivor_count") != 0:
                    add_issue(issues, "fail", "semantic_teardown", f"run {row.get('run_id')} has nonzero Serena/LSP survivors")
                if semantic_session.get("child_lsp_survivor_count") != 0 or row.get("semantic_child_lsp_survivor_count") != 0:
                    add_issue(issues, "fail", "semantic_teardown", f"run {row.get('run_id')} has nonzero child LSP survivors")
            if factors.semantic_access_enabled:
                session_id = str(semantic_session.get("session_id", ""))
                semantic_session_ids[session_id] += 1
                if not session_id or session_id != row.get("run_id"):
                    add_issue(issues, "fail", "semantic_session_id", f"run {row.get('run_id')} semantic session id must match run id")
                if semantic_session.get("mode") != "codex_mcp_stdio_per_run":
                    add_issue(issues, "fail", "semantic_session_mode", f"run {row.get('run_id')} semantic session is not per-run Codex MCP stdio")
                if semantic_session.get("isolated") is not True:
                    add_issue(issues, "fail", "semantic_session_isolation", f"run {row.get('run_id')} semantic session is not isolated")
                if semantic_session.get("mcp_server_configured") is not True:
                    add_issue(issues, "fail", "semantic_mcp_config", f"run {row.get('run_id')} has no semantic MCP config")
                if semantic_session.get("transport") != "stdio":
                    add_issue(issues, "fail", "semantic_session_transport", f"run {row.get('run_id')} semantic session must use stdio transport")
                semantic_home = str(semantic_session.get("semantic_session_home", ""))
                run_dir = str(row.get("run_dir", ""))
                if not semantic_home or not Path(semantic_home).exists() or not path_is_under(semantic_home, run_dir):
                    add_issue(issues, "fail", "semantic_session_home", f"run {row.get('run_id')} semantic session home is not inside the run directory")
                for field in ("serena_home", "xdg_config_home", "xdg_cache_home", "xdg_data_home"):
                    value = str(semantic_session.get(field, ""))
                    if not value or not Path(value).exists() or not path_is_under(value, semantic_home):
                        add_issue(issues, "fail", field, f"run {row.get('run_id')} semantic {field} is not inside the session home")
                env_keys = {str(item) for item in semantic_session.get("mcp_env_keys", []) or []}
                required_env_keys = {"RARB_SERENA_SESSION_HOME", "SERENA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"}
                if required_env_keys - env_keys:
                    add_issue(issues, "fail", "semantic_session_env", f"run {row.get('run_id')} semantic session lacks isolated env keys")
                if not is_hmac_fingerprint(semantic_session.get("project_path_hmac")):
                    add_issue(issues, "fail", "semantic_project_path_hmac", f"run {row.get('run_id')} semantic session lacks project path HMAC")
                if not is_hmac_fingerprint(row.get("semantic_session_id_hmac")):
                    add_issue(issues, "fail", "semantic_session_id_hmac", f"run {row.get('run_id')} lacks semantic session id HMAC")
                if confirmatory and live:
                    if row.get("serena_readiness_status") != "pass" or row.get("serena_readiness_ready") is not True:
                        add_issue(issues, "fail", "semantic_readiness", f"run {row.get('run_id')} semantic readiness did not pass before task execution")
                    if semantic_session.get("readiness_status") != "pass" or semantic_session.get("readiness_ready") is not True:
                        add_issue(issues, "fail", "semantic_session_readiness", f"run {row.get('run_id')} semantic-session artifact does not prove passed readiness")
                    readiness_path = Path(str(row.get("run_dir", ""))) / "serena-readiness.json"
                    if not readiness_path.exists():
                        add_issue(issues, "fail", "semantic_readiness_artifact", f"run {row.get('run_id')} has no serena-readiness.json")
                    else:
                        readiness_payload = load_json(readiness_path)
                        readiness_env_keys = {str(item) for item in readiness_payload.get("isolated_env_keys", []) or []}
                        readiness_process_state_after = readiness_payload.get("process_state_after")
                        if readiness_payload.get("status") != "pass" or readiness_payload.get("ready") is not True:
                            add_issue(issues, "fail", "semantic_readiness_artifact", f"run {row.get('run_id')} readiness artifact did not pass")
                        if str(readiness_payload.get("semantic_session_home", "")) != semantic_home:
                            add_issue(issues, "fail", "semantic_readiness_isolation", f"run {row.get('run_id')} readiness used a different semantic session home")
                        if required_env_keys - readiness_env_keys:
                            add_issue(issues, "fail", "semantic_readiness_isolation", f"run {row.get('run_id')} readiness lacks isolated semantic env keys")
                        if row.get("serena_process_state_after_readiness") != readiness_process_state_after:
                            add_issue(issues, "fail", "semantic_readiness_process_state", f"run {row.get('run_id')} row and readiness artifact disagree on post-readiness process state")
                        if semantic_session.get("readiness_process_state_after") != readiness_process_state_after:
                            add_issue(issues, "fail", "semantic_readiness_process_state", f"run {row.get('run_id')} semantic-session and readiness artifact disagree on post-readiness process state")
                        if not process_state_is_zero(readiness_process_state_after):
                            add_issue(issues, "fail", "semantic_readiness_process_state", f"run {row.get('run_id')} readiness prewarm left Serena/LSP process state before task execution")
            else:
                if semantic_session.get("mode") != "disabled" or semantic_session.get("mcp_server_configured") is not False:
                    add_issue(issues, "fail", "semantic_session_disabled", f"run {row.get('run_id')} search-only semantic session is not disabled")
                if semantic_session.get("session_id") not in {"", None} or row.get("semantic_session_id_hmac") not in {"", None}:
                    add_issue(issues, "fail", "semantic_session_disabled_id", f"run {row.get('run_id')} search-only semantic session must not carry a session id")
        if not (Path(str(row.get("run_dir", ""))) / "oracle.json").exists():
            add_issue(issues, "fail", "oracle_artifact", f"run {row.get('run_id')} has no oracle.json")
        if row.get("oracle_status") in {"", "not_configured", None}:
            add_issue(issues, "fail", "oracle_status", f"run {row.get('run_id')} has no configured external oracle")
        key = (
            str(row.get("agent", "")),
            str(row.get("task_id", "")),
            str(row.get("repo", "")),
            int(row.get("repeat_index", 0)),
        )
        cells_by_block[key][profile] = row

    for arm in FACTORIAL_ARM_ORDER:
        counts = [positions_by_arm[(arm, position)] for position in range(1, 5)]
        if len(set(counts)) > 1:
            add_issue(issues, "fail", "position_balance", f"{arm} position counts are not balanced: {counts}")
    duplicate_semantic_sessions = [session_id for session_id, count in semantic_session_ids.items() if session_id and count > 1]
    if duplicate_semantic_sessions:
        add_issue(issues, "fail", "semantic_session_unique", "semantic session ids must be unique per semantic run")
    task_ids = sorted(
        {
            (str(row.get("agent", "")), str(row.get("task_id", "")), str(row.get("repo", "")))
            for row in rows
        }
    )
    for agent, task_id, repo in task_ids:
        for arm in FACTORIAL_ARM_ORDER:
            counts = [positions_by_task_arm[(agent, task_id, repo, arm, position)] for position in range(1, 5)]
            if len(set(counts)) > 1:
                add_issue(issues, "fail", "task_position_balance", f"{agent}/{repo}/{task_id}/{arm} position counts are not balanced: {counts}")

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
        for field in TOOL_VERSION_FIELDS:
            versions = {str(row.get(field, "")) for row in profile_rows.values()}
            if len(versions) != 1:
                add_issue(issues, "fail", "block_tool_version_match", f"{key} {field} differs across arms")
        for left, right in FACTORIAL_COMPARISONS:
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

    if confirmatory:
        analysis_path = base / "study-analysis.json"
        if not analysis_path.exists():
            add_issue(issues, "fail", "study_analysis", "confirmatory study requires study-analysis.json")
        else:
            analysis = load_json(analysis_path)
            if not _analysis_has_required_shape(analysis):
                add_issue(issues, "fail", "study_analysis_shape", "study-analysis.json lacks required paired, sensitivity, factorial, correctness, or CI fields")
            if not _analysis_matches_preregistered_primary(analysis):
                add_issue(issues, "fail", "study_analysis_metric", "confirmatory analysis must use preregistered exact_uncached_input_tokens metric")
            if not _analysis_cost_has_required_shape(analysis, manifest):
                add_issue(issues, "fail", "study_analysis_cost", "study-analysis.json has missing or invalid estimated-cost metadata")
            if _analysis_has_required_shape(analysis) and not _analysis_matches_rows(analysis, base):
                add_issue(issues, "fail", "study_analysis_consistency", "study-analysis.json does not match recomputed results from runs.jsonl")
            correctness = analysis.get("correctness_pairwise", {})
            if isinstance(correctness, dict):
                for name, value in correctness.items():
                    if isinstance(value, dict) and value.get("noninferiority_passed") is not True:
                        add_issue(issues, "fail", "correctness_noninferiority", f"{name} did not pass correctness non-inferiority")
        power_path = base / "study-power.json"
        if not power_path.exists():
            add_issue(issues, "fail", "study_power", "confirmatory study requires study-power.json")
        else:
            power = load_json(power_path)
            if power.get("status") != "estimated":
                add_issue(issues, "fail", "study_power_status", "study-power.json must have status=estimated")
            if not _power_matches_preregistered_primary(power):
                add_issue(issues, "fail", "study_power_metric", "study-power.json must use the preregistered exact_uncached_input_tokens planning inputs")
            if not _power_has_required_shape(power):
                add_issue(issues, "fail", "study_power_shape", "study-power.json must include all preregistered pairwise power estimates")
            if _power_has_required_shape(power) and not _power_matches_rows(power, rows):
                add_issue(issues, "fail", "study_power_consistency", "study-power.json does not match recomputed results from runs.jsonl")
            if power.get("power_target_met") is not True:
                add_issue(issues, "fail", "study_power_target", "observed study cells do not meet the planned power target")

    status = "pass" if not any(issue["severity"] == "fail" for issue in issues) else "fail"
    return {
        "status": status,
        "run_count": len(rows),
        "confirmatory": confirmatory,
        "issues": issues,
        "arm_counts": dict(Counter(str(row.get("profile", "")) for row in rows)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a router-effect-v1 real-agent study output.")
    parser.add_argument("--root", required=True, help="Benchmark output directory.")
    parser.add_argument("--out", help="Optional JSON output path.")
    parser.add_argument("--confirmatory", action="store_true", help="Apply publishable confirmatory-study gates.")
    parser.add_argument("--min-task-families", type=int, default=5)
    parser.add_argument("--min-tasks-per-family", type=int, default=3)
    args = parser.parse_args(argv)
    result = audit(
        args.root,
        confirmatory=args.confirmatory,
        min_task_families=args.min_task_families,
        min_tasks_per_family=args.min_tasks_per_family,
    )
    if args.out:
        to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
