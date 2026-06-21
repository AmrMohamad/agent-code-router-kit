#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".serena",
    "__pycache__",
    "results",
    "raw",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "build",
    "dist",
}

SKIP_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".jks",
    ".keystore",
    ".pyc",
}

PNG_SUFFIXES = {".png"}
PNG_METADATA_CHUNKS = {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}
PUBLIC_EVIDENCE_PARTS = ("benchmarks", "real-agent-routing", "evidence")
CODEX_SMOKE_EVIDENCE_PARTS = (*PUBLIC_EVIDENCE_PARTS, "codex-ad-smoke-anonymized")
ROUTER_EFFECT_STUDY_ID = "router-effect-v1"
CODEX_SMOKE_ALLOWED_FILES = {
    "README.md",
    "audit.sanitized.json",
    "claim-readiness.sanitized.json",
    "evidence-manifest.sanitized.json",
    "route-isolation.sanitized.jsonl",
    "runs.sanitized.jsonl",
    "source.sanitized.json",
    "summary.sanitized.json",
}
ROUTER_EFFECT_STUDY_ALLOWED_FILES = {
    "README.md",
    "analysis.sanitized.json",
    "artifact-hashes.sha256.json",
    "audit.sanitized.json",
    "manifest.sanitized.json",
    "power.sanitized.json",
    "runs.sanitized.jsonl",
    "treatment-diffs.sanitized.jsonl",
}
CODEX_SMOKE_TOP_LEVEL_KEYS = {
    "source.sanitized.json": {
        "audit",
        "claim_readiness",
        "created_at",
        "limitations",
        "privacy_note",
        "route_isolation",
        "runs",
        "scope",
        "targets",
        "title",
        "version_capture",
    },
    "summary.sanitized.json": {
        "created_at",
        "evidence_files",
        "paired_results",
        "pooled_descriptive_total",
        "privacy_note",
        "scope",
        "target_nature",
        "title",
        "trade_off",
    },
    "claim-readiness.sanitized.json": {
        "agent_reported_token_savings_claims_supported",
        "exact_token_savings_claims_supported",
        "exact_uncached_token_savings_claims_supported",
        "model_visible_proxy_savings_claims_supported",
        "paired_comparisons",
        "rows",
        "scope",
    },
    "audit.sanitized.json": {
        "all_scoped_smoke_audits_passed",
        "audit_flags",
        "rows",
        "scope",
    },
    "evidence-manifest.sanitized.json": {
        "artifact_hashes_sha256",
        "artifact_hashes_sha256_note",
        "artifact_path_mode",
        "evidence_directory",
        "limitations",
        "privacy_policy",
        "schema_version",
        "targets",
        "title",
        "version_capture",
    },
}
CODEX_SMOKE_JSONL_ROW_KEYS = {
    "runs.sanitized.jsonl": {
        "agent",
        "ast_grep_count",
        "completion_reason",
        "correctness_status",
        "exact_cached_input_tokens",
        "exact_input_tokens",
        "exact_output_tokens",
        "exact_reasoning_output_tokens",
        "exact_total_tokens",
        "exact_uncached_input_tokens",
        "exact_uncached_total_tokens",
        "expected_proof_layer_seen",
        "expected_success_signal_seen",
        "files_opened_count",
        "mcp_servers_hard_disabled",
        "model_visible_proxy_tokens",
        "observed_task_tools",
        "policy_adherence",
        "policy_violations",
        "profile",
        "repeat_index",
        "route_hard_controls",
        "route_isolation_mode",
        "route_weak_controls",
        "runtime_tool_count",
        "search_count",
        "semantic_tool_count",
        "semantic_tools_disabled",
        "target_id",
        "target_label",
        "task_family",
        "token_source",
        "tool_call_count",
        "tool_evidence_source",
        "tool_output_bytes",
        "usage_event_count",
        "wall_seconds",
    },
    "route-isolation.sanitized.jsonl": {
        "agent",
        "blocked_tool_violation_count",
        "command_shape",
        "hard_controls",
        "mcp_servers_hard_disabled",
        "observed_task_tools",
        "profile",
        "route_isolation_mode",
        "semantic_tools_disabled",
        "target_id",
        "target_label",
        "weak_controls",
    },
}
CODEX_SMOKE_SOURCE_CLAIM_ROW_KEYS = {
    "agent",
    "agent_reported_claim_blockers",
    "agent_reported_token_savings_claim_supported",
    "baseline_exact_uncached_total_tokens",
    "correctness_ok",
    "exact_claim_blockers",
    "exact_token_savings_claim_supported",
    "exact_token_savings_percent",
    "exact_uncached_token_savings_claim_supported",
    "exact_uncached_token_savings_percent",
    "model_visible_proxy_savings_claim_supported",
    "model_visible_proxy_token_savings_percent",
    "repeat_index",
    "target_id",
    "target_label",
    "treatment_exact_uncached_total_tokens",
}
CODEX_SMOKE_CLAIM_ROW_KEYS = CODEX_SMOKE_SOURCE_CLAIM_ROW_KEYS | {
    "treatment_minus_baseline_exact_uncached_tokens",
    "uncached_tokens_avoided",
}
ROUTER_EFFECT_STUDY_TOP_LEVEL_KEYS = {
    "manifest.sanitized.json": {
        "agents",
        "controller_commit",
        "controller_dirty",
        "controller_tree_hash",
        "isolated_agent_home",
        "isolated_serena_session",
        "model_id",
        "order_design",
        "parallelism",
        "privacy",
        "reasoning_effort",
        "repo_count",
        "repository_labels",
        "require_clean_serena_process_state",
        "require_explicit_reasoning_effort",
        "route_profile_hashes",
        "snapshot_scope",
        "snapshot_repos",
        "study_id",
        "study_package",
        "task_count",
        "tool_versions",
    },
    "audit.sanitized.json": {
        "audit_mode",
        "arm_counts",
        "fail_count",
        "issue_counts",
        "min_task_families",
        "min_tasks_per_family",
        "run_count",
        "status",
    },
    "analysis.sanitized.json": {
        "analysis_id",
        "arm_counts",
        "bootstrap",
        "cell_key_fields",
        "cluster_unit",
        "correctness_counts",
        "correctness_noninferiority_margin",
        "correctness_pairwise",
        "cost",
        "expected_arms",
        "factorial_effects",
        "factorial_effects_by_repo",
        "factorial_effects_by_task_family",
        "intention_to_treat_run_count",
        "metric",
        "multiple_comparison_correction",
        "notes",
        "pairwise_effects",
        "pairwise_effects_by_repo",
        "pairwise_effects_by_sequence_position",
        "pairwise_effects_by_task_family",
        "pass_all_sensitivity_factorial_effects",
        "pass_pass_sensitivity_pairwise_effects",
        "run_count",
    },
    "power.sanitized.json": {
        "all_preregistered_comparisons_power_target_met",
        "alpha",
        "cell_key_fields",
        "cluster_unit",
        "method",
        "metric",
        "minimum_effect",
        "minimum_effect_log",
        "observed_pairs",
        "pair_count",
        "pairwise_power",
        "pilot_log_ratio_variance",
        "power",
        "power_target_met",
        "primary_comparison",
        "recommended_pairs",
        "recommended_repeats_floor",
        "status",
        "z_alpha_two_sided",
        "z_power",
    },
}
ROUTER_EFFECT_STUDY_RUN_ROW_KEYS = {
    "agent",
    "agent_config_hash",
    "ast_grep_count",
    "ast_grep_version",
    "block_id",
    "codex_version",
    "completion_reason",
    "controller_commit",
    "controller_tree_hash",
    "correctness_status",
    "dynamic_target_hmac",
    "end_to_end_seconds",
    "exact_cached_input_tokens",
    "exact_input_tokens",
    "exact_output_tokens",
    "exact_reasoning_output_tokens",
    "exact_total_tokens",
    "exact_uncached_input_tokens",
    "exact_uncached_total_tokens",
    "exact_usage_event_count",
    "files_opened_count",
    "fd_version",
    "git_version",
    "json_language_server_version",
    "kotlin_language_server_version",
    "model_visible_bytes",
    "node_version",
    "npm_version",
    "oracle_status",
    "order_design",
    "os_version",
    "observed_task_tools",
    "policy_adherence",
    "previous_arm",
    "profile",
    "protocol_commit",
    "python_version",
    "pnpm_version",
    "repeat_index",
    "repo_public_id",
    "response_contract_hash",
    "route_hard_controls",
    "route_isolation_mode",
    "route_profile_hash",
    "route_weak_controls",
    "routing_discipline_enabled",
    "rg_version",
    "runtime_tool_count",
    "run_id",
    "search_count",
    "semantic_access_enabled",
    "semantic_child_lsp_survivor_count",
    "semantic_lifecycle_owner",
    "semantic_process_survivor_count",
    "semantic_project_path_hmac",
    "semantic_session_artifact",
    "semantic_session_id_hmac",
    "semantic_session_isolated",
    "semantic_session_mode",
    "semantic_setup_seconds",
    "semantic_teardown_verified",
    "semantic_tool_count",
    "sequence_id",
    "sequence_position",
    "serena_process_state_after",
    "serena_process_state_before",
    "serena_version",
    "snapshot_key_hmac",
    "snapshot_scope",
    "snapshot_state_hmac",
    "source_state_hmac",
    "sourcekit_lsp_version",
    "study_id",
    "task_execution_seconds",
    "task_family",
    "task_prompt_hmac",
    "task_public_id",
    "tsc_version",
    "typescript_language_server_version",
    "token_source",
    "tool_call_count",
    "tool_evidence_source",
    "tool_output_bytes",
    "wall_seconds",
    "yarn_version",
}
ROUTER_EFFECT_TREATMENT_DIFF_ROW_KEYS = {
    "agent",
    "block_id",
    "comparisons",
    "missing_profiles",
    "repeat_index",
    "repo_public_id",
    "task_family",
    "task_public_id",
    "valid",
}
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_TARGET_LABELS = {"Commerce Web Frontend", "Native iOS Commerce App"}
ALLOWED_OBSERVED_TOOLS = {"rg", "sed", "find_symbol", "get_symbols_overview"}
ABSOLUTE_USER_PATH_RE = re.compile(r"(?i)(/users/[^\\s\"']+|/home/[^\\s\"']+|[a-z]:\\\\users\\\\[^\\s\"']+|/private/tmp/[^\\s\"']+)")
EMAIL_RE = re.compile(r"(?i)\\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}\\b")
URL_SECRET_RE = re.compile(r"(?i)[?&](token|api[_-]?key|apikey|access[_-]?token|secret|password)=")
AUTH_VALUE_RE = re.compile(r"(?i)authorization\\s*[:=]\\s*(bearer|basic)\\s+")


@dataclass(frozen=True)
class BannedToken:
    label: str
    token: str


def join(*parts: str) -> str:
    return "".join(parts)


def banned_tokens() -> list[BannedToken]:
    specs = [
        ("old_company_name", ("ro", "busta")),
        ("old_b2b_app_name", ("ma", "zaya")),
        ("old_retail_app_name", ("pan", "da")),
        ("old_b2b_display_suffix", ("b2", "bapp")),
        ("old_retail_repo_fragment", ("customer", "-app")),
        ("old_b2b_repo_fragment", ("group", "-b2b")),
        ("private_home_path", ("/users/", "amr", "mohamad")),
        ("private_company_path", ("developer/", "ro", "busta")),
        ("old_b2b_package_prefix", ("com.", "ma", "zaya")),
        ("old_retail_package_prefix", ("com.", "pan", "da")),
        ("old_feature_symbol_one", ("notifications", "viewmodel")),
        ("old_feature_symbol_two", ("dynamic", "content", "viewmodel")),
        ("old_service_symbol", ("apppush", "notifications", "service")),
        ("old_graphql_symbol", ("graphql", "clientimp")),
        ("old_analytics_key", ("clar", "ity_id")),
        ("old_staging_map_key", ("staging", ".map", ".api", ".key")),
        ("old_production_map_key", ("production", ".map", ".api", ".key")),
    ]
    return [BannedToken(label, join(*parts).lower()) for label, parts in specs]


def git_release_files(root: Path) -> list[Path]:
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    proc = subprocess.run(cmd, cwd=root, check=True, stdout=subprocess.PIPE)
    files: list[Path] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        files.append(root / raw.decode())
    return files


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    if path.name == ".DS_Store":
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def decode_bytes(raw: bytes, encoding: str = "utf-8") -> str:
    return raw.decode(encoding, errors="replace")


def png_metadata_chunks(path: Path) -> list[tuple[str, str]]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return []

    chunks: list[tuple[str, str]] = []
    offset = 8
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            break
        payload = data[start:end]
        if kind not in PNG_METADATA_CHUNKS:
            offset = end + 4
            continue
        kind_text = decode_bytes(kind, "ascii")
        if kind == b"eXIf":
            chunks.append((f"png metadata {kind_text}", f"{len(payload)} bytes"))
        elif kind == b"tEXt":
            chunks.append((f"png metadata {kind_text}", decode_bytes(payload, "latin-1")))
        elif kind == b"zTXt":
            value = f"{len(payload)} bytes"
            keyword, separator, rest = payload.partition(b"\0")
            if separator and rest:
                compression_method = rest[0]
                compressed = rest[1:]
                if compression_method == 0:
                    try:
                        text = zlib.decompress(compressed)
                    except zlib.error:
                        text = compressed
                    value = f"{decode_bytes(keyword, 'latin-1')}\0{decode_bytes(text, 'latin-1')}"
                else:
                    value = f"{decode_bytes(keyword, 'latin-1')}\0unsupported-compression-method:{compression_method}"
            chunks.append((f"png metadata {kind_text}", value))
        elif kind == b"iTXt":
            value = f"{len(payload)} bytes"
            keyword, separator, rest = payload.partition(b"\0")
            if separator and len(rest) >= 2:
                compression_flag = rest[0]
                compression_method = rest[1]
                language, _, rest = rest[2:].partition(b"\0")
                translated_keyword, _, text = rest.partition(b"\0")
                if compression_flag == 1 and compression_method == 0:
                    try:
                        text = zlib.decompress(text)
                    except zlib.error:
                        pass
                value = "\0".join(
                    [
                        decode_bytes(keyword),
                        decode_bytes(language),
                        decode_bytes(translated_keyword),
                        decode_bytes(text),
                    ]
                )
            chunks.append((f"png metadata {kind_text}", value))
        offset = end + 4
    return chunks


def png_text_chunks(path: Path) -> list[tuple[str, str]]:
    return [
        (where, value)
        for where, value in png_metadata_chunks(path)
        if where in {"png metadata tEXt", "png metadata zTXt", "png metadata iTXt"}
    ]


def is_public_evidence_path(rel: Path) -> bool:
    return len(rel.parts) >= len(PUBLIC_EVIDENCE_PARTS) and rel.parts[: len(PUBLIC_EVIDENCE_PARTS)] == PUBLIC_EVIDENCE_PARTS


def is_codex_smoke_evidence_path(rel: Path) -> bool:
    return len(rel.parts) >= len(CODEX_SMOKE_EVIDENCE_PARTS) and rel.parts[: len(CODEX_SMOKE_EVIDENCE_PARTS)] == CODEX_SMOKE_EVIDENCE_PARTS


def is_router_effect_study_evidence_path(path: Path, rel: Path) -> bool:
    if is_codex_smoke_evidence_path(rel) or not is_public_evidence_path(rel):
        return False
    manifest_path = path if path.name == "manifest.sanitized.json" else path.parent / "manifest.sanitized.json"
    if not manifest_path.exists():
        return False
    if path.name == "manifest.sanitized.json":
        return True
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return isinstance(manifest, dict) and manifest.get("study_id") == ROUTER_EFFECT_STUDY_ID


def iter_json_values(value: object, json_path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from iter_json_values(item, f"{json_path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_json_values(item, f"{json_path}[{index}]")
    elif isinstance(value, str):
        yield json_path, value


def evidence_json_payloads(path: Path) -> list[object]:
    try:
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if path.suffix == ".json":
            return [json.loads(path.read_text(encoding="utf-8"))]
    except json.JSONDecodeError:
        return [{"__invalid_json__": path.name}]
    return []


def public_evidence_schema_violations(path: Path, root: Path) -> list[dict[str, str]]:
    rel = path.relative_to(root)
    if not is_public_evidence_path(rel):
        return []
    rel_text = rel.as_posix()
    violations: list[dict[str, str]] = []
    is_codex_smoke = is_codex_smoke_evidence_path(rel)
    is_router_effect_study = is_router_effect_study_evidence_path(path, rel)
    if is_codex_smoke and path.name not in CODEX_SMOKE_ALLOWED_FILES:
        violations.append({"file": rel_text, "label": "evidence_unexpected_file", "where": "path"})
    if is_router_effect_study and path.name not in ROUTER_EFFECT_STUDY_ALLOWED_FILES:
        violations.append({"file": rel_text, "label": "evidence_unexpected_file", "where": "path"})
    for payload_index, payload in enumerate(evidence_json_payloads(path)):
        if isinstance(payload, dict) and "__invalid_json__" in payload:
            violations.append({"file": rel_text, "label": "evidence_invalid_json", "where": f"$[{payload_index}]"})
            continue
        if is_codex_smoke and path.name in CODEX_SMOKE_TOP_LEVEL_KEYS and isinstance(payload, dict):
            unexpected = set(payload) - CODEX_SMOKE_TOP_LEVEL_KEYS[path.name]
            for key in sorted(unexpected):
                violations.append(
                    {"file": rel_text, "label": "evidence_unexpected_json_field", "where": f"$[{payload_index}].{key}"}
                )
        if is_codex_smoke and path.name in CODEX_SMOKE_JSONL_ROW_KEYS and isinstance(payload, dict):
            unexpected = set(payload) - CODEX_SMOKE_JSONL_ROW_KEYS[path.name]
            for key in sorted(unexpected):
                violations.append(
                    {"file": rel_text, "label": "evidence_unexpected_json_field", "where": f"$[{payload_index}].{key}"}
                )
        if is_codex_smoke and path.name == "source.sanitized.json" and isinstance(payload, dict):
            for index, row in enumerate(payload.get("runs", [])):
                if isinstance(row, dict):
                    unexpected = set(row) - CODEX_SMOKE_JSONL_ROW_KEYS["runs.sanitized.jsonl"]
                    for key in sorted(unexpected):
                        violations.append(
                            {
                                "file": rel_text,
                                "label": "evidence_unexpected_json_field",
                                "where": f"$[{payload_index}].runs[{index}].{key}",
                            }
                        )
            for index, row in enumerate(payload.get("route_isolation", [])):
                if isinstance(row, dict):
                    unexpected = set(row) - CODEX_SMOKE_JSONL_ROW_KEYS["route-isolation.sanitized.jsonl"]
                    for key in sorted(unexpected):
                        violations.append(
                            {
                                "file": rel_text,
                                "label": "evidence_unexpected_json_field",
                                "where": f"$[{payload_index}].route_isolation[{index}].{key}",
                            }
                        )
            claim_section = payload.get("claim_readiness", {})
            claim_rows = claim_section.get("rows", []) if isinstance(claim_section, dict) else []
            for index, row in enumerate(claim_rows):
                if isinstance(row, dict):
                    unexpected = set(row) - CODEX_SMOKE_SOURCE_CLAIM_ROW_KEYS
                    for key in sorted(unexpected):
                        violations.append(
                            {
                                "file": rel_text,
                                "label": "evidence_unexpected_json_field",
                                "where": f"$[{payload_index}].claim_readiness.rows[{index}].{key}",
                            }
                        )
        if is_codex_smoke and path.name == "claim-readiness.sanitized.json" and isinstance(payload, dict):
            for index, row in enumerate(payload.get("rows", [])):
                if isinstance(row, dict):
                    unexpected = set(row) - CODEX_SMOKE_CLAIM_ROW_KEYS
                    for key in sorted(unexpected):
                        violations.append(
                            {
                                "file": rel_text,
                                "label": "evidence_unexpected_json_field",
                                "where": f"$[{payload_index}].rows[{index}].{key}",
                            }
                        )
        if is_router_effect_study and path.name in ROUTER_EFFECT_STUDY_TOP_LEVEL_KEYS and isinstance(payload, dict):
            unexpected = set(payload) - ROUTER_EFFECT_STUDY_TOP_LEVEL_KEYS[path.name]
            for key in sorted(unexpected):
                violations.append(
                    {"file": rel_text, "label": "evidence_unexpected_json_field", "where": f"$[{payload_index}].{key}"}
                )
        if is_router_effect_study and path.name == "runs.sanitized.jsonl" and isinstance(payload, dict):
            unexpected = set(payload) - ROUTER_EFFECT_STUDY_RUN_ROW_KEYS
            for key in sorted(unexpected):
                violations.append(
                    {"file": rel_text, "label": "evidence_unexpected_json_field", "where": f"$[{payload_index}].{key}"}
                )
        if is_router_effect_study and path.name == "treatment-diffs.sanitized.jsonl" and isinstance(payload, dict):
            unexpected = set(payload) - ROUTER_EFFECT_TREATMENT_DIFF_ROW_KEYS
            for key in sorted(unexpected):
                violations.append(
                    {"file": rel_text, "label": "evidence_unexpected_json_field", "where": f"$[{payload_index}].{key}"}
                )
        if is_router_effect_study and path.name == "artifact-hashes.sha256.json" and isinstance(payload, dict):
            expected_files = {
                item.name
                for item in path.parent.iterdir()
                if item.is_file()
                and item.name != "artifact-hashes.sha256.json"
                and item.name in ROUTER_EFFECT_STUDY_ALLOWED_FILES
            }
            unexpected_files = set(payload) - expected_files
            missing_files = expected_files - set(payload)
            for key in sorted(unexpected_files):
                violations.append(
                    {
                        "file": rel_text,
                        "label": "evidence_unexpected_artifact_hash_file",
                        "where": f"$[{payload_index}].{key}",
                    }
                )
            for key in sorted(missing_files):
                violations.append(
                    {
                        "file": rel_text,
                        "label": "evidence_missing_artifact_hash_file",
                        "where": f"$[{payload_index}].{key}",
                    }
                )
            for key, value in payload.items():
                if not isinstance(value, str) or not HEX64_RE.fullmatch(value):
                    violations.append(
                        {
                            "file": rel_text,
                            "label": "evidence_invalid_artifact_hash",
                            "where": f"$[{payload_index}].{key}",
                        }
                    )
        for json_path, value in iter_json_values(payload, f"$[{payload_index}]"):
            lower = value.lower()
            if ABSOLUTE_USER_PATH_RE.search(value):
                violations.append({"file": rel_text, "label": "evidence_absolute_private_path", "where": json_path})
            if EMAIL_RE.search(value):
                violations.append({"file": rel_text, "label": "evidence_email_address", "where": json_path})
            if URL_SECRET_RE.search(value) or AUTH_VALUE_RE.search(value):
                violations.append({"file": rel_text, "label": "evidence_secret_like_value", "where": json_path})
            is_target_label = json_path.endswith(".target_label") or (
                json_path.endswith(".label")
                and (".targets." in json_path or ".target_nature." in json_path)
            )
            if is_codex_smoke and is_target_label and value not in ALLOWED_TARGET_LABELS:
                violations.append({"file": rel_text, "label": "evidence_unapproved_target_label", "where": json_path})
            if (is_codex_smoke or is_router_effect_study) and "observed_task_tools" in json_path and lower not in ALLOWED_OBSERVED_TOOLS:
                violations.append({"file": rel_text, "label": "evidence_unapproved_observed_tool", "where": json_path})
    return violations


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None


def scan(root: Path) -> list[dict[str, str]]:
    tokens = banned_tokens()
    violations: list[dict[str, str]] = []
    for path in git_release_files(root):
        if not path.exists() or should_skip(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        violations.extend(public_evidence_schema_violations(path, root))
        rel_lower = rel.lower()
        for token in tokens:
            if token.token in rel_lower:
                violations.append({"file": rel, "label": token.label, "where": "path"})
        if path.suffix.lower() in PNG_SUFFIXES:
            for where, _metadata in png_metadata_chunks(path):
                violations.append({"file": rel, "label": "png_metadata_forbidden", "where": where})
            continue
        text = read_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for token in tokens:
                if token.token in lower:
                    violations.append(
                        {
                            "file": rel,
                            "label": token.label,
                            "where": f"line {line_no}",
                        }
                    )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check public files for private project identifiers.")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[3])
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    violations = scan(root)
    if violations:
        print("PUBLIC SANITIZATION FAILED")
        for item in violations:
            print(f"{item['file']}:{item['where']}: {item['label']}")
        return 1
    print("PUBLIC SANITIZATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
