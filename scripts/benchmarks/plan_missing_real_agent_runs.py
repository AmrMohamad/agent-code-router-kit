from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.audit_real_agent_benchmark_readiness import adapter_rows, split_csv
from scripts.benchmarks.build_real_agent_report import load_runs
from scripts.benchmarks.run_real_agent_benchmark import DEFAULT_TASKS
from scripts.lib.agent_session import load_tasks, to_json_file, utc_now


def _md_cell(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    text = str(value if value is not None else "")
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _markdown_table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_cell(value) for value in row) + " |")
    return lines


def _has_non_proxy_token_totals(row: dict[str, object]) -> bool:
    token_source = str(row.get("probe_token_source") or row.get("token_source") or "")
    if token_source == "exact":
        return (row.get("probe_exact_total_tokens") if "probe_exact_total_tokens" in row else row.get("exact_total_tokens")) is not None
    if token_source == "agent_reported":
        return (
            row.get("probe_agent_reported_total_tokens")
            if "probe_agent_reported_total_tokens" in row
            else row.get("agent_reported_total_tokens")
        ) is not None
    return False


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _task_profiles_from_manifest(manifest: dict[str, object], rows: list[dict[str, object]]) -> dict[tuple[str, str], set[str]]:
    task_manifest = Path(str(manifest.get("task_manifest") or ""))
    task_ids = {str(task_id) for task_id in manifest.get("task_ids", []) if str(task_id)}
    profiles: dict[tuple[str, str], set[str]] = {}
    if task_manifest.exists():
        for task in load_tasks(task_manifest):
            if task_ids and task.task_id not in task_ids:
                continue
            profiles[(task.task_id, task.repo)] = set(task.route_profiles)
    if profiles:
        return profiles
    for row in rows:
        key = (str(row.get("task_id", "")), str(row.get("repo", "")))
        if key[0]:
            profiles.setdefault(key, set()).add(str(row.get("profile", "")))
    return profiles


def _adapter_readiness(paths: list[str | Path] | None) -> dict[str, dict[str, object]]:
    readiness: dict[str, dict[str, object]] = {}
    for row in adapter_rows(paths):
        agent = str(row.get("agent", ""))
        if not agent:
            continue
        weak_controls = list(row.get("route_weak_controls") or row.get("probe_route_weak_controls") or [])
        token_source = str(row.get("probe_token_source") or row.get("token_source") or "")
        token_telemetry_ready = (
            row.get("token_telemetry_ready")
            if isinstance(row.get("token_telemetry_ready"), bool)
            else row.get("non_proxy_token_telemetry_ready")
        )
        if not isinstance(token_telemetry_ready, bool):
            token_telemetry_ready = row.get("probe_non_proxy_token_telemetry_ready")
        if not isinstance(token_telemetry_ready, bool):
            token_telemetry_ready = _has_non_proxy_token_totals(row)
        elif token_telemetry_ready:
            token_telemetry_ready = _has_non_proxy_token_totals(row)
        ready = (
            row.get("status") == "pass"
            and row.get("ready_for_live_benchmark", True) is not False
            and not weak_controls
        )
        readiness[agent] = {
            "status": "ready" if ready else "blocked",
            "probe_status": row.get("status"),
            "reason": row.get("reason", ""),
            "completion_reason": row.get("completion_reason", ""),
            "next_action": row.get("next_action", ""),
            "route_weak_controls": weak_controls,
            "token_source": token_source,
            "token_telemetry_ready": token_telemetry_ready,
            "token_telemetry_next_action": row.get("token_telemetry_next_action", ""),
        }
    return readiness


def _argv_for_agent(
    *,
    agent: str,
    benchmark_out: Path,
    manifest: dict[str, object],
    profiles: list[str],
) -> list[str]:
    repo = str(manifest.get("repo") or Path.cwd())
    task_manifest = str(manifest.get("task_manifest") or DEFAULT_TASKS)
    repeats = str(manifest.get("repeats") or 1)
    argv = [
        "python3",
        "scripts/benchmarks/run_real_agent_benchmark.py",
        "--live",
        "--agents",
        agent,
        "--repo",
        repo,
        "--tasks",
        task_manifest,
        "--arms",
        ",".join(profiles),
        "--repeats",
        repeats,
        "--resume-from",
        str(benchmark_out),
        "--out",
        str(benchmark_out.parent / f"{benchmark_out.name}-resume-{agent}"),
        "--snapshot-repos",
        "--monitor",
        "--terminal-mode",
        "tmux",
    ]
    repo_map = manifest.get("repo_map")
    if isinstance(repo_map, dict) and repo_map:
        repo_map_arg = ",".join(f"{key}={value}" for key, value in repo_map.items() if key)
        if repo_map_arg:
            argv.extend(["--repo-map", repo_map_arg])
    return argv


def _missing_repo_map_entries(manifest: dict[str, object], task_profiles: dict[tuple[str, str], set[str]]) -> list[str]:
    repo_map = manifest.get("repo_map")
    mapped = set(repo_map) if isinstance(repo_map, dict) else set()
    return sorted({repo for _, repo in task_profiles if repo and repo not in mapped})


def _valid_present_rows(rows: list[dict[str, object]], manifest: dict[str, object]) -> list[dict[str, object]]:
    repo_map = manifest.get("repo_map")
    mapped = set(repo_map) if isinstance(repo_map, dict) else set()
    return [
        row
        for row in rows
        if not str(row.get("repo", "")) or str(row.get("repo", "")) in mapped
    ]


def _execution_plan(
    *,
    missing: list[dict[str, object]],
    adapter_state: dict[str, dict[str, object]],
    runnable_agents: list[str],
    blocked_agents: list[str],
    unknown_agents: list[str],
    missing_repo_maps: list[str] | None = None,
) -> dict[str, object]:
    missing_repo_maps = missing_repo_maps or []
    if not missing:
        status = "complete"
        boundary = "all requested benchmark matrix cells are present"
    elif runnable_agents:
        status = "runnable"
        boundary = "some missing cells can run now; use resume_commands for runnable agents"
    elif missing_repo_maps:
        status = "blocked"
        boundary = "missing cells remain, but live repo mappings are incomplete"
    elif blocked_agents:
        status = "blocked"
        boundary = "missing cells remain, but no blocked adapter can be launched safely now"
    else:
        status = "unknown"
        boundary = "missing cells remain, but adapter readiness evidence is missing"
    missing_by_agent = {
        agent: sum(1 for cell in missing if cell["agent"] == agent)
        for agent in sorted({str(cell["agent"]) for cell in missing})
    }
    blocked_actions = []
    for agent in blocked_agents:
        state = adapter_state.get(agent, {})
        repo_blockers = sorted({str(cell["repo"]) for cell in missing if cell["agent"] == agent and cell.get("blocker_reason") == "missing_repo_map"})
        blocked_actions.append(
            {
                "agent": agent,
                "missing_cells": missing_by_agent.get(agent, 0),
                "reason": "missing_repo_map" if repo_blockers else state.get("reason", ""),
                "next_action": (
                    "add --repo-map entries for " + ",".join(repo_blockers)
                    if repo_blockers
                    else state.get("next_action", "")
                ),
                "token_source": state.get("token_source", ""),
                "token_telemetry_ready": state.get("token_telemetry_ready", False),
                "token_telemetry_next_action": state.get("token_telemetry_next_action", ""),
            }
        )
    return {
        "status": status,
        "can_resume_now": bool(runnable_agents),
        "completion_boundary": boundary,
        "missing_by_agent": missing_by_agent,
        "runnable_agents": runnable_agents,
        "blocked_actions": blocked_actions,
        "unknown_agents": unknown_agents,
        "missing_repo_map_entries": missing_repo_maps,
    }


def build_missing_run_markdown(result: dict[str, object]) -> str:
    execution_plan = result.get("execution_plan") if isinstance(result.get("execution_plan"), dict) else {}
    missing_cells = result.get("missing_cells") if isinstance(result.get("missing_cells"), list) else []
    resume_commands = result.get("resume_commands") if isinstance(result.get("resume_commands"), list) else []
    blocked_actions = execution_plan.get("blocked_actions") if isinstance(execution_plan.get("blocked_actions"), list) else []
    adapter_readiness = result.get("adapter_readiness") if isinstance(result.get("adapter_readiness"), dict) else {}
    missing_repo_maps = result.get("missing_repo_map_entries") if isinstance(result.get("missing_repo_map_entries"), list) else []
    lines = [
        "# Missing Real-Agent Benchmark Runs",
        "",
        f"- Benchmark output: `{result.get('benchmark_out', '')}`",
        f"- Status: `{execution_plan.get('status', 'unknown')}`",
        f"- Completion boundary: {execution_plan.get('completion_boundary', '')}",
        f"- Missing cells: `{result.get('missing_cell_count', 0)}`",
        f"- Runnable missing cells now: `{result.get('runnable_missing_cell_count', 0)}`",
        f"- Can resume now: `{str(execution_plan.get('can_resume_now', False)).lower()}`",
        f"- Existing run rows: `{result.get('existing_runs', 0)}`",
        f"- Invalid existing rows: `{result.get('invalid_existing_runs', 0)}`",
        "",
    ]
    if not missing_cells:
        lines.extend(
            [
                "All requested benchmark matrix cells are present.",
                "",
            ]
        )
    if missing_repo_maps:
        lines.extend(
            [
                "## Missing Repo Mappings",
                "",
                "These repo names appear in the task manifest but are not present in `repo_map`.",
                "",
            ]
        )
        lines.extend(_markdown_table(["repo", "next_action"], [[repo, f"add --repo-map {repo}=/absolute/path"] for repo in missing_repo_maps]))
        lines.append("")
    if blocked_actions:
        lines.extend(["## Blocked Agents", ""])
        lines.extend(
            _markdown_table(
                ["agent", "missing_cells", "reason", "token_source", "token_ready", "next_action"],
                [
                    [
                        action.get("agent", ""),
                        action.get("missing_cells", 0),
                        action.get("reason", ""),
                        action.get("token_source", ""),
                        action.get("token_telemetry_ready", False),
                        action.get("next_action", ""),
                    ]
                    for action in blocked_actions
                    if isinstance(action, dict)
                ],
            )
        )
        lines.append("")
    readiness_rows = []
    for agent, state in sorted(adapter_readiness.items()):
        if not isinstance(state, dict):
            continue
        readiness_rows.append(
            [
                agent,
                state.get("status", ""),
                state.get("reason", ""),
                state.get("token_source", ""),
                state.get("token_telemetry_ready", False),
                state.get("token_telemetry_next_action", ""),
            ]
        )
    if readiness_rows:
        lines.extend(["## Adapter Readiness", ""])
        lines.extend(_markdown_table(["agent", "status", "reason", "token_source", "token_ready", "token_next_action"], readiness_rows))
        lines.append("")
    if resume_commands:
        lines.extend(["## Resume Commands", ""])
        for command in resume_commands:
            if not isinstance(command, dict):
                continue
            argv = command.get("argv") if isinstance(command.get("argv"), list) else []
            lines.extend(
                [
                    f"### {command.get('agent', '')}",
                    "",
                    "```sh",
                    " ".join(str(part) for part in argv),
                    "```",
                    "",
                ]
            )
    elif missing_cells:
        lines.extend(
            [
                "## Resume Commands",
                "",
                "No resume command is runnable from current adapter readiness evidence.",
                "",
            ]
        )
    if missing_cells:
        lines.extend(["## Missing Cells", ""])
        lines.extend(
            _markdown_table(
                ["agent", "profile", "task_id", "repo", "repeat", "adapter_status", "reason", "next_action"],
                [
                    [
                        cell.get("agent", ""),
                        cell.get("profile", ""),
                        cell.get("task_id", ""),
                        cell.get("repo", ""),
                        cell.get("repeat_index", ""),
                        cell.get("adapter_status", ""),
                        cell.get("blocker_reason", ""),
                        cell.get("next_action", ""),
                    ]
                    for cell in missing_cells
                    if isinstance(cell, dict)
                ],
            )
        )
        lines.append("")
    lines.extend(
        [
            "## Interpretation",
            "",
            (
                "This benchmark matrix is complete for the requested agents/profiles."
                if not missing_cells
                else "This benchmark matrix is incomplete; do not describe it as a full multi-agent comparison until the missing cells are filled or explicitly excluded."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def plan_missing_runs(
    *,
    benchmark_out: str | Path,
    agents: list[str],
    profiles: list[str],
    adapter_probe: list[str | Path] | None = None,
) -> dict[str, object]:
    root = Path(benchmark_out).expanduser().resolve()
    runs_path = root / "runs.jsonl"
    rows = load_runs(runs_path) if runs_path.exists() else []
    manifest = _load_json(root / "run-manifest.json")
    repeats = int(manifest.get("repeats", 1) or 1)
    task_profiles = _task_profiles_from_manifest(manifest, rows)
    missing_repo_maps = _missing_repo_map_entries(manifest, task_profiles)
    present_rows = _valid_present_rows(rows, manifest)
    present = {
        (
            str(row.get("agent", "")),
            str(row.get("profile", "")),
            str(row.get("task_id", "")),
            str(row.get("repo", "")),
            str(row.get("repeat_index", "")),
        )
        for row in present_rows
    }
    adapter_state = _adapter_readiness(adapter_probe)
    missing: list[dict[str, object]] = []
    for (task_id, repo), supported_profiles in sorted(task_profiles.items()):
        for repeat_index in range(repeats):
            for agent in agents:
                state = adapter_state.get(agent, {"status": "unknown"})
                for profile in profiles:
                    if profile not in supported_profiles:
                        continue
                    cell = (agent, profile, task_id, repo, str(repeat_index))
                    if cell in present:
                        continue
                    repo_mapping_missing = bool(repo and repo in missing_repo_maps)
                    adapter_status = "blocked_repo_mapping" if repo_mapping_missing else state["status"]
                    missing.append(
                        {
                            "agent": agent,
                            "profile": profile,
                            "task_id": task_id,
                            "repo": repo,
                            "repeat_index": repeat_index,
                            "adapter_status": adapter_status,
                            "runnable_now": state["status"] == "ready" and not repo_mapping_missing,
                            "blocker_reason": "missing_repo_map" if repo_mapping_missing else state.get("reason", "") if state["status"] == "blocked" else "",
                            "next_action": (
                                f"add --repo-map {repo}=/absolute/path"
                                if repo_mapping_missing
                                else state.get("next_action", "") if state["status"] == "blocked" else ""
                            ),
                            "token_source": state.get("token_source", ""),
                            "token_telemetry_ready": state.get("token_telemetry_ready", False),
                            "token_telemetry_next_action": state.get("token_telemetry_next_action", ""),
                        }
                    )
    runnable_agents = sorted({str(cell["agent"]) for cell in missing if cell["runnable_now"]})
    if missing_repo_maps:
        runnable_agents = []
    blocked_agents = sorted({str(cell["agent"]) for cell in missing if str(cell["adapter_status"]).startswith("blocked")})
    unknown_agents = sorted({str(cell["agent"]) for cell in missing if cell["adapter_status"] == "unknown"})
    commands = [
        {
            "agent": agent,
            "argv": _argv_for_agent(agent=agent, benchmark_out=root, manifest=manifest, profiles=profiles),
        }
        for agent in runnable_agents
    ]
    execution_plan = _execution_plan(
        missing=missing,
        adapter_state=adapter_state,
        runnable_agents=runnable_agents,
        blocked_agents=blocked_agents,
        unknown_agents=unknown_agents,
        missing_repo_maps=missing_repo_maps,
    )
    return {
        "created_at": utc_now(),
        "benchmark_out": str(root),
        "existing_runs": len(rows),
        "invalid_existing_runs": len(rows) - len(present_rows),
        "agents": agents,
        "profiles": profiles,
        "missing_cell_count": len(missing),
        "runnable_missing_cell_count": sum(1 for cell in missing if cell["runnable_now"]),
        "blocked_agents": blocked_agents,
        "unknown_agents": unknown_agents,
        "adapter_readiness": adapter_state,
        "missing_repo_map_entries": missing_repo_maps,
        "execution_plan": execution_plan,
        "missing_cells": missing,
        "resume_commands": commands,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan only the missing cells from a real-agent benchmark matrix.")
    parser.add_argument("--benchmark-out", required=True)
    parser.add_argument("--agents", required=True)
    parser.add_argument("--profiles", default="A-search-only,D-full-router")
    parser.add_argument("--adapter-probe", action="append", help="Adapter probe or doctor summary path/directory.")
    parser.add_argument("--out")
    parser.add_argument("--out-markdown", help="Write a human-readable missing-run plan markdown artifact.")
    args = parser.parse_args(argv)
    result = plan_missing_runs(
        benchmark_out=args.benchmark_out,
        agents=split_csv(args.agents),
        profiles=split_csv(args.profiles),
        adapter_probe=args.adapter_probe,
    )
    if args.out:
        to_json_file(args.out, result)
    if args.out_markdown:
        Path(args.out_markdown).expanduser().resolve().write_text(build_missing_run_markdown(result), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result["missing_cell_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
