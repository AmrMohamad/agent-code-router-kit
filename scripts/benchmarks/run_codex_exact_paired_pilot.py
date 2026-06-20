from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.audit_real_agent_benchmark_readiness import audit
from scripts.benchmarks.doctor_live_agent_adapters import run_doctor
from scripts.benchmarks.export_sanitized_live_pilot import export_sanitized_live_pilot
from scripts.benchmarks.run_real_agent_benchmark import ROOT, parse_repo_map, run_benchmark
from scripts.lib.agent_session import to_json_file, utc_now
from scripts.lib.serena_readiness import serena_process_cleanup_plan


DEFAULT_TASKS = ROOT / "benchmarks" / "real-agent-routing" / "tasks" / "android-realworld.local.tsv"
DEFAULT_SANITIZED_NAME = "sanitized-live-pilot"
PHASE_ORDER = ("doctor-preflight", "doctor-probe", "benchmark", "audit", "export")


def split_blocker_messages(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    messages: list[str] = []
    for item in items:
        if isinstance(item, dict):
            agent = str(item.get("agent") or "codex")
            reason = str(item.get("reason") or "")
            next_action = str(item.get("next_action") or "")
            pieces = [piece for piece in (agent, reason, next_action) if piece]
            messages.append(": ".join(pieces))
        elif item:
            messages.append(str(item))
    return messages


def write_pilot_status(out: Path, payload: dict[str, object]) -> dict[str, object]:
    enriched = {
        "created_at": utc_now(),
        "status_file": str((out / "pilot-status.json").resolve()),
        **payload,
    }
    to_json_file(out / "pilot-status.json", enriched)
    return enriched


def safe_clean_output_dir(path: Path) -> None:
    resolved = path.expanduser().resolve()
    temp_roots = {Path("/tmp").resolve(), Path("/private/tmp").resolve(), Path(tempfile.gettempdir()).resolve()}
    benchmark_results = (ROOT / "benchmarks" / "real-agent-routing" / "results").resolve()
    repo_results = (ROOT / "results" / "real-agent-routing").resolve()
    allowed = any(temp_root in resolved.parents for temp_root in temp_roots)
    allowed = allowed or benchmark_results == resolved or benchmark_results in resolved.parents
    allowed = allowed or repo_results == resolved or repo_results in resolved.parents
    if not allowed:
        raise SystemExit("--clean-out is only allowed under a temporary directory or RARB results directory")
    if resolved.exists():
        shutil.rmtree(resolved)


def cleanup_target_repo(args: argparse.Namespace) -> str:
    repo_map = parse_repo_map(args.repo_map, default_repo=args.repo)
    for repo_id, path in repo_map.items():
        if repo_id:
            return path
    return repo_map[""]


def strict_codex_paired_audit(*, benchmark_out: Path, doctor_out: Path, audit_out: Path) -> dict[str, object]:
    result = audit(
        benchmark_out=benchmark_out,
        adapter_probe=[doctor_out],
        expected_agents=["codex"],
        expected_profiles=["A-search-only", "D-full-router"],
        min_tasks=1,
        require_live=True,
        require_clean_repos=False,
        require_all_adapters=False,
        require_all_pass=True,
        require_observed_tools=True,
        require_non_proxy_tokens=True,
        require_no_weak_route_controls=True,
        require_hard_isolation_for_blocked_tools=True,
        require_paired_route_comparisons=True,
        required_savings_claim="exact_uncached",
        require_live_lifecycle_telemetry=True,
        require_fresh_sessions=True,
        require_randomized_order=True,
        require_repo_snapshots=False,
        require_repo_metadata=True,
        require_real_task_manifest=True,
        require_balanced_matrix=False,
        require_self_contained_artifacts=False,
        require_clean_serena_process_state=True,
        require_expected_proof_layer=True,
        require_matrix_completion_report=False,
        require_terminal_control_summary=True,
        require_route_policy_summary=True,
        missing_plan=None,
        allow_controlled_failures=False,
        min_supported_savings_pairs=1,
    )
    to_json_file(audit_out, result)
    return result


def benchmark_args(args: argparse.Namespace, *, benchmark_out: Path) -> argparse.Namespace:
    return argparse.Namespace(
        agent="codex",
        agents="codex",
        repo=args.repo,
        repo_map=args.repo_map,
        tasks=args.tasks,
        arms="A-search-only,D-full-router",
        repeats=args.repeats,
        task_limit=args.task_limit,
        timeout=args.timeout,
        out=str(benchmark_out),
        dry_run=False,
        live=True,
        allow_dirty=args.allow_dirty,
        snapshot_repos=args.snapshot_repos,
        seed=args.seed,
        no_randomize_order=False,
        monitor=args.monitor,
        stream_agent_output=args.stream_agent_output,
        terminal_mode=args.terminal_mode,
        skip_serena_readiness=False,
        serena_readiness_timeout=args.serena_readiness_timeout,
        require_clean_serena_process_state=True,
        static_code_prompts=False,
        resume_from=None,
        rerun_failed=False,
        clean_out=False,
        json=True,
    )


def run_codex_exact_paired_pilot(args: argparse.Namespace) -> tuple[int, dict[str, object]]:
    out = Path(args.out).expanduser().resolve()
    if args.clean_out:
        safe_clean_output_dir(out)
    out.mkdir(parents=True, exist_ok=True)
    if not Path(args.tasks).expanduser().exists():
        status = write_pilot_status(
            out,
            {
                "status": "failed",
                "phase": "doctor-preflight",
                "blockers": [f"task manifest does not exist: {args.tasks}"],
                "phase_order": PHASE_ORDER,
            },
        )
        return 2, status

    doctor_preflight_out = out / "doctor-preflight"
    doctor_preflight = run_doctor(
        agents=["codex"],
        repo=args.repo,
        out_root=doctor_preflight_out,
        timeout_seconds=args.doctor_timeout,
        terminal_mode=args.terminal_mode,
        run_probe=False,
        require_clean_serena_process_state=True,
    )
    preflight_warnings = doctor_preflight.get("serena_process_state_warnings")
    if isinstance(preflight_warnings, list) and preflight_warnings:
        cleanup_plan_path = out / "serena-cleanup-plan.json"
        cleanup_plan = serena_process_cleanup_plan(
            warnings=[str(item) for item in preflight_warnings],
            target_repo=cleanup_target_repo(args),
        )
        to_json_file(cleanup_plan_path, cleanup_plan)
        status = write_pilot_status(
            out,
            {
                "status": "blocked",
                "phase": "doctor-preflight",
                "blockers": split_blocker_messages(doctor_preflight.get("blockers")),
                "next_action": "clean stale Serena/Kotlin/JSON LSP sessions before running the full-router Codex cell",
                "doctor_summary": str((doctor_preflight_out / "adapter-doctor-summary.json").resolve()),
                "serena_cleanup_plan": str(cleanup_plan_path.resolve()),
                "serena_process_state": doctor_preflight.get("serena_process_state", {}),
                "serena_process_state_warnings": preflight_warnings,
                "stale_candidate_process_count": len(cleanup_plan.get("stale_candidate_processes", []) or []),
                "executable_candidate_process_count": cleanup_plan.get("executable_candidate_process_count", 0),
                "unsafe_candidate_process_count": cleanup_plan.get("unsafe_candidate_process_count", 0),
                "serena_cleanup_safe_to_execute": cleanup_plan.get("safe_to_execute", False),
                "serena_cleanup_status": cleanup_plan.get("cleanup_status", ""),
                "operator_required_action": cleanup_plan.get("operator_required_action", ""),
                "dry_run_cleanup_command": cleanup_plan.get("dry_run_cleanup_command", ""),
                "dry_run_table_command": cleanup_plan.get("dry_run_table_command", ""),
                "execute_cleanup_command": cleanup_plan.get("execute_cleanup_command", ""),
                "partial_safe_execute_command": cleanup_plan.get("partial_safe_execute_command", ""),
                "review_only_execute_command": cleanup_plan.get("review_only_execute_command", ""),
                "phase_order": PHASE_ORDER,
            },
        )
        return 2, status

    doctor_out = doctor_preflight_out
    doctor_summary = doctor_preflight
    if args.no_doctor_probe:
        status = write_pilot_status(
            out,
            {
                "status": "blocked",
                "phase": "doctor-probe",
                "blockers": ["doctor probe was skipped; live Codex readiness is not proven"],
                "next_action": "rerun without --no-doctor-probe when ready to launch the Codex readiness probe",
                "doctor_summary": str((doctor_preflight_out / "adapter-doctor-summary.json").resolve()),
                "serena_process_state": doctor_preflight.get("serena_process_state", {}),
                "serena_process_state_warnings": preflight_warnings or [],
                "phase_order": PHASE_ORDER,
            },
        )
        return 2, status

    doctor_out = out / "doctor-probe"
    doctor_summary = run_doctor(
        agents=["codex"],
        repo=args.repo,
        out_root=doctor_out,
        timeout_seconds=args.doctor_timeout,
        terminal_mode=args.terminal_mode,
        run_probe=True,
        require_clean_serena_process_state=True,
    )
    if doctor_summary.get("status") != "pass":
        status = write_pilot_status(
            out,
            {
                "status": "blocked",
                "phase": "doctor-probe",
                "blockers": split_blocker_messages(doctor_summary.get("blockers")),
                "next_action": "repair Codex live adapter readiness before running the paired benchmark",
                "doctor_summary": str((doctor_out / "adapter-doctor-summary.json").resolve()),
                "serena_process_state": doctor_summary.get("serena_process_state", {}),
                "serena_process_state_warnings": doctor_summary.get("serena_process_state_warnings", []),
                "phase_order": PHASE_ORDER,
            },
        )
        return 2, status

    benchmark_out = out / "benchmark"
    try:
        benchmark_result = run_benchmark(benchmark_args(args, benchmark_out=benchmark_out))
    except SystemExit as exc:
        status = write_pilot_status(
            out,
            {
                "status": "failed",
                "phase": "benchmark",
                "blockers": [str(exc)],
                "doctor_summary": str((doctor_out / "adapter-doctor-summary.json").resolve()),
                "benchmark_out": str(benchmark_out),
                "phase_order": PHASE_ORDER,
            },
        )
        return 2, status

    audit_out = out / "audit-codex-exact-paired.json"
    audit_result = strict_codex_paired_audit(benchmark_out=benchmark_out, doctor_out=doctor_out, audit_out=audit_out)
    if audit_result.get("status") != "pass":
        status = write_pilot_status(
            out,
            {
                "status": "failed",
                "phase": "audit",
                "blockers": audit_result.get("blockers", []),
                "doctor_summary": str((doctor_out / "adapter-doctor-summary.json").resolve()),
                "benchmark_out": str(benchmark_out),
                "audit_out": str(audit_out),
                "phase_order": PHASE_ORDER,
            },
        )
        return 2, status

    sanitized_out = Path(args.sanitized_out).expanduser().resolve() if args.sanitized_out else out / DEFAULT_SANITIZED_NAME
    export_summary = export_sanitized_live_pilot(
        benchmark_out=benchmark_out,
        out=sanitized_out,
        title="Codex Exact Paired RARB Pilot",
    )
    status = write_pilot_status(
        out,
        {
            "status": "pass",
            "phase": "export",
            "blockers": [],
            "doctor_summary": str((doctor_out / "adapter-doctor-summary.json").resolve()),
            "benchmark_out": str(benchmark_out),
            "audit_out": str(audit_out),
            "sanitized_out": str(sanitized_out),
            "benchmark_summary": benchmark_result.get("summary", {}),
            "export_summary": export_summary,
            "phase_order": PHASE_ORDER,
        },
    )
    return 0, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Codex-only exact paired RARB pilot: doctor clean Serena state, "
            "execute A-search-only vs D-full-router, audit the strict claim gate, "
            "and export a sanitized evidence bundle."
        )
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repo-map", required=True)
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--out", required=True)
    parser.add_argument("--sanitized-out")
    parser.add_argument("--task-limit", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--doctor-timeout", type=int, default=120)
    parser.add_argument("--serena-readiness-timeout", type=int, default=90)
    parser.add_argument("--terminal-mode", choices=["pty", "tmux", "subprocess", "codex-tui"])
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--snapshot-repos", action="store_true")
    parser.add_argument("--monitor", action="store_true")
    parser.add_argument("--stream-agent-output", action="store_true")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--clean-out", action="store_true")
    parser.add_argument(
        "--no-doctor-probe",
        action="store_true",
        help="Stop after non-launching clean-Serena and CLI metadata checks; useful for safe host status checks.",
    )
    args = parser.parse_args(argv)
    if args.task_limit < 1:
        raise SystemExit("--task-limit must be >= 1")
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    if args.timeout < 1 or args.doctor_timeout < 1 or args.serena_readiness_timeout < 1:
        raise SystemExit("--timeout, --doctor-timeout, and --serena-readiness-timeout must be >= 1")
    code, status = run_codex_exact_paired_pilot(args)
    print(json.dumps(status, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
