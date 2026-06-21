#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file
from scripts.lib.environment_capture import file_sha256


PUBLIC_ROW_FIELDS = [
    "run_id",
    "study_id",
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
    "task_id",
    "task_family",
    "repo",
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
    "exact_reasoning_output_tokens",
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
]


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def public_row(row: dict[str, object]) -> dict[str, object]:
    sanitized = {key: row.get(key) for key in PUBLIC_ROW_FIELDS if key in row}
    sanitized.pop("prompt", None)
    sanitized.pop("repo_path", None)
    sanitized.pop("run_dir", None)
    return sanitized


def build_public_bundle(*, root: Path, out: Path) -> dict[str, object]:
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "run-manifest.json").read_text(encoding="utf-8"))
    rows = load_jsonl(root / "runs.jsonl")
    public_manifest = {
        "study_id": manifest.get("study_id"),
        "order_design": manifest.get("order_design"),
        "parallelism": manifest.get("parallelism"),
        "snapshot_repos": manifest.get("snapshot_repos"),
        "isolated_agent_home": manifest.get("isolated_agent_home"),
        "isolated_serena_session": manifest.get("isolated_serena_session"),
        "model_id": manifest.get("model_id"),
        "reasoning_effort": manifest.get("reasoning_effort"),
        "tool_versions": manifest.get("tool_versions", {}),
        "privacy": {
            "private_paths_removed": True,
            "private_prompts_removed": True,
            "private_value_hmac_fields_only": True,
        },
    }
    to_json_file(out / "manifest.sanitized.json", public_manifest)
    with (out / "runs.sanitized.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(public_row(row), sort_keys=True) + "\n")
    readme = (
        "# Router Effect V1 Public Evidence\n\n"
        "This bundle contains sanitized study metadata and run rows. It intentionally "
        "omits private repository paths, prompts, source snippets, and concrete target symbols.\n"
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
    args = parser.parse_args(argv)
    result = build_public_bundle(root=Path(args.root).expanduser().resolve(), out=Path(args.out).expanduser().resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
