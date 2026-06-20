from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.build_real_agent_report import load_runs, write_report
from scripts.benchmarks.judge_agent_run import judge_file
from scripts.benchmarks.run_real_agent_benchmark import DEFAULT_TASKS, profile_path
from scripts.lib.agent_session import append_jsonl, load_route_profile, load_tasks, to_json_file, utc_now
from scripts.lib.token_proxy import byte_count, normalize_token_fields
from scripts.lib.transcript_parser import (
    classify_failure_reason,
    count_tool_mentions,
    extract_token_usage,
    observed_tool_events,
    parse_benchmark_response,
    tool_output_bytes,
)


RUN_FIELD_DEFAULTS = {
    "repeat_index": 0,
    "repo": "",
    "repo_path": "",
    "completion_reason": "",
    "wall_seconds": 0,
}
CONTROLLED_COMPLETION_REASONS = {"output_budget_exceeded", "timeout", "process_timeout", "terminal_idle_timeout"}


def load_task_map(path: str | Path) -> dict[str, object]:
    return {task.task_id: task for task in load_tasks(path)}


def run_sentinel(run_id: str) -> str:
    return f"BENCHMARK_DONE_{run_id}"


def telemetry_completion_reason(run_dir: Path) -> str:
    telemetry_path = run_dir / "telemetry.jsonl"
    if not telemetry_path.exists():
        return ""
    reason = ""
    with telemetry_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if payload.get("event") == "run_completed":
                reason = str(payload.get("completion_reason") or "")
            elif payload.get("event") == "output_budget_exceeded":
                reason = "output_budget_exceeded"
            elif payload.get("event") == "terminal_idle_timeout":
                reason = "terminal_idle_timeout"
            elif payload.get("event") == "process_timeout":
                reason = "process_timeout"
    return reason


def recompute_metrics(*, run_dir: Path, run_id: str, agent: str, dry_run: bool) -> dict[str, object]:
    prompt = (run_dir / "task-packet.md").read_text(encoding="utf-8")
    transcript = (run_dir / "transcript.txt").read_text(encoding="utf-8")
    parsed = parse_benchmark_response(transcript, sentinel=run_sentinel(run_id))
    observed_events = observed_tool_events(transcript)
    observed_task_events = [event for event in observed_events if event.get("phase") != "bootstrap_context"]
    output_bytes = tool_output_bytes(transcript, fallback_to_transcript=not dry_run)
    token_usage = extract_token_usage(transcript)
    telemetry_reason = telemetry_completion_reason(run_dir)
    completion_reason = "sentinel" if parsed.done else "missing_sentinel"
    if telemetry_reason in CONTROLLED_COMPLETION_REASONS:
        completion_reason = telemetry_reason
    metrics = {
        "run_id": run_id,
        "agent": agent,
        "completion_reason": completion_reason,
        "failure_reason": classify_failure_reason(transcript),
        "done": parsed.done,
        "contract_present": parsed.contract_present,
        "status": parsed.status,
        "policy_adherence": parsed.policy_adherence,
        "tool_call_count": len(parsed.tools_used),
        "files_opened_count": len(parsed.files_opened),
        "raw_dump_incidents": parsed.raw_dump_incidents,
        "raw_output_bytes": output_bytes,
        "observed_tool_events": observed_events,
        "observed_tools": [event["tool"] for event in observed_events],
        "observed_task_tools": [event["tool"] for event in observed_task_events],
        "tool_evidence_source": "observed" if observed_task_events else "self_report" if parsed.tools_used else "missing",
        **count_tool_mentions(transcript),
        **normalize_token_fields(
            prompt_bytes=byte_count(prompt),
            answer_bytes=byte_count(parsed.final_answer),
            transcript_bytes=byte_count(transcript),
            tool_output_bytes=output_bytes,
            exact_tokens=token_usage.get("exact"),  # type: ignore[arg-type]
            agent_reported_tokens=token_usage.get("agent_reported"),  # type: ignore[arg-type]
        ),
    }
    previous_metrics_path = run_dir / "metrics.normalized.json"
    if previous_metrics_path.exists():
        previous = json.loads(previous_metrics_path.read_text(encoding="utf-8"))
        metrics["wall_seconds"] = previous.get("wall_seconds", 0)
        previous_reason = str(previous.get("completion_reason") or "")
        if previous_reason in CONTROLLED_COMPLETION_REASONS:
            metrics["completion_reason"] = previous_reason
    else:
        metrics["wall_seconds"] = 0
    return metrics


def rebuild_row(row: dict[str, object], *, metrics: dict[str, object], judge: dict[str, object]) -> dict[str, object]:
    updated = {**RUN_FIELD_DEFAULTS, **row}
    route_isolation = {}
    route_isolation_path = Path(str(row["run_dir"])) / "route-isolation.json"
    if route_isolation_path.exists():
        route_isolation = json.loads(route_isolation_path.read_text(encoding="utf-8"))
    updated.update(
        {
            "completion_reason": metrics.get("completion_reason", updated.get("completion_reason", "")),
            "failure_reason": metrics.get("failure_reason", ""),
            "wall_seconds": metrics.get("wall_seconds", 0),
            "correctness_status": judge["correctness_status"],
            "policy_adherence": judge["policy_adherence"],
            "policy_violations": judge["violations"],
            "expected_success_signal_seen": judge.get("expected_success_signal_seen", False),
            "expected_proof_layer_seen": judge.get("expected_proof_layer_seen", False),
            "token_source": metrics.get("token_source", "proxy"),
            "exact_input_tokens": metrics.get("exact_input_tokens"),
            "exact_output_tokens": metrics.get("exact_output_tokens"),
            "exact_total_tokens": metrics.get("exact_total_tokens"),
            "exact_uncached_total_tokens": metrics.get("exact_uncached_total_tokens"),
            "exact_cached_input_tokens": metrics.get("exact_cached_input_tokens"),
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
            "tool_output_bytes": metrics.get("tool_output_bytes", 0),
            "tool_evidence_source": metrics.get("tool_evidence_source", "missing"),
            "observed_tools": metrics.get("observed_tools", []),
            "observed_task_tools": metrics.get("observed_task_tools", []),
            "observed_tool_event_count": len(metrics.get("observed_tool_events", []) or []),
            "route_isolation_mode": route_isolation.get("mode", updated.get("route_isolation_mode", "")),
            "route_hard_controls": route_isolation.get("hard_controls", updated.get("route_hard_controls", [])),
            "route_weak_controls": route_isolation.get("weak_controls", updated.get("route_weak_controls", [])),
            "model_visible_proxy_tokens": metrics.get("model_visible_proxy_tokens", 0),
            "tool_call_count": metrics.get("tool_call_count", 0),
            "files_opened_count": metrics.get("files_opened_count", 0),
            "search_count": metrics.get("search_count", 0),
            "semantic_tool_count": metrics.get("semantic_tool_count", 0),
            "runtime_tool_count": metrics.get("runtime_tool_count", 0),
            "ast_grep_count": metrics.get("ast_grep_count", 0),
        }
    )
    return updated


def rejudge(
    *,
    benchmark_out: str | Path,
    tasks: str | Path | None,
    write: bool,
    replace_runs: bool,
) -> dict[str, object]:
    out_root = Path(benchmark_out).expanduser().resolve()
    runs_path = out_root / "runs.jsonl"
    manifest_path = out_root / "run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    dry_run = bool(manifest.get("dry_run", False))
    task_manifest = Path(tasks or str(manifest.get("task_manifest") or DEFAULT_TASKS)).expanduser()
    task_map = load_task_map(task_manifest)
    rows = load_runs(runs_path)
    updated_rows: list[dict[str, object]] = []
    changes: list[dict[str, object]] = []
    for row in rows:
        run_dir = Path(str(row["run_dir"]))
        run_id = str(row["run_id"])
        metrics = recompute_metrics(run_dir=run_dir, run_id=run_id, agent=str(row.get("agent", "")), dry_run=dry_run)
        route_profile = load_route_profile(profile_path(str(row["profile"])))
        judge = judge_file(
            run_dir / "transcript.txt",
            sentinel=run_sentinel(run_id),
            forbidden_claims=str(task_map[str(row["task_id"])].forbidden_claims),
            route_profile=route_profile,
            task=task_map[str(row["task_id"])],
            metrics=metrics,
            dry_run=dry_run,
            out=(run_dir / "judge.json") if write else None,
        )
        updated = rebuild_row(row, metrics=metrics, judge=judge)
        updated_rows.append(updated)
        changes.append(
            {
                "run_id": run_id,
                "old_correctness_status": row.get("correctness_status"),
                "new_correctness_status": updated.get("correctness_status"),
                "old_policy_violations": row.get("policy_violations", []),
                "new_policy_violations": updated.get("policy_violations", []),
                "old_token_source": row.get("token_source"),
                "new_token_source": updated.get("token_source"),
            }
        )
        if write:
            to_json_file(run_dir / "metrics.normalized.json", metrics)
    target_runs = out_root / "runs.rejudged.jsonl"
    if write:
        if replace_runs:
            backup = out_root / f"runs.{utc_now().replace(':', '').replace('-', '')}.bak.jsonl"
            shutil.copy2(runs_path, backup)
            target_runs = runs_path
        if target_runs.exists():
            target_runs.unlink()
        for updated in updated_rows:
            append_jsonl(target_runs, updated)
        write_report(runs_jsonl=target_runs, out_dir=out_root, dry_run=dry_run)
    return {
        "benchmark_out": str(out_root),
        "task_manifest": str(task_manifest.resolve()),
        "runs": len(rows),
        "write": write,
        "replace_runs": replace_runs,
        "runs_path": str(target_runs) if write else "",
        "planned_runs_path": str(target_runs),
        "changes": changes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recompute metrics and judge records for existing RARB transcripts.")
    parser.add_argument("--benchmark-out", required=True)
    parser.add_argument("--tasks", help="Task TSV. Defaults to run-manifest.json task_manifest, then the public example TSV.")
    parser.add_argument("--write", action="store_true", help="Write metrics, judge files, reports, and runs.rejudged.jsonl.")
    parser.add_argument("--replace-runs", action="store_true", help="Replace runs.jsonl after writing a timestamped backup.")
    args = parser.parse_args(argv)
    if args.replace_runs and not args.write:
        raise SystemExit("--replace-runs requires --write")
    result = rejudge(
        benchmark_out=args.benchmark_out,
        tasks=args.tasks,
        write=args.write,
        replace_runs=args.replace_runs,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
