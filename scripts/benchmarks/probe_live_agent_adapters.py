from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.agents.generic_terminal_agent_bridge import TerminalAgentBridge
from scripts.benchmarks.run_real_agent_benchmark import agent_path, profile_path
from scripts.lib.agent_session import append_jsonl, load_agent_profile, load_route_profile, new_run_id, to_json_file, utc_now
from scripts.lib.route_isolation import materialize_route_isolation
from scripts.lib.transcript_parser import classify_failure_reason, parse_benchmark_response


ROOT = Path(__file__).resolve().parents[2]


def adapter_probe_prompt(*, agent_id: str, sentinel: str) -> str:
    return f"""# RARB Live Adapter Probe

You are the subject agent `{agent_id}` in a live adapter probe.

Do not edit files. Do not run shell commands. Return only this contract:

BENCHMARK_RESULT
status: pass
confidence: high

tools_used:

proof_layers:
  semantic_identity: not requested
  references: not requested
  runtime: live adapter process only

files_opened:
  count: 0
  paths:

raw_dump_incidents:
  count: 0

policy_adherence: pass

final_answer:
  live adapter process responded

{sentinel}
"""


def has_non_proxy_token_totals(metrics: dict[str, object]) -> bool:
    if metrics.get("token_source") == "exact":
        return metrics.get("exact_total_tokens") is not None
    if metrics.get("token_source") == "agent_reported":
        return metrics.get("agent_reported_total_tokens") is not None
    return False


def probe_agent(
    *,
    agent_id: str,
    repo: str | Path,
    out_root: str | Path,
    timeout_seconds: int,
    terminal_mode: str | None = None,
) -> dict[str, object]:
    profile = load_agent_profile(agent_path(agent_id))
    candidates = [profile.command, *profile.fallback_commands]
    resolved = next((shutil.which(candidate) for candidate in candidates if shutil.which(candidate)), None)
    run_id = new_run_id(f"adapter-{profile.agent_id}")
    run_dir = Path(out_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sentinel = f"BENCHMARK_DONE_{run_id}"
    route_profile = load_route_profile(profile_path("A-search-only"))
    isolation = materialize_route_isolation(
        agent_profile=profile,
        route_profile=route_profile,
        run_dir=run_dir,
        workspace_cwd=repo,
        probe_cursor_mcp=True,
        terminal_mode=terminal_mode or profile.terminal_mode,
    )
    prompt = adapter_probe_prompt(agent_id=profile.agent_id, sentinel=sentinel)
    (run_dir / "task-packet.md").write_text(prompt, encoding="utf-8")
    row: dict[str, object] = {
        "run_id": run_id,
        "agent": profile.agent_id,
        "created_at": utc_now(),
        "run_dir": str(run_dir),
        "command_candidates": candidates,
        "resolved_command": resolved,
        "supports_live": profile.supports_live,
        "route_profile": route_profile.profile_id,
        "route_isolation_mode": isolation.mode,
        "route_hard_controls": isolation.hard_controls,
        "route_weak_controls": isolation.weak_controls,
        "route_isolation_observations": isolation.observations,
    }
    if not profile.supports_live:
        row.update({"status": "fail", "reason": "adapter_supports_live_false"})
        return row
    if not resolved:
        row.update({"status": "fail", "reason": "command_not_found"})
        return row
    bridge = TerminalAgentBridge(
        profile,
        cwd=str(Path(repo).resolve()),
        dry_run=False,
        command=isolation.command,
        args=isolation.args,
        env=isolation.env,
        terminal_mode=terminal_mode or profile.terminal_mode,
    )
    to_json_file(run_dir / "launch-plan.json", asdict(bridge.launch_plan()))
    result = bridge.run_prompt(
        run_id=run_id,
        prompt=prompt,
        out_dir=run_dir,
        timeout_seconds=timeout_seconds,
        sentinel=sentinel,
        profile_id="A-search-only",
        task_id="adapter_live_probe",
    )
    transcript = Path(result.transcript_path).read_text(encoding="utf-8")
    metrics = json.loads(Path(result.metrics_path).read_text(encoding="utf-8"))
    parsed = parse_benchmark_response(transcript, sentinel=sentinel)
    failure_reason = classify_failure_reason(transcript)
    if not failure_reason and result.completion_reason == "timeout":
        failure_reason = "timeout"
    elif not failure_reason and result.completion_reason == "sentinel" and not parsed.contract_present:
        failure_reason = "missing_contract"
    elif not failure_reason and result.completion_reason != "sentinel":
        failure_reason = "missing_sentinel"
    row.update(
        {
            "status": "pass" if result.completion_reason == "sentinel" and parsed.contract_present else "fail",
            "reason": failure_reason,
            "completion_reason": result.completion_reason,
            "contract_present": parsed.contract_present,
            "done": parsed.done,
            "response_status": parsed.status,
            "wall_seconds": result.wall_seconds,
            "token_source": metrics.get("token_source", "proxy"),
            "exact_total_tokens": metrics.get("exact_total_tokens"),
            "exact_uncached_total_tokens": metrics.get("exact_uncached_total_tokens"),
            "exact_usage_event_count": metrics.get("exact_usage_event_count"),
            "agent_reported_total_tokens": metrics.get("agent_reported_total_tokens"),
            "non_proxy_token_telemetry_ready": has_non_proxy_token_totals(metrics),
        }
    )
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe live subject-agent adapters with a no-edit contract prompt.")
    parser.add_argument("--agents", default="codex,claude-code,cursor-agent")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--terminal-mode", choices=["pty", "tmux", "subprocess", "codex-tui"])
    args = parser.parse_args(argv)
    out_root = Path(args.out).expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for agent_id in [item.strip() for item in args.agents.split(",") if item.strip()]:
        row = probe_agent(
            agent_id=agent_id,
            repo=args.repo,
            out_root=out_root,
            timeout_seconds=args.timeout,
            terminal_mode=args.terminal_mode,
        )
        rows.append(row)
        append_jsonl(out_root / "adapter-probes.jsonl", row)
    summary = {
        "created_at": utc_now(),
        "out": str(out_root),
        "agents": len(rows),
        "pass": sum(1 for row in rows if row.get("status") == "pass"),
        "fail": sum(1 for row in rows if row.get("status") != "pass"),
        "rows": rows,
    }
    to_json_file(out_root / "adapter-probe-summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["fail"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
