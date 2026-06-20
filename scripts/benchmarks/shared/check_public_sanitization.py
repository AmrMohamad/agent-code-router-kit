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
        if kind == b"eXIf":
            chunks.append(("png metadata eXIf", f"{len(payload)} bytes"))
        elif kind == b"tEXt":
            chunks.append(("png metadata tEXt", decode_bytes(payload, "latin-1")))
        elif kind == b"zTXt":
            keyword, separator, rest = payload.partition(b"\0")
            if separator and rest:
                compression_method = rest[0]
                compressed = rest[1:]
                if compression_method == 0:
                    try:
                        text = zlib.decompress(compressed)
                    except zlib.error:
                        text = compressed
                    chunks.append(
                        (
                            "png metadata zTXt",
                            f"{decode_bytes(keyword, 'latin-1')}\0{decode_bytes(text, 'latin-1')}",
                        )
                    )
        elif kind == b"iTXt":
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
                chunks.append(
                    (
                        "png metadata iTXt",
                        "\0".join(
                            [
                                decode_bytes(keyword),
                                decode_bytes(language),
                                decode_bytes(translated_keyword),
                                decode_bytes(text),
                            ]
                        ),
                    )
                )
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
    if is_codex_smoke_evidence_path(rel) and path.name not in CODEX_SMOKE_ALLOWED_FILES:
        violations.append({"file": rel_text, "label": "evidence_unexpected_file", "where": "path"})
    for payload_index, payload in enumerate(evidence_json_payloads(path)):
        if isinstance(payload, dict) and "__invalid_json__" in payload:
            violations.append({"file": rel_text, "label": "evidence_invalid_json", "where": f"$[{payload_index}]"})
            continue
        if path.name in CODEX_SMOKE_TOP_LEVEL_KEYS and isinstance(payload, dict):
            unexpected = set(payload) - CODEX_SMOKE_TOP_LEVEL_KEYS[path.name]
            for key in sorted(unexpected):
                violations.append(
                    {"file": rel_text, "label": "evidence_unexpected_json_field", "where": f"$[{payload_index}].{key}"}
                )
        if path.name in CODEX_SMOKE_JSONL_ROW_KEYS and isinstance(payload, dict):
            unexpected = set(payload) - CODEX_SMOKE_JSONL_ROW_KEYS[path.name]
            for key in sorted(unexpected):
                violations.append(
                    {"file": rel_text, "label": "evidence_unexpected_json_field", "where": f"$[{payload_index}].{key}"}
                )
        if path.name == "source.sanitized.json" and isinstance(payload, dict):
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
        if path.name == "claim-readiness.sanitized.json" and isinstance(payload, dict):
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
            if is_target_label and value not in ALLOWED_TARGET_LABELS:
                violations.append({"file": rel_text, "label": "evidence_unapproved_target_label", "where": json_path})
            if "observed_task_tools" in json_path and lower not in ALLOWED_OBSERVED_TOOLS:
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
