from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, replace
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.agents.generic_terminal_agent_bridge import TerminalAgentBridge
from scripts.benchmarks.build_real_agent_report import build_codex_tui_summary, write_report
from scripts.benchmarks.judge_agent_run import judge_file
from scripts.lib.agent_session import (
    RouteProfile,
    append_jsonl,
    load_agent_profile,
    load_route_profile,
    load_tasks,
    new_run_id,
    to_json_file,
    utc_now,
)
from scripts.lib.dynamic_task_prompts import materialize_task_for_symbol, select_code_symbol_target
from scripts.lib.environment_capture import capture_tool_versions, file_sha256, git_tree_hash, lockfile_hash, text_sha256
from scripts.lib.experiment_design import assign_sequence, load_study_plan, sequence_metadata
from scripts.lib.hermetic_agent_environment import materialize_hermetic_agent_environment
from scripts.lib.route_isolation import materialize_route_isolation
from scripts.lib.serena_readiness import run_serena_source_symbol_readiness, write_serena_readiness
from scripts.lib.task_oracles import load_task_oracles, verify_transcript_file
from scripts.lib.treatment_diff_artifacts import write_treatment_diff_artifact
from scripts.lib.treatment_config import FACTORIAL_ARM_ORDER, factors_for_profile, hmac_sha256_hex, validate_factorial_arm_set


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASKS = ROOT / "benchmarks" / "real-agent-routing" / "tasks" / "android-realworld.example.tsv"
DEFAULT_OUT = ROOT / "results" / "real-agent-routing"
SERENA_PROCESS_STATE_WARNING_CODES = {
    "multiple_serena_mcp_processes",
    "multiple_kotlin_lsp_processes",
    "multiple_json_lsp_processes",
}
HIGH_FANOUT_RAW_OUTPUT_CEILING_BYTES = 50000
DEFAULT_STUDY_MODEL_ID = "not_pinned"
DEFAULT_REASONING_EFFORT = "default"


def apply_study_controls(args: argparse.Namespace, *, study_plan) -> None:
    if not study_plan:
        return
    args.order_design = study_plan.order_design
    args.isolated_agent_home = True
    args.isolated_serena_session = True
    args.prewarm_semantic_layer = study_plan.require_prewarm_semantic_layer
    args.capture_versions = True
    args.require_snapshots = study_plan.require_clean_snapshots
    args.parallelism = study_plan.parallelism
    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    validate_factorial_arm_set(arms)
    if args.repeats < study_plan.minimum_repeats:
        raise SystemExit(f"study plan requires --repeats >= {study_plan.minimum_repeats}")
    if study_plan.parallelism != 1 or args.parallelism != 1:
        raise SystemExit("study plan requires --parallelism 1")
    if study_plan.require_clean_snapshots and not args.snapshot_repos:
        raise SystemExit("study plan requires --snapshot-repos")
    if study_plan.require_prewarm_semantic_layer and args.skip_serena_readiness:
        raise SystemExit("study plan requires semantic readiness prewarm; remove --skip-serena-readiness")
    if args.allow_dirty:
        raise SystemExit("study plan does not allow --allow-dirty")
    if study_plan.require_external_oracles and not args.task_oracles:
        args.task_oracles = study_plan.task_oracles_path
    if not args.dry_run and args.model_id == DEFAULT_STUDY_MODEL_ID:
        raise SystemExit("live study mode requires --model-id with the exact pinned model identifier")
    if not os.environ.get(args.hmac_key_env, ""):
        raise SystemExit(f"study mode requires ${args.hmac_key_env} for private HMAC fingerprints")


def exact_uncached_input_tokens(metrics: dict[str, object]) -> int | None:
    input_tokens = metrics.get("exact_input_tokens")
    cached_tokens = metrics.get("exact_cached_input_tokens")
    if isinstance(input_tokens, int) and isinstance(cached_tokens, int):
        return max(0, input_tokens - cached_tokens)
    return None


def private_hmac(value: str, *, key_env: str) -> str:
    key = str(os.environ.get(key_env, ""))
    if not key:
        return ""
    return hmac_sha256_hex(value, key=key)


def file_hmac(path: str | Path, *, key_env: str) -> str:
    source = Path(path)
    if not source.exists():
        return ""
    return private_hmac(source.read_text(encoding="utf-8"), key_env=key_env)


def study_task_split(*, tasks_path: str | Path, study_plan) -> str:
    if not study_plan:
        return ""
    task_manifest = Path(tasks_path).expanduser().resolve()
    study_dir = Path(study_plan.protocol_path).resolve().parent
    split_paths = {
        "pilot": study_dir / "pilot-tasks.tsv",
        "confirmatory": study_dir / "confirmatory-tasks.tsv",
    }
    for split, split_path in split_paths.items():
        if task_manifest == split_path.resolve():
            return split
    return "custom"


def build_study_package_metadata(args: argparse.Namespace, *, study_plan) -> dict[str, object]:
    if not study_plan:
        return {}
    study_plan_path = Path(args.study_plan).expanduser().resolve()
    task_oracles_path = Path(args.task_oracles).expanduser().resolve() if args.task_oracles else Path(study_plan.task_oracles_path).resolve()
    task_manifest_path = Path(args.tasks).expanduser().resolve()
    plan_task_oracles_path = Path(study_plan.task_oracles_path).resolve()
    paths = {
        "study_plan": study_plan_path,
        "protocol": Path(study_plan.protocol_path).resolve(),
        "analysis_plan": Path(study_plan.analysis_plan_path).resolve(),
        "task_oracles": task_oracles_path,
        "task_manifest": task_manifest_path,
    }
    metadata: dict[str, object] = {
        "hash_algorithm": "sha256",
        "private_fingerprint_algorithm": "hmac-sha256",
        "task_split": study_task_split(tasks_path=task_manifest_path, study_plan=study_plan),
        "task_oracles_source": "study_plan" if task_oracles_path == plan_task_oracles_path else "custom",
    }
    for name, path in paths.items():
        metadata[f"{name}_path"] = str(path)
        metadata[f"{name}_sha256"] = file_sha256(path) if path.exists() else ""
        metadata[f"{name}_hmac"] = file_hmac(path, key_env=args.hmac_key_env)
    return metadata


def semantic_session_artifact(
    *,
    run_id: str,
    profile_id: str,
    semantic_access_enabled: bool,
    isolated_serena_session: bool,
    hermetic_environment,
    serena_readiness: dict[str, object] | None,
    tool_versions: dict[str, str],
    project_path_hmac: str,
) -> dict[str, object]:
    language_versions = {
        "sourcekit-lsp": tool_versions.get("sourcekit-lsp", ""),
        "kotlin-language-server": tool_versions.get("kotlin-language-server", ""),
        "vscode-json-languageserver": tool_versions.get("vscode-json-languageserver", ""),
    }
    if not semantic_access_enabled:
        return {
            "session_id": "",
            "profile": profile_id,
            "semantic_access_enabled": False,
            "mode": "disabled",
            "isolated": True,
            "mcp_server_configured": False,
            "transport": "",
            "semantic_session_home": "",
            "serena_home": "",
            "xdg_config_home": "",
            "xdg_cache_home": "",
            "xdg_data_home": "",
            "project_path_hmac": "",
            "readiness_status": "",
            "readiness_ready": None,
            "language_server_versions": language_versions,
            "teardown_policy": "no semantic MCP server configured for this arm",
        }
    semantic_home = Path(hermetic_environment.semantic_session_home) if hermetic_environment else None
    serena_home = semantic_home / "home" if semantic_home else None
    xdg_config_home = semantic_home / "xdg-config" if semantic_home else None
    xdg_cache_home = semantic_home / "xdg-cache" if semantic_home else None
    xdg_data_home = semantic_home / "xdg-data" if semantic_home else None
    return {
        "session_id": run_id,
        "profile": profile_id,
        "semantic_access_enabled": True,
        "mode": "codex_mcp_stdio_per_run",
        "isolated": bool(isolated_serena_session and hermetic_environment),
        "mcp_server_configured": True,
        "transport": "stdio",
        "semantic_session_home": hermetic_environment.semantic_session_home if hermetic_environment else "",
        "serena_home": str(serena_home) if serena_home else "",
        "xdg_config_home": str(xdg_config_home) if xdg_config_home else "",
        "xdg_cache_home": str(xdg_cache_home) if xdg_cache_home else "",
        "xdg_data_home": str(xdg_data_home) if xdg_data_home else "",
        "mcp_env_keys": ["RARB_SERENA_SESSION_HOME", "SERENA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"],
        "project_path_hmac": project_path_hmac,
        "requires_unique_port": False,
        "readiness_status": serena_readiness.get("status") if serena_readiness else "",
        "readiness_ready": serena_readiness.get("ready") if serena_readiness else None,
        "language_server_versions": language_versions,
        "teardown_policy": "Codex subprocess owns the stdio MCP server; session exit closes the per-run Serena process",
    }


def profile_path(profile_id: str) -> Path:
    return ROOT / "benchmarks" / "real-agent-routing" / "profiles" / f"{profile_id}.yaml"


def agent_path(agent_id: str) -> Path:
    filenames = {
        "codex": "codex.yaml",
        "claude-code": "claude-code.yaml",
        "cursor": "cursor-agent.yaml",
        "cursor-agent": "cursor-agent.yaml",
    }
    return ROOT / "benchmarks" / "real-agent-routing" / "agents" / filenames.get(agent_id, f"{agent_id}.yaml")


def effective_route_profile(profile: RouteProfile, *, task) -> RouteProfile:
    if (
        task.task_family.startswith("high_fanout")
        and profile.max_raw_output_bytes > HIGH_FANOUT_RAW_OUTPUT_CEILING_BYTES
    ):
        return replace(profile, max_raw_output_bytes=HIGH_FANOUT_RAW_OUTPUT_CEILING_BYTES)
    return profile


def high_fanout_requires_summary_first(profile: RouteProfile) -> bool:
    return "summary_first" in profile.high_fanout_policy


def raw_output_discipline(*, task, profile: RouteProfile) -> str:
    if not task.task_family.startswith("high_fanout"):
        return """- Treat the maximum raw output bytes as a hard budget for terminal/tool output,
  not just for the final answer.
- Prefer `rg -l`, `rg --count`, `wc -l`, `head`, `sed -n`, `awk` grouping, or
  module/file counts before opening files."""

    if high_fanout_requires_summary_first(profile):
        return """- Treat the maximum raw output bytes as a hard budget for terminal/tool output,
  not just for the final answer.
- Prefer `rg -l`, `rg --count`, `wc -l`, `head`, `sed -n`, `awk` grouping, or
  module/file counts before opening files.
- For high-fanout terms, do not run commands that print every match. Summarize
  first, then inspect only the narrow files needed for the answer."""

    return """- Treat the maximum raw output bytes as a hard budget for terminal/tool output,
  not just for the final answer.
- This route is a controlled high-fanout baseline. Raw search or semantic output
  is allowed up to the profile budget when the profile permits that tool path.
- Do not try to bypass or raise the budget. If the run hits the output budget,
  stop and report that controlled failure as benchmark data.
- Keep the final answer compact and label the evidence according to the route
  profile."""


def budget_safe_guidance(*, task, profile) -> str:
    if task.task_family == "known_kotlin_symbol_definition":
        return """- Start with one narrow symbol lookup. If semantic tools are available for this
  route, use that first with a small answer limit.
- If using shell search, prefer:
  `rg -l '\\b<SymbolName>\\b' --glob '*.kt' | sed -n '1,20p'`
  then inspect only the most likely declaration file with a short `sed -n`
  range.
- Do not print every usage/reference of the symbol. This task asks for the
  definition path and evidence layer only."""
    if task.task_family.startswith("high_fanout"):
        if not high_fanout_requires_summary_first(profile):
            return """- A summary-first command is not required in this arm. Use the natural route
  allowed by the profile while staying under Maximum raw output bytes.
- A-search-only remains search/basic-read only. C-lsp-naive may use semantic
  tools, but the benchmark should still observe whether this naive route floods
  context.
- If the output budget is exceeded, do not retry with a larger dump. Report the
  budget hit as the run outcome."""
        return """- Never print every match for the high-fanout term.
- Do not open or read any source file before the first grouped count/search
  summary. A file read before grouped evidence is a benchmark failure.
- First produce grouped counts only, for example:
  `rg -l '\\bUseCase\\b|UseCase' --glob '*.kt' | awk -F/ '{count[$1]++} END {for (k in count) print count[k], k}' | sort -nr | sed -n '1,15p'`
- If using Cursor grep, use `outputMode: count` or a narrow path-restricted
  search. Do not page through `files_with_matches` offsets for `UseCase`.
- Open at most 2-3 representative files after the grouped count, and only with
  short line ranges.
- The final answer should report top groups and evidence boundaries, not raw
  match lists."""
    return "- Keep command output short and inspect only the minimum files needed."


def serena_preflight_section(readiness: dict[str, object] | None) -> str:
    if not readiness:
        return ""
    process_state = readiness.get("process_state") if isinstance(readiness.get("process_state"), dict) else {}
    warnings = readiness.get("warnings") if isinstance(readiness.get("warnings"), list) else []
    warning_text = ", ".join(str(item) for item in warnings) if warnings else "none"
    return f"""
## Serena Semantic Preflight

Status: {readiness.get("status")}
Ready: {str(bool(readiness.get("ready"))).lower()}
Symbol: {readiness.get("symbol") or ""}
Source file: {readiness.get("source_file") or ""}
Reason: {readiness.get("reason") or ""}
Next action: {readiness.get("next_action") or ""}
Process state: serena_mcp={process_state.get("serena_mcp", "unknown")}, kotlin_lsp={process_state.get("kotlin_lsp", "unknown")}, json_lsp={process_state.get("json_lsp", "unknown")}
Warnings: {warning_text}

Serena coordination rules:
- If Ready is true, prefer Serena for semantic identity and keep source reads
  narrow. If the MCP reports that the language-server manager is not initialized,
  treat the semantic layer as temporarily unavailable and report that honestly.
- If Ready is false, do not claim semantic proof from Serena. Report blocked or
  partial according to the response contract, and include the reason above.
- Multiple Serena/Kotlin LSP processes are a stale-session risk. Mention them as
  route-readiness risk instead of hiding them.
"""


def route_uses_serena(profile: RouteProfile) -> bool:
    semantic_terms = ("serena", "kotlin lsp", "java lsp", "semantic")
    allowed_or_required = " ".join(
        [
            profile.required_first_tool,
            *profile.allowed_tools,
        ]
    ).lower()
    if any(term in allowed_or_required for term in semantic_terms):
        return True
    blocked = " ".join(profile.blocked_tools).lower()
    instructions = profile.instructions.lower()
    return not any(term in blocked for term in semantic_terms) and any(term in instructions for term in semantic_terms)


def task_needs_serena_source_readiness(task) -> bool:
    haystack = " ".join(
        [
            task.task_family,
            task.prompt,
            task.expected_proof_layer,
        ]
    ).lower()
    if "kotlin" not in haystack and "java" not in haystack:
        return False
    return any(
        term in haystack
        for term in (
            "known_kotlin_symbol",
            "known_java_symbol",
            "semantic_identity",
            "reference_proof",
            "semantic_disagreement",
        )
    )


def serena_process_state_warnings(readiness: dict[str, object] | None) -> list[str]:
    if not readiness:
        return []
    warnings = readiness.get("warnings")
    if not isinstance(warnings, list):
        return []
    return [str(warning) for warning in warnings if str(warning) in SERENA_PROCESS_STATE_WARNING_CODES]


def enforce_clean_serena_process_state(*, readiness: dict[str, object] | None, run_dir: Path) -> None:
    warnings = serena_process_state_warnings(readiness)
    if not warnings:
        return
    raise SystemExit(
        "Serena process state is not clean for a live semantic-router cell; "
        f"warnings={','.join(warnings)}. "
        f"Inspect {run_dir / 'serena-readiness.json'} and clean stale Serena/Kotlin LSP sessions before rerunning."
    )


def task_supports_dynamic_code_prompt(task) -> bool:
    return task_needs_serena_source_readiness(task)


def dynamic_prompt_rng(*, seed: int, repeat_index: int, agent_id: str, task_id: str, repo: str) -> random.Random:
    return random.Random(f"{seed}:{repeat_index}:{agent_id}:{task_id}:{repo}")


def render_task_packet(*, run_id: str, agent: str, repo: str, task, profile, sentinel: str, serena_readiness: dict[str, object] | None = None) -> str:
    return f"""# RARB Task Packet v1

Run ID: {run_id}
Agent: {agent}
Route Profile: {profile.profile_id}
Repo: {repo}
Task ID: {task.task_id}
Task Family: {task.task_family}
Time Budget Seconds: {task.timeout_seconds}
Edit Allowed: {str(task.edit_allowed).lower()}
Build Allowed: {str(task.build_allowed).lower()}
Completion Sentinel: {sentinel}

## Objective

{task.prompt}

## Routing Constraints

{profile.instructions}

Allowed tools:
{chr(10).join(f"- {tool}" for tool in profile.allowed_tools)}

Blocked tools:
{chr(10).join(f"- {tool}" for tool in profile.blocked_tools) if profile.blocked_tools else "- none"}

High-fanout policy: {profile.high_fanout_policy}
Maximum raw output bytes: {profile.max_raw_output_bytes}

Raw-output discipline:
{raw_output_discipline(task=task, profile=profile)}

Budget-safe command guidance:
{budget_safe_guidance(task=task, profile=profile)}
{serena_preflight_section(serena_readiness)}

## Expected Proof

{task.expected_proof_layer}

## Forbidden Claims

{task.forbidden_claims}

## Response Contract

Return this exact contract shape as plain text. Do not wrap it in Markdown
fences. `status` must be one of pass, partial, fail, or blocked.

BENCHMARK_RESULT
status: pass|partial|fail|blocked
confidence: high|medium|low

tools_used:
  - tool names actually used

proof_layers:
  semantic_identity: evidence or not used
  references: evidence or not used
  runtime: evidence or not run

files_opened:
  count: number
  paths:
  - relative/path

raw_dump_incidents:
  count: number

tool_outputs:
  compact summary bullets only; do not paste raw high-fanout output or long
  command excerpts. If you used grouped counts, summaries, or short facts
  instead of raw dumps, set raw_dump_incidents count to 0.

policy_adherence: pass|warn|fail

final_answer:
  concise answer and evidence

End with:

{sentinel}
"""


def select_tasks(tasks, *, arms: list[str], task_limit: int | None):
    selected = [task for task in tasks if set(arms).intersection(task.route_profiles)]
    return selected[:task_limit] if task_limit else selected


def resolve_output_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def clean_output_dir(out_root: Path) -> None:
    repo_results = DEFAULT_OUT.resolve()
    temp_roots = {Path("/tmp").resolve(), Path("/private/tmp").resolve(), Path(tempfile.gettempdir()).resolve()}
    allowed = repo_results == out_root or repo_results in out_root.parents
    allowed = allowed or any(temp_root in out_root.parents for temp_root in temp_roots)
    if not allowed:
        raise SystemExit(
            "--clean-out is only allowed under results/real-agent-routing or a temporary directory"
        )
    if out_root.exists():
        shutil.rmtree(out_root)


def git_metadata(repo: str | Path) -> dict[str, object]:
    repo_path = Path(repo).resolve()

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return completed.stdout.strip() if completed.returncode == 0 else ""

    status = git("status", "--porcelain")
    return {
        "path": str(repo_path),
        "git_root": git("rev-parse", "--show-toplevel"),
        "branch": git("branch", "--show-current") or git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": git("rev-parse", "HEAD"),
        "tree_hash": git("rev-parse", "HEAD^{tree}"),
        "lockfile_hash": lockfile_hash(repo_path),
        "dirty": bool(status),
        "dirty_entries": len([line for line in status.splitlines() if line.strip()]),
        "status_sha256": text_sha256(status),
    }


def _git(repo: str | Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=Path(repo).resolve(),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {completed.stderr.strip()}")
    return completed


def _safe_repo_id(repo_id: str) -> str:
    value = repo_id or "default"
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]


def snapshot_repo_map(repo_map: dict[str, str], *, out_root: Path) -> tuple[dict[str, str], dict[str, dict[str, object]]]:
    snapshot_root = out_root / "_repo-snapshots"
    if snapshot_root.exists():
        shutil.rmtree(snapshot_root)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    source_cache: dict[tuple[str, str], Path] = {}
    snapshots: dict[str, dict[str, object]] = {}
    mapped: dict[str, str] = {}
    for repo_id, repo_path_value in repo_map.items():
        repo_path = Path(repo_path_value).expanduser().resolve()
        git_root_text = _git(repo_path, "rev-parse", "--show-toplevel", check=True).stdout.strip()
        commit = _git(repo_path, "rev-parse", "HEAD", check=True).stdout.strip()
        git_root = Path(git_root_text).resolve()
        try:
            relative = repo_path.relative_to(git_root)
        except ValueError:
            relative = Path()
        cache_key = (str(git_root), commit)
        if cache_key not in source_cache:
            snapshot_path = snapshot_root / _safe_repo_id(repo_id)
            suffix = 1
            while snapshot_path.exists():
                suffix += 1
                snapshot_path = snapshot_root / f"{_safe_repo_id(repo_id)}-{suffix}"
            _git(git_root, "worktree", "add", "--detach", str(snapshot_path), commit, check=True)
            source_cache[cache_key] = snapshot_path.resolve()
        snapshot_base = source_cache[cache_key]
        effective_path = (snapshot_base / relative).resolve()
        mapped[repo_id] = str(effective_path)
        snapshots[repo_id or "default"] = {
            "source_path": str(repo_path),
            "source_git_root": str(git_root),
            "source_commit": commit,
            "source_tree_hash": _git(git_root, "rev-parse", f"{commit}^{{tree}}", check=True).stdout.strip(),
            "snapshot_path": str(effective_path),
            "snapshot_git_root": str(snapshot_base),
        }
    return mapped, snapshots


def parse_repo_map(value: str | None, *, default_repo: str | Path) -> dict[str, str]:
    mapping: dict[str, str] = {"": str(Path(default_repo).resolve())}
    if not value:
        return mapping
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise SystemExit(f"--repo-map item must be repo_id=/path: {item}")
        repo_id, path = item.split("=", 1)
        if not repo_id.strip() or not path.strip():
            raise SystemExit(f"--repo-map item must be repo_id=/path: {item}")
        mapping[repo_id.strip()] = str(Path(path).expanduser().resolve())
    return mapping


def restrict_repo_map_to_tasks(repo_map: dict[str, str], tasks: list[object]) -> dict[str, str]:
    needed = {str(getattr(task, "repo", "") or "") for task in tasks}
    restricted: dict[str, str] = {}
    for repo_id in needed:
        if repo_id in repo_map:
            restricted[repo_id] = repo_map[repo_id]
    needs_default_fallback = "" in needed or any(repo_id and repo_id not in repo_map for repo_id in needed)
    if needs_default_fallback and "" in repo_map:
        restricted[""] = repo_map[""]
    return restricted


def repo_for_task(repo_map: dict[str, str], task_repo: str) -> str:
    return repo_map.get(task_repo) or repo_map[""]


def missing_live_repo_mappings(tasks: list[TaskSpec], repo_map: dict[str, str]) -> list[str]:
    return sorted({task.repo for task in tasks if task.repo and task.repo not in repo_map})


def monitor_event(path: Path, event: dict[str, object], *, enabled: bool) -> None:
    append_jsonl(path, event)
    if enabled:
        if event["event"] == "run_started":
            print(f"• Running {event['profile']} / {event['task_id']} [{event['run_id']}]", flush=True)
        elif event["event"] == "run_completed":
            print(
                f"  └ {event['correctness_status']} policy={event['policy_adherence']} "
                f"tokens={event['model_visible_proxy_tokens']} raw_dumps={event['raw_dump_incidents']}",
                flush=True,
            )


def load_existing_run_rows(path: str | Path) -> list[dict[str, object]]:
    runs_path = Path(path)
    if runs_path.is_dir():
        runs_path = runs_path / "runs.jsonl"
    if not runs_path.exists():
        raise SystemExit(f"--resume-from has no runs.jsonl: {runs_path}")
    rows: list[dict[str, object]] = []
    with runs_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def load_run_rows(path: str | Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def filter_valid_carried_rows(rows: list[dict[str, object]], *, resume_root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    manifest_path = resume_root / "run-manifest.json"
    if not manifest_path.exists():
        return rows, []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repo_map = manifest.get("repo_map")
    mapped = set(repo_map) if isinstance(repo_map, dict) else set()
    valid: list[dict[str, object]] = []
    invalid: list[dict[str, object]] = []
    for row in rows:
        repo_id = str(row.get("repo", ""))
        if repo_id and repo_id not in mapped:
            invalid.append(row)
        else:
            valid.append(row)
    return valid, invalid


def filter_rerunnable_rows(rows: list[dict[str, object]], *, rerun_failed: bool) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if not rerun_failed:
        return rows, []
    valid: list[dict[str, object]] = []
    rerun: list[dict[str, object]] = []
    for row in rows:
        if row.get("correctness_status") != "pass" or row.get("policy_violations"):
            rerun.append(row)
        else:
            valid.append(row)
    return valid, rerun


def split_importable_carried_rows(rows: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    importable: list[dict[str, object]] = []
    missing_artifacts: list[dict[str, object]] = []
    required_files = {
        "task-packet.md",
        "transcript.txt",
        "telemetry.jsonl",
        "metrics.normalized.json",
        "judge.json",
        "route-isolation.json",
    }
    for row in rows:
        run_dir = Path(str(row.get("run_dir", ""))).expanduser()
        if not run_dir.exists() or not run_dir.is_dir():
            missing_artifacts.append(row)
            continue
        missing = [name for name in required_files if not (run_dir / name).exists()]
        if missing:
            missing_row = dict(row)
            missing_row["missing_artifact_files"] = missing
            missing_artifacts.append(missing_row)
            continue
        importable.append(row)
    return importable, missing_artifacts


def import_carried_row_artifacts(
    row: dict[str, object],
    *,
    out_root: Path,
    repo_map: dict[str, str],
) -> dict[str, object]:
    source_run_dir = Path(str(row.get("run_dir", ""))).expanduser().resolve()
    run_id = str(row.get("run_id", source_run_dir.name))
    target_run_dir = out_root / run_id
    if target_run_dir.exists():
        suffix = 1
        while True:
            candidate = out_root / f"{run_id}-carried-{suffix}"
            if not candidate.exists():
                target_run_dir = candidate
                break
            suffix += 1
    shutil.copytree(source_run_dir, target_run_dir)
    imported = dict(row)
    imported["run_dir"] = str(target_run_dir)
    imported["repo_path"] = repo_for_task(repo_map, str(imported.get("repo", "")))
    imported["carried_forward_from_run_dir"] = str(source_run_dir)
    imported["carried_forward_artifacts_imported"] = True
    return imported


def run_cell_key(row: dict[str, object]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("agent", "")),
        str(row.get("profile", "")),
        str(row.get("task_id", "")),
        str(row.get("repo", "")),
        str(row.get("repeat_index", "")),
    )


def run_benchmark(args: argparse.Namespace) -> dict[str, object]:
    if args.seed is None:
        args.seed = random.SystemRandom().randrange(1, 2**32)
    study_plan = load_study_plan(args.study_plan) if args.study_plan else None
    apply_study_controls(args, study_plan=study_plan)
    out_root = resolve_output_path(args.out)
    resume_root = resolve_output_path(args.resume_from) if args.resume_from else None
    if resume_root and resume_root == out_root:
        raise SystemExit("--resume-from must point at a different directory than --out")
    out_root.mkdir(parents=True, exist_ok=True)
    runs_path = out_root / "runs.jsonl"
    if runs_path.exists():
        runs_path.unlink()
    monitor_path = out_root / "monitor.jsonl"
    if monitor_path.exists():
        monitor_path.unlink()
    agent_ids = [item.strip() for item in (args.agents or args.agent).split(",") if item.strip()]
    agent_profiles = {agent_id: load_agent_profile(agent_path(agent_id)) for agent_id in agent_ids}
    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    if args.order_design == "balanced-latin-square":
        validate_factorial_arm_set(arms)
    tasks = select_tasks(load_tasks(args.tasks), arms=arms, task_limit=args.task_limit)
    task_oracles = load_task_oracles(args.task_oracles)
    repo_map = parse_repo_map(args.repo_map, default_repo=args.repo)
    if args.require_snapshots:
        repo_map = restrict_repo_map_to_tasks(repo_map, tasks)
    if not args.dry_run:
        missing_repos = missing_live_repo_mappings(tasks, repo_map)
        if missing_repos:
            raise SystemExit(
                "live runs require explicit --repo-map entries for named task repos: "
                + ",".join(missing_repos)
            )
        for agent_profile in agent_profiles.values():
            if not agent_profile.supports_live:
                raise SystemExit(f"agent {agent_profile.agent_id} does not support live execution yet")
            candidates = [agent_profile.command, *agent_profile.fallback_commands]
            if not any(shutil.which(candidate) for candidate in candidates):
                raise SystemExit(
                    f"agent {agent_profile.agent_id} has no installed command candidate: {', '.join(candidates)}"
                )
    source_repo_states = {repo_id or "default": git_metadata(path) for repo_id, path in repo_map.items()}
    if args.require_snapshots:
        dirty_sources = [repo_id for repo_id, state in source_repo_states.items() if state["dirty"]]
        if dirty_sources:
            raise SystemExit(
                "study/snapshot runs require clean source repositories before snapshotting; dirty repos: "
                + ",".join(dirty_sources)
            )
    repo_snapshots: dict[str, dict[str, object]] = {}
    if args.snapshot_repos:
        repo_map, repo_snapshots = snapshot_repo_map(repo_map, out_root=out_root)
        for repo_id, snapshot in repo_snapshots.items():
            snapshot_path = str(snapshot.get("snapshot_path", ""))
            if snapshot_path:
                snapshot_state = git_metadata(snapshot_path)
                snapshot["snapshot_commit"] = snapshot_state.get("commit", "")
                snapshot["snapshot_dirty"] = snapshot_state.get("dirty", True)
                snapshot["snapshot_tree_hash"] = git_tree_hash(snapshot_path)
                snapshot["lockfile_hash"] = lockfile_hash(snapshot_path)
    repo_states = {repo_id or "default": git_metadata(path) for repo_id, path in repo_map.items()}
    if not args.dry_run and not args.allow_dirty:
        dirty_repos = [repo_id for repo_id, state in repo_states.items() if state["dirty"]]
        if dirty_repos:
            raise SystemExit(
                "live runs require clean git worktrees; dirty repos: "
                + ",".join(dirty_repos)
                + " (rerun with --allow-dirty to override)"
            )
    route_profiles = {arm: load_route_profile(profile_path(arm)) for arm in arms}
    tool_versions = capture_tool_versions(cwd=ROOT) if args.capture_versions else {}
    carried_rows = load_existing_run_rows(resume_root) if resume_root else []
    invalid_carried_rows: list[dict[str, object]] = []
    if resume_root:
        carried_rows, invalid_carried_rows = filter_valid_carried_rows(carried_rows, resume_root=resume_root)
    rerun_carried_rows: list[dict[str, object]] = []
    carried_rows, rerun_carried_rows = filter_rerunnable_rows(carried_rows, rerun_failed=args.rerun_failed)
    missing_artifact_carried_rows: list[dict[str, object]] = []
    carried_rows, missing_artifact_carried_rows = split_importable_carried_rows(carried_rows)
    existing_cells = {run_cell_key(row) for row in carried_rows}
    task_manifest_path = Path(args.tasks).expanduser().resolve()
    task_manifest_hash = file_sha256(task_manifest_path)
    study_package = build_study_package_metadata(args, study_plan=study_plan)
    manifest = {
        "created_at": utc_now(),
        "study_plan": str(Path(args.study_plan).expanduser().resolve()) if args.study_plan else "",
        "study_id": study_plan.study_id if study_plan else "",
        "study_design_type": study_plan.design_type if study_plan else "",
        "study_package": study_package,
        "order_design": args.order_design,
        "parallelism": args.parallelism,
        "isolated_agent_home": args.isolated_agent_home,
        "isolated_serena_session": args.isolated_serena_session,
        "prewarm_semantic_layer": args.prewarm_semantic_layer,
        "capture_versions": args.capture_versions,
        "require_snapshots": args.require_snapshots,
        "model_id": args.model_id,
        "reasoning_effort": args.reasoning_effort,
        "tool_versions": tool_versions,
        "task_oracles": str(Path(args.task_oracles).expanduser().resolve()) if args.task_oracles else "",
        "hmac_key_env": args.hmac_key_env,
        "private_hmac_configured": bool(os.environ.get(args.hmac_key_env, "")),
        "agent": args.agent if not args.agents else None,
        "agents": list(agent_profiles),
        "repo": str(Path(args.repo).resolve()),
        "repo_map": repo_map,
        "task_manifest": str(task_manifest_path),
        "task_manifest_hash": task_manifest_hash,
        "task_ids": [task.task_id for task in tasks],
        "source_repo_states": source_repo_states,
        "repo_snapshots": repo_snapshots,
        "repo_states": repo_states,
        "snapshot_repos": args.snapshot_repos,
        "dry_run": args.dry_run,
        "live": not args.dry_run,
        "arms": list(route_profiles),
        "task_count": len(tasks),
        "repeats": args.repeats,
        "fresh_session_per_run": True,
        "order_randomized": args.order_design == "random" and not args.no_randomize_order,
        "seed": args.seed,
        "resumed_from": str(resume_root) if resume_root else "",
        "carried_forward_runs": len(carried_rows),
        "invalid_carried_forward_runs": len(invalid_carried_rows),
        "invalid_carried_forward_cells": ["/".join(run_cell_key(row)) for row in invalid_carried_rows],
        "rerun_failed": args.rerun_failed,
        "rerun_carried_forward_runs": len(rerun_carried_rows),
        "rerun_carried_forward_cells": ["/".join(run_cell_key(row)) for row in rerun_carried_rows],
        "missing_artifact_carried_forward_runs": len(missing_artifact_carried_rows),
        "missing_artifact_carried_forward_cells": ["/".join(run_cell_key(row)) for row in missing_artifact_carried_rows],
        "serena_readiness_enabled": not args.skip_serena_readiness,
        "serena_readiness_timeout_seconds": args.serena_readiness_timeout,
        "require_clean_serena_process_state": args.require_clean_serena_process_state,
        "dynamic_code_prompts": not args.static_code_prompts,
    }
    if study_plan:
        for task in tasks:
            missing_profiles = [arm for arm in FACTORIAL_ARM_ORDER if arm not in task.route_profiles]
            if missing_profiles:
                raise SystemExit(
                    f"study task {task.task_id} does not include all A/B/C/D arms; missing={','.join(missing_profiles)}"
                )
    run_specs: list[dict[str, object]] = []
    skipped_existing_specs = 0
    for repeat_index in range(args.repeats):
        for agent_id, agent_profile in agent_profiles.items():
            for task in tasks:
                profile_order = list(route_profiles)
                sequence_meta_by_profile: dict[str, dict[str, object]] = {}
                if args.order_design == "balanced-latin-square":
                    profile_order = assign_sequence(task.task_id, repeat_index, arms=arms)
                    sequence_meta_by_profile = {
                        profile_id: sequence_metadata(profile_order, position=index, block_index=repeat_index)
                        for index, profile_id in enumerate(profile_order)
                    }
                for profile_id in profile_order:
                    profile = route_profiles[profile_id]
                    if profile_id not in task.route_profiles:
                        continue
                    cell = (agent_id, profile_id, task.task_id, task.repo, str(repeat_index))
                    if cell in existing_cells:
                        skipped_existing_specs += 1
                        continue
                    run_specs.append(
                        {
                            "repeat_index": repeat_index,
                            "agent_id": agent_id,
                            "agent_profile": agent_profile,
                            "task": task,
                            "profile_id": profile_id,
                            "profile": profile,
                            "sequence": sequence_meta_by_profile.get(
                                profile_id,
                                {
                                    "block_id": f"repeat-{repeat_index + 1:03d}",
                                    "sequence_id": "",
                                    "sequence_position": None,
                                    "previous_arm": "",
                                    "order_design": "random" if not args.no_randomize_order else "input",
                                },
                            ),
                        }
                    )
    manifest["existing_cells_available"] = len(existing_cells)
    manifest["skipped_existing_cells"] = skipped_existing_specs
    manifest["planned_new_runs"] = len(run_specs)
    to_json_file(out_root / "run-manifest.json", manifest)
    for row in carried_rows:
        append_jsonl(runs_path, import_carried_row_artifacts(row, out_root=out_root, repo_map=repo_map))
    if args.order_design == "random" and not args.no_randomize_order:
        random.Random(args.seed).shuffle(run_specs)
    for spec in run_specs:
        repeat_index = int(spec["repeat_index"])
        agent_id = str(spec["agent_id"])
        agent_profile = spec["agent_profile"]
        task = spec["task"]
        profile_id = str(spec["profile_id"])
        profile = spec["profile"]
        sequence = dict(spec["sequence"])
        run_id = new_run_id("rarb")
        run_dir = out_root / run_id
        sentinel = f"BENCHMARK_DONE_{run_id}"
        task_repo_path = repo_for_task(repo_map, task.repo)
        effective_profile = effective_route_profile(profile, task=task)
        terminal_mode = args.terminal_mode or agent_profile.terminal_mode
        run_dir.mkdir(parents=True, exist_ok=True)
        dynamic_target: dict[str, object] | None = None
        run_task = task
        if not args.static_code_prompts and task_supports_dynamic_code_prompt(task):
            target = select_code_symbol_target(
                task_repo_path,
                rng=dynamic_prompt_rng(
                    seed=args.seed,
                    repeat_index=repeat_index,
                    agent_id=agent_id,
                    task_id=task.task_id,
                    repo=task_repo_path,
                ),
            )
            if target:
                dynamic_target = target.to_dict()
                run_task = materialize_task_for_symbol(task, target)
                to_json_file(run_dir / "dynamic-task-target.json", dynamic_target)
        serena_readiness: dict[str, object] | None = None
        semantic_setup_seconds = 0.0
        if (
            not args.dry_run
            and not args.skip_serena_readiness
            and route_uses_serena(effective_profile)
            and (args.prewarm_semantic_layer or task_needs_serena_source_readiness(run_task))
        ):
            semantic_setup_started = time.monotonic()
            readiness = run_serena_source_symbol_readiness(
                repo=task_repo_path,
                prompt=run_task.prompt,
                source_symbol=str(dynamic_target["symbol"]) if dynamic_target else None,
                source_file=str(dynamic_target["source_file"]) if dynamic_target else None,
                timeout_seconds=args.serena_readiness_timeout,
            )
            semantic_setup_seconds = time.monotonic() - semantic_setup_started
            write_serena_readiness(run_dir / "serena-readiness.json", readiness)
            serena_readiness = asdict(readiness)
            if args.prewarm_semantic_layer and not readiness.ready:
                raise SystemExit(
                    "semantic readiness prewarm failed before live semantic-router run; "
                    f"inspect {run_dir / 'serena-readiness.json'}"
                )
            if args.require_clean_serena_process_state:
                enforce_clean_serena_process_state(readiness=serena_readiness, run_dir=run_dir)
        prompt = render_task_packet(
            run_id=run_id,
            agent=agent_profile.agent_id,
            repo=task_repo_path,
            task=run_task,
            profile=effective_profile,
            sentinel=sentinel,
            serena_readiness=serena_readiness,
        )
        (run_dir / "task-packet.md").write_text(prompt, encoding="utf-8")
        response_contract_path = ROOT / "benchmarks" / "real-agent-routing" / "contracts" / "response-contract.md"
        response_contract_hash = text_sha256(response_contract_path.read_text(encoding="utf-8"))
        hermetic_environment = None
        if args.isolated_agent_home:
            hermetic_environment = materialize_hermetic_agent_environment(
                agent_profile=agent_profile,
                route_profile=effective_profile,
                run_dir=run_dir,
                repo_path=task_repo_path,
                model_id=args.model_id,
                reasoning_effort=args.reasoning_effort,
                sandbox=args.sandbox,
                timeout_seconds=min(args.timeout, task.timeout_seconds),
                response_contract=response_contract_hash,
            )
        isolation = materialize_route_isolation(
            agent_profile=agent_profile,
            route_profile=effective_profile,
            run_dir=run_dir,
            workspace_cwd=task_repo_path,
            probe_cursor_mcp=not args.dry_run,
            terminal_mode=terminal_mode,
            hermetic_environment=hermetic_environment,
        )
        bridge = TerminalAgentBridge(
            agent_profile,
            cwd=task_repo_path,
            dry_run=args.dry_run,
            stream_agent_output=args.stream_agent_output,
            monitor_live_events=args.monitor,
            command=isolation.command,
            args=isolation.args,
            env=isolation.env,
            terminal_mode=terminal_mode,
        )
        to_json_file(run_dir / "launch-plan.json", asdict(bridge.launch_plan()))
        monitor_event(
            monitor_path,
            {
                "event": "run_started",
                "created_at": utc_now(),
                "run_id": run_id,
                "agent": agent_profile.agent_id,
                "profile": profile_id,
                "task_id": task.task_id,
                "task_family": task.task_family,
                "dynamic_target": dynamic_target,
                "repeat_index": repeat_index,
            },
            enabled=args.monitor,
        )
        bridge_result = bridge.run_prompt(
            run_id=run_id,
            prompt=prompt,
            out_dir=run_dir,
            timeout_seconds=min(args.timeout, task.timeout_seconds),
            sentinel=sentinel,
            profile_id=profile_id,
            task_id=task.task_id,
            max_output_bytes=effective_profile.max_raw_output_bytes,
        )
        metrics = json.loads((run_dir / "metrics.normalized.json").read_text(encoding="utf-8"))
        judge = judge_file(
            bridge_result.transcript_path,
            sentinel=sentinel,
            forbidden_claims=task.forbidden_claims,
            route_profile=effective_profile,
            task=run_task,
            metrics=metrics,
            dry_run=args.dry_run,
            out=run_dir / "judge.json",
        )
        repo_key = task.repo or "default"
        source_state = source_repo_states.get(repo_key, source_repo_states.get("default", {}))
        snapshot_state = repo_snapshots.get(repo_key, repo_snapshots.get("default", {}))
        row = {
            "run_id": run_id,
            "study_id": study_plan.study_id if study_plan else "",
            "protocol_commit": git_metadata(ROOT).get("commit", ""),
            "block_id": sequence.get("block_id", ""),
            "sequence_id": sequence.get("sequence_id", ""),
            "sequence_position": sequence.get("sequence_position"),
            "previous_arm": sequence.get("previous_arm", ""),
            "order_design": sequence.get("order_design", args.order_design),
            "repeat_index": repeat_index,
            "agent": agent_profile.agent_id,
            "profile": profile_id,
            "semantic_access_enabled": factors_for_profile(profile_id).semantic_access_enabled,
            "routing_discipline_enabled": factors_for_profile(profile_id).routing_discipline_enabled,
            "task_id": task.task_id,
            "task_family": task.task_family,
            "prompt": run_task.prompt,
            "task_prompt_sha256": text_sha256(run_task.prompt),
            "task_prompt_hmac": private_hmac(run_task.prompt, key_env=args.hmac_key_env),
            "expected_proof_layer": run_task.expected_proof_layer,
            "expected_success_signal": run_task.expected_success_signal,
            "dynamic_target_symbol": dynamic_target.get("symbol") if dynamic_target else "",
            "dynamic_target_symbol_hmac": private_hmac(str(dynamic_target.get("symbol")) if dynamic_target else "", key_env=args.hmac_key_env),
            "dynamic_target_source_file": dynamic_target.get("source_file") if dynamic_target else "",
            "dynamic_target_line": dynamic_target.get("line") if dynamic_target else None,
            "dynamic_target_language": dynamic_target.get("language") if dynamic_target else "",
            "dynamic_target_declaration_kind": dynamic_target.get("declaration_kind") if dynamic_target else "",
            "repo": task.repo,
            "repo_path": task_repo_path,
            "source_state_hmac": private_hmac(
                json.dumps(source_state, sort_keys=True),
                key_env=args.hmac_key_env,
            ),
            "snapshot_state_hmac": private_hmac(
                json.dumps(repo_states.get(repo_key, repo_states.get("default", {})), sort_keys=True),
                key_env=args.hmac_key_env,
            ),
            "source_commit": source_state.get("commit", ""),
            "snapshot_commit": snapshot_state.get("snapshot_commit", ""),
            "source_tree_hash": source_state.get("tree_hash", ""),
            "snapshot_tree_hash": snapshot_state.get("snapshot_tree_hash", ""),
            "source_lockfile_hash": source_state.get("lockfile_hash", ""),
            "lockfile_hash": snapshot_state.get("lockfile_hash", ""),
            "task_manifest_hash": task_manifest_hash,
            "route_profile_hash": hermetic_environment.effective_config.get("route_profile_hash") if hermetic_environment else "",
            "agent_config_hash": hermetic_environment.effective_config_sha256 if hermetic_environment else "",
            "model_id": args.model_id,
            "reasoning_effort": args.reasoning_effort,
            "run_dir": str(run_dir),
            "completion_reason": bridge_result.completion_reason,
            "failure_reason": metrics.get("failure_reason", ""),
            "wall_seconds": metrics.get("wall_seconds", 0),
            "semantic_setup_seconds": round(semantic_setup_seconds, 3),
            "task_execution_seconds": metrics.get("task_execution_seconds", metrics.get("wall_seconds", 0)),
            "end_to_end_seconds": metrics.get(
                "end_to_end_seconds",
                round(float(metrics.get("wall_seconds", 0) or 0) + semantic_setup_seconds, 3),
            ),
            "correctness_status": judge["correctness_status"],
            "policy_adherence": judge["policy_adherence"],
            "policy_violations": judge["violations"],
            "expected_success_signal_seen": judge.get("expected_success_signal_seen", False),
            "expected_proof_layer_seen": judge.get("expected_proof_layer_seen", False),
            "token_source": metrics.get("token_source", "proxy"),
            "exact_input_tokens": metrics.get("exact_input_tokens"),
            "exact_output_tokens": metrics.get("exact_output_tokens"),
            "exact_total_tokens": metrics.get("exact_total_tokens"),
            "exact_cached_input_tokens": metrics.get("exact_cached_input_tokens"),
            "exact_uncached_input_tokens": exact_uncached_input_tokens(metrics),
            "exact_uncached_total_tokens": metrics.get("exact_uncached_total_tokens"),
            "exact_cache_creation_input_tokens": metrics.get("exact_cache_creation_input_tokens"),
            "exact_cache_read_input_tokens": metrics.get("exact_cache_read_input_tokens"),
            "exact_reasoning_output_tokens": metrics.get("exact_reasoning_output_tokens"),
            "exact_usage_event_count": metrics.get("exact_usage_event_count"),
            "agent_reported_input_tokens": metrics.get("agent_reported_input_tokens"),
            "agent_reported_output_tokens": metrics.get("agent_reported_output_tokens"),
            "agent_reported_total_tokens": metrics.get("agent_reported_total_tokens"),
            "model_visible_bytes": metrics.get("model_visible_bytes", 0),
            "raw_dump_incidents": metrics.get("raw_dump_incidents", 0),
            "raw_output_bytes": metrics.get("raw_output_bytes", 0),
            "raw_task_output_bytes": metrics.get("raw_task_output_bytes", metrics.get("raw_output_bytes", 0)),
            "raw_bootstrap_output_bytes": metrics.get("raw_bootstrap_output_bytes", 0),
            "raw_total_observed_output_bytes": metrics.get("raw_total_observed_output_bytes", metrics.get("raw_output_bytes", 0)),
            "tool_output_bytes": metrics.get("tool_output_bytes", 0),
            "tool_evidence_source": metrics.get("tool_evidence_source", "missing"),
            "observed_tools": metrics.get("observed_tools", []),
            "observed_task_tools": metrics.get("observed_task_tools", []),
            "observed_tool_event_count": len(metrics.get("observed_tool_events", []) or []),
            "route_isolation_mode": isolation.mode,
            "route_hard_controls": isolation.hard_controls,
            "route_weak_controls": isolation.weak_controls,
            "serena_readiness_status": serena_readiness.get("status") if serena_readiness else "",
            "serena_readiness_ready": serena_readiness.get("ready") if serena_readiness else None,
            "serena_readiness_reason": serena_readiness.get("reason") if serena_readiness else "",
            "serena_readiness_warnings": serena_readiness.get("warnings") if serena_readiness else [],
            "serena_readiness_symbol": serena_readiness.get("symbol") if serena_readiness else "",
            "serena_readiness_source_file": serena_readiness.get("source_file") if serena_readiness else "",
            "model_visible_proxy_tokens": metrics.get("model_visible_proxy_tokens", 0),
            "tool_call_count": metrics.get("tool_call_count", 0),
            "files_opened_count": metrics.get("files_opened_count", 0),
            "search_count": metrics.get("search_count", 0),
            "semantic_tool_count": metrics.get("semantic_tool_count", 0),
            "runtime_tool_count": metrics.get("runtime_tool_count", 0),
            "ast_grep_count": metrics.get("ast_grep_count", 0),
        }
        oracle_result = verify_transcript_file(
            task_id=task.task_id,
            oracle=task_oracles.get(task.task_id) or task_oracles.get(f"family:{task.task_family}"),
            transcript_path=bridge_result.transcript_path,
            run_row=row,
        )
        semantic_session = semantic_session_artifact(
            run_id=run_id,
            profile_id=profile_id,
            semantic_access_enabled=bool(row["semantic_access_enabled"]),
            isolated_serena_session=args.isolated_serena_session,
            hermetic_environment=hermetic_environment,
            serena_readiness=serena_readiness,
            tool_versions=tool_versions,
            project_path_hmac=private_hmac(task_repo_path, key_env=args.hmac_key_env),
        )
        to_json_file(run_dir / "semantic-session.json", semantic_session)
        oracle_payload = asdict(oracle_result)
        to_json_file(run_dir / "oracle.json", oracle_payload)
        row.update(
            {
                "semantic_session_mode": semantic_session["mode"],
                "semantic_session_isolated": semantic_session["isolated"],
                "semantic_session_artifact": "semantic-session.json",
                "semantic_session_id_hmac": private_hmac(str(semantic_session.get("session_id", "")), key_env=args.hmac_key_env)
                if semantic_session.get("semantic_access_enabled")
                else "",
                "semantic_project_path_hmac": semantic_session.get("project_path_hmac", ""),
                "codex_version": tool_versions.get("codex", ""),
                "serena_version": tool_versions.get("serena", ""),
                "sourcekit_lsp_version": tool_versions.get("sourcekit-lsp", ""),
                "kotlin_language_server_version": tool_versions.get("kotlin-language-server", ""),
                "json_language_server_version": tool_versions.get("vscode-json-languageserver", ""),
                "os_version": tool_versions.get("os", ""),
                "oracle_id": oracle_result.oracle_id,
                "oracle_type": oracle_result.oracle_type,
                "oracle_status": oracle_result.status,
                "oracle_reason": oracle_result.reason,
            }
        )
        append_jsonl(runs_path, row)
        monitor_event(
            monitor_path,
            {
                "event": "run_completed",
                "created_at": utc_now(),
                "run_id": run_id,
                "agent": agent_profile.agent_id,
                "profile": profile_id,
                "task_id": task.task_id,
                "task_family": task.task_family,
                "dynamic_target": dynamic_target,
                "repeat_index": repeat_index,
                "correctness_status": judge["correctness_status"],
                "policy_adherence": judge["policy_adherence"],
                "model_visible_proxy_tokens": metrics.get("model_visible_proxy_tokens", 0),
                "raw_dump_incidents": metrics.get("raw_dump_incidents", 0),
            },
            enabled=args.monitor,
        )
    write_treatment_diff_artifact(rows=load_run_rows(runs_path), out=out_root / "treatment-diffs.jsonl")
    summary = write_report(runs_jsonl=runs_path, out_dir=out_root, dry_run=args.dry_run)
    return {"manifest": manifest, "summary": summary, "out": str(out_root)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Real Agent Routing Benchmark.")
    parser.add_argument("--agent", default="codex", choices=["codex", "claude-code", "cursor", "cursor-agent"])
    parser.add_argument("--agents", help="Comma-separated subject agents to run, e.g. codex,claude-code,cursor-agent.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repo-map", help="Comma-separated task repo mapping, e.g. sample_b2b_android=/repo/a,sample_retail_android=/repo/b.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--arms", default="A-search-only,D-full-router")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--study-plan", help="Path to a preregistered real-agent study plan.")
    parser.add_argument("--task-oracles", help="Path to external task oracle definitions for study correctness checks.")
    parser.add_argument(
        "--order-design",
        default="random",
        choices=["random", "input", "balanced-latin-square"],
        help="Run-order design. Study mode uses balanced-latin-square.",
    )
    parser.add_argument("--parallelism", type=int, default=1, help="Execution parallelism. Confirmatory study mode requires 1.")
    parser.add_argument("--model-id", default=DEFAULT_STUDY_MODEL_ID, help="Exact pinned model identifier recorded for study runs.")
    parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT, help="Fixed reasoning effort label/config value.")
    parser.add_argument("--sandbox", default="read-only", choices=["read-only", "workspace-write", "danger-full-access"])
    parser.add_argument("--isolated-agent-home", action="store_true", help="Use a fresh controlled agent home/config for every run.")
    parser.add_argument("--isolated-serena-session", action="store_true", help="Require per-run project-scoped Serena session config for semantic arms.")
    parser.add_argument("--prewarm-semantic-layer", action="store_true", help="Separate semantic readiness/setup from task execution timing.")
    parser.add_argument("--capture-versions", action="store_true", help="Capture controller/tool versions in the manifest.")
    parser.add_argument("--require-snapshots", action="store_true", help="Require clean source repos and detached worktree snapshots.")
    parser.add_argument("--hmac-key-env", default="RARB_PRIVATE_HMAC_KEY", help="Environment variable that contains the private HMAC key for private fingerprints.")
    parser.add_argument("--task-limit", type=int)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true", help="Run a live subject agent; requires adapter support.")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow live runs when the target repo is dirty.")
    parser.add_argument("--snapshot-repos", action="store_true", help="Run against clean detached git worktree snapshots under the output directory.")
    parser.add_argument("--seed", type=int, help="Random seed for run order and sampled code prompts. Defaults to a generated seed recorded in the manifest.")
    parser.add_argument("--no-randomize-order", action="store_true")
    parser.add_argument("--monitor", action="store_true", help="Print one progress line per run and write monitor.jsonl.")
    parser.add_argument("--stream-agent-output", action="store_true", help="Stream live subject-agent output to stdout while capturing the transcript.")
    parser.add_argument("--terminal-mode", choices=["pty", "tmux", "subprocess", "codex-tui"], help="Live control mode. Defaults to the agent config.")
    parser.add_argument(
        "--skip-serena-readiness",
        action="store_true",
        help="Do not run the source-symbol Serena readiness smoke before live semantic-router cells.",
    )
    parser.add_argument(
        "--serena-readiness-timeout",
        type=int,
        default=90,
        help="Timeout in seconds for the Serena source-symbol readiness smoke.",
    )
    parser.add_argument(
        "--require-clean-serena-process-state",
        action="store_true",
        help="Fail live semantic-router cells when Serena readiness sees multiple stale Serena/Kotlin/JSON LSP processes.",
    )
    parser.add_argument(
        "--static-code-prompts",
        action="store_true",
        help="Use task TSV prompts exactly as written instead of sampling real repo symbols for source-symbol tasks.",
    )
    parser.add_argument(
        "--resume-from",
        help="Carry forward existing runs.jsonl rows from a previous output and execute only missing agent/profile/task/repeat cells into --out.",
    )
    parser.add_argument(
        "--rerun-failed",
        action="store_true",
        help="With --resume-from, rerun cells whose carried row failed correctness or had policy violations.",
    )
    parser.add_argument("--clean-out", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of Codex TUI output.")
    args = parser.parse_args(argv)
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    if args.parallelism != 1:
        raise SystemExit("parallel execution is not implemented; use --parallelism 1")
    if args.serena_readiness_timeout < 1:
        raise SystemExit("--serena-readiness-timeout must be >= 1")
    if args.dry_run == args.live:
        raise SystemExit("choose exactly one of --dry-run or --live")
    if args.no_randomize_order and args.order_design == "random":
        args.order_design = "input"
    if args.clean_out:
        clean_output_dir(resolve_output_path(args.out))
    result = run_benchmark(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(build_codex_tui_summary(result["summary"], out_dir=result["out"], dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
