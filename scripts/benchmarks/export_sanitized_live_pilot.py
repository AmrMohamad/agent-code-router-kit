from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file, utc_now


TOP_LEVEL_FILES = (
    "correctness-summary.json",
    "matrix-completion-summary.json",
    "metrics-summary.json",
    "policy-violations.json",
    "proof-layer-summary.json",
    "route-claim-readiness.json",
    "route-comparisons.json",
    "route-isolation-summary.json",
    "route-policy-summary.json",
    "terminal-control-summary.json",
    "token-savings-report.md",
)
RUN_ARTIFACTS = (
    "judge.json",
    "launch-plan.json",
    "metrics.normalized.json",
    "route-isolation.json",
    "serena-readiness.json",
    "telemetry.jsonl",
)
RUN_FIELDS = (
    "run_id",
    "repeat_index",
    "agent",
    "profile",
    "task_id",
    "task_family",
    "repo",
    "completion_reason",
    "failure_reason",
    "wall_seconds",
    "correctness_status",
    "policy_adherence",
    "policy_violations",
    "expected_success_signal_seen",
    "expected_proof_layer_seen",
    "token_source",
    "exact_input_tokens",
    "exact_output_tokens",
    "exact_total_tokens",
    "exact_cached_input_tokens",
    "exact_uncached_total_tokens",
    "exact_reasoning_output_tokens",
    "exact_usage_event_count",
    "agent_reported_total_tokens",
    "model_visible_proxy_tokens",
    "tool_output_bytes",
    "tool_evidence_source",
    "observed_task_tools",
    "route_isolation_mode",
    "route_hard_controls",
    "route_weak_controls",
    "dynamic_target_symbol",
    "dynamic_target_language",
    "dynamic_target_declaration_kind",
    "serena_readiness_status",
    "serena_readiness_ready",
    "serena_readiness_reason",
    "serena_readiness_warnings",
)


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def path_alias_map(manifest: dict[str, object]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key in ("repo_map", "repo_states", "source_repo_states"):
        value = manifest.get(key)
        if isinstance(value, dict):
            for repo_id, item in value.items():
                alias = str(repo_id or "default")
                if isinstance(item, str):
                    aliases[str(Path(item).expanduser())] = f"<repo:{alias}>"
                    aliases[str(Path(item).expanduser().resolve())] = f"<repo:{alias}>"
                elif isinstance(item, dict):
                    for path_key in ("path", "git_root"):
                        path_value = item.get(path_key)
                        if isinstance(path_value, str) and path_value:
                            aliases[path_value] = f"<repo:{alias}>"
                            aliases[str(Path(path_value).expanduser())] = f"<repo:{alias}>"
    return aliases


def sanitize_text(value: str, aliases: dict[str, str]) -> str:
    sanitized = value
    for source, alias in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        sanitized = sanitized.replace(source, alias)
    return sanitized


def sanitize_value(value: object, aliases: dict[str, str]) -> object:
    if isinstance(value, str):
        return sanitize_text(value, aliases)
    if isinstance(value, list):
        return [sanitize_value(item, aliases) for item in value]
    if isinstance(value, dict):
        return {str(key): sanitize_value(item, aliases) for key, item in value.items()}
    return value


def sanitize_manifest(manifest: dict[str, object], aliases: dict[str, str]) -> dict[str, object]:
    keep = {
        key: manifest.get(key)
        for key in (
            "created_at",
            "agents",
            "arms",
            "task_ids",
            "task_count",
            "repeats",
            "dry_run",
            "live",
            "fresh_session_per_run",
            "order_randomized",
            "seed",
            "snapshot_repos",
            "serena_readiness_enabled",
            "serena_readiness_timeout_seconds",
            "require_clean_serena_process_state",
            "dynamic_code_prompts",
            "planned_new_runs",
            "carried_forward_runs",
        )
        if key in manifest
    }
    keep["repo_aliases"] = {
        str(repo_id or "default"): f"<repo:{repo_id or 'default'}>"
        for repo_id in (manifest.get("repo_map") or {})
    } if isinstance(manifest.get("repo_map"), dict) else {}
    keep["repo_states"] = sanitize_value(manifest.get("repo_states", {}), aliases)
    keep["source_repo_states"] = sanitize_value(manifest.get("source_repo_states", {}), aliases)
    return keep


def sanitize_run_row(row: dict[str, object], aliases: dict[str, str]) -> dict[str, object]:
    sanitized = {field: sanitize_value(row.get(field), aliases) for field in RUN_FIELDS if field in row}
    sanitized["run_dir"] = f"runs/{row.get('run_id', 'unknown')}"
    return sanitized


def sanitize_run_artifact(path: Path, aliases: dict[str, str]) -> str:
    return sanitize_text(path.read_text(encoding="utf-8"), aliases)


def export_sanitized_live_pilot(*, benchmark_out: str | Path, out: str | Path, title: str = "") -> dict[str, object]:
    source = Path(benchmark_out).expanduser().resolve()
    target = Path(out).expanduser().resolve()
    if not (source / "run-manifest.json").exists():
        raise SystemExit(f"run-manifest.json is missing under {source}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    manifest = load_json(source / "run-manifest.json")
    if not isinstance(manifest, dict):
        raise SystemExit("run-manifest.json must contain an object")
    aliases = path_alias_map(manifest)
    rows = load_jsonl(source / "runs.jsonl")
    sanitized_rows = [sanitize_run_row(row, aliases) for row in rows]
    to_json_file(target / "run-manifest.sanitized.json", sanitize_manifest(manifest, aliases))
    write_jsonl(target / "runs.sanitized.jsonl", sanitized_rows)

    copied_top_level: list[str] = []
    for name in TOP_LEVEL_FILES:
        src = source / name
        if not src.exists():
            continue
        dst = target / name
        if src.suffix == ".json":
            payload = load_json(src)
            to_json_file(dst, sanitize_value(payload, aliases))
        else:
            dst.write_text(sanitize_text(src.read_text(encoding="utf-8"), aliases), encoding="utf-8")
        copied_top_level.append(name)

    copied_run_artifacts: list[str] = []
    for row in rows:
        run_id = str(row.get("run_id") or "")
        run_dir_value = row.get("run_dir")
        if not run_id or not isinstance(run_dir_value, str):
            continue
        src_run_dir = Path(run_dir_value).expanduser()
        dst_run_dir = target / "runs" / run_id
        dst_run_dir.mkdir(parents=True, exist_ok=True)
        for name in RUN_ARTIFACTS:
            src = src_run_dir / name
            if not src.exists():
                continue
            (dst_run_dir / name).write_text(sanitize_run_artifact(src, aliases), encoding="utf-8")
            copied_run_artifacts.append(f"runs/{run_id}/{name}")

    summary = {
        "created_at": utc_now(),
        "title": title or "Sanitized RARB live pilot",
        "source": str(source),
        "out": str(target),
        "run_count": len(rows),
        "copied_top_level_files": copied_top_level,
        "copied_run_artifacts": copied_run_artifacts,
        "omitted_raw_artifacts": ["transcript.txt", "agent_final_answer.md", "visible-terminal-transcript.txt", "task-packet.md"],
        "status": "pass" if rows else "empty",
    }
    to_json_file(target / "export-summary.json", summary)
    (target / "README.md").write_text(
        "\n".join(
            [
                f"# {summary['title']}",
                "",
                "This directory is a sanitized RARB live-pilot export.",
                "Raw transcripts, task packets, and final-answer text are intentionally omitted.",
                "Local repository paths are replaced with `<repo:...>` aliases.",
                "",
                f"Runs: {len(rows)}",
                f"Created: {summary['created_at']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a sanitized RARB live-pilot artifact bundle.")
    parser.add_argument("--benchmark-out", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--title", default="")
    args = parser.parse_args(argv)
    summary = export_sanitized_live_pilot(benchmark_out=args.benchmark_out, out=args.out, title=args.title)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
