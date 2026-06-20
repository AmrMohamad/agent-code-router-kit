from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file, utc_now
from scripts.lib.serena_readiness import (
    SerenaProcess,
    serena_process_cleanup_plan,
    stale_processes_from_cleanup_plan,
    terminate_processes,
)

REVIEW_ONLY_APPROVAL_TOKEN = "TERMINATE_REVIEW_ONLY_SERENA_PROCESSES"

TABLE_COLUMNS = (
    ("pid", "PID", 7),
    ("kind", "process kind", 14),
    ("command", "command", 38),
    ("elapsed", "age", 12),
    ("parent_pid", "parent", 8),
    ("parent_command", "parent command", 30),
    ("project_guess", "project/cwd guess", 34),
    ("safe_to_terminate", "safe", 6),
    ("safety_exclusions", "exclusions", 26),
    ("kill_reason", "kill reason", 52),
)


def shorten(value: object, width: int) -> str:
    if isinstance(value, list):
        text = ",".join(str(item) for item in value)
    else:
        text = str(value if value is not None else "")
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: max(width - 1, 0)] + "…"


def format_repair_table(result: dict[str, object]) -> str:
    before = result.get("before")
    if not isinstance(before, dict):
        return "No cleanup plan available."
    rows = before.get("stale_candidate_processes")
    if not isinstance(rows, list) or not rows:
        return "No stale Serena/Kotlin/JSON LSP cleanup candidates."
    lines = [
        "Summary:",
        f"  cleanup_status: {before.get('cleanup_status', '')}",
        f"  safe_to_execute: {before.get('safe_to_execute', False)}",
        f"  executable_candidates: {before.get('executable_candidate_process_count', 0)}",
        f"  unsafe_candidates: {before.get('unsafe_candidate_process_count', 0)}",
        f"  operator_required_action: {before.get('operator_required_action', '')}",
        "",
        " | ".join(title.ljust(width) for _, title, width in TABLE_COLUMNS),
        " | ".join("-" * width for _, _, width in TABLE_COLUMNS),
    ]
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(
            " | ".join(shorten(row.get(key), width).ljust(width) for key, _, width in TABLE_COLUMNS)
        )
    lines.extend(
        [
            "",
            "Commands:",
            f"  dry-run : {before.get('dry_run_cleanup_command', '')}",
            f"  execute : {before.get('execute_cleanup_command', '')}",
            f"  partial: {before.get('partial_safe_execute_command', '')}",
            f"  review-only approved: {before.get('review_only_execute_command', '')}",
            "",
            "Execute refuses partial cleanup when unsafe candidates remain.",
            "Use the partial command only when intentionally cleaning safe candidates while review-only candidates remain.",
            "Use the review-only approved command only after explicit user approval for the listed review-only candidates.",
        ]
    )
    return "\n".join(lines)


def stale_candidate_processes_from_cleanup_plan(plan: dict[str, object], *, include_review_only: bool) -> list[SerenaProcess]:
    values = plan.get("stale_candidate_processes")
    if not isinstance(values, list):
        return []
    processes: list[SerenaProcess] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        if not include_review_only and item.get("safe_to_terminate") is not True:
            continue
        pid = item.get("pid")
        command = item.get("command")
        if isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(command, str):
            continue
        processes.append(SerenaProcess(pid=pid, command=command))
    return processes


def repair_serena_process_state(
    *,
    execute: bool,
    allow_partial_safe_execute: bool = False,
    approve_review_only_candidates: bool = False,
    approval_token: str = "",
    target_repo: str | None = None,
) -> dict[str, object]:
    before = serena_process_cleanup_plan(target_repo=target_repo)
    review_only_approval_accepted = bool(
        approve_review_only_candidates and approval_token == REVIEW_ONLY_APPROVAL_TOKEN
    )
    safe_processes = stale_processes_from_cleanup_plan(before)
    stale_processes = (
        stale_candidate_processes_from_cleanup_plan(before, include_review_only=True)
        if review_only_approval_accepted
        else safe_processes
    )
    stale_candidates = before.get("stale_candidate_processes")
    stale_candidate_count = len(stale_candidates) if isinstance(stale_candidates, list) else 0
    unsafe_candidate_count = max(stale_candidate_count - len(safe_processes), 0)
    terminated: list[dict[str, object]] = []
    after: dict[str, object] | None = None
    refused = bool(
        execute
        and unsafe_candidate_count
        and not allow_partial_safe_execute
        and not review_only_approval_accepted
    )
    no_safe_candidates = bool(execute and stale_candidate_count and not stale_processes)
    if execute and stale_processes and not refused:
        terminated = terminate_processes(stale_processes)
        after = serena_process_cleanup_plan(target_repo=target_repo)
    approval_missing_or_invalid = bool(execute and approve_review_only_candidates and not review_only_approval_accepted)
    if approval_missing_or_invalid:
        status = "refused_missing_review_only_approval"
    elif refused:
        status = "refused_partial_cleanup"
    elif no_safe_candidates:
        status = "blocked_no_safe_candidates"
    elif execute and review_only_approval_accepted:
        status = "executed_review_only_approved"
    elif execute:
        status = "executed"
    else:
        status = "dry_run"
    cleanup_status = str(before.get("cleanup_status") or "")
    if approval_missing_or_invalid:
        next_action = (
            f"review-only cleanup requires --approval-token {REVIEW_ONLY_APPROVAL_TOKEN} "
            "and explicit user approval"
        )
    elif refused and not stale_processes:
        next_action = (
            "no cleanup candidates are safe to terminate; close owning Codex/Serena/project sessions "
            "or get explicit approval for a broader cleanup"
        )
    elif refused:
        next_action = (
            "review unsafe candidates or rerun with --allow-partial-safe-execute if partial cleanup is intentional"
        )
    elif no_safe_candidates:
        next_action = (
            "no cleanup candidates are safe to terminate; close owning Codex/Serena/project sessions "
            "or get explicit approval for a broader cleanup"
        )
    elif execute:
        next_action = "rerun the Codex exact paired pilot"
    elif cleanup_status == "manual_review_required":
        next_action = (
            "no cleanup candidates are safe to terminate; close owning Codex/Serena/project sessions "
            "or get explicit approval for a broader cleanup"
        )
    else:
        next_action = "review stale candidates; rerun with --execute only after confirming they are safe to terminate"
    return {
        "created_at": utc_now(),
        "mode": "execute" if execute else "dry_run",
        "status": status,
        "cleanup_status": before.get("cleanup_status", ""),
        "safe_to_execute": before.get("safe_to_execute", False),
        "stale_candidate_process_count": stale_candidate_count,
        "executable_candidate_process_count": len(safe_processes),
        "selected_process_count": len(stale_processes),
        "unsafe_candidate_process_count": unsafe_candidate_count,
        "operator_required_action": before.get("operator_required_action", ""),
        "dry_run_cleanup_command": before.get("dry_run_cleanup_command", ""),
        "dry_run_table_command": before.get("dry_run_table_command", ""),
        "execute_cleanup_command": before.get("execute_cleanup_command", ""),
        "partial_safe_execute_command": before.get("partial_safe_execute_command", ""),
        "review_only_execute_command": before.get("review_only_execute_command", ""),
        "allow_partial_safe_execute": allow_partial_safe_execute,
        "approve_review_only_candidates": approve_review_only_candidates,
        "review_only_approval_accepted": review_only_approval_accepted,
        "target_repo": target_repo or "",
        "terminated_processes": terminated,
        "before": before,
        "after": after,
        "next_action": next_action,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Repair stale Serena/Kotlin/JSON LSP process state for RARB. "
            "Defaults to dry-run and does not terminate anything unless --execute is passed."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Inspect only. This is the default.")
    mode.add_argument("--execute", action="store_true", help="Terminate stale candidates from the cleanup plan.")
    parser.add_argument(
        "--allow-partial-safe-execute",
        action="store_true",
        help=(
            "With --execute, allow terminating safe candidates even when unsafe review-only "
            "candidates remain. Without this flag, execute refuses partial cleanup."
        ),
    )
    parser.add_argument(
        "--approve-review-only-candidates",
        action="store_true",
        help=(
            "With --execute, include review-only stale candidates after explicit user approval. "
            "Requires --approval-token TERMINATE_REVIEW_ONLY_SERENA_PROCESSES."
        ),
    )
    parser.add_argument("--approval-token", default="", help="Required token for --approve-review-only-candidates.")
    parser.add_argument("--out", help="Optional JSON output path.")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    parser.add_argument("--target-repo", help="Only mark processes safe when their cwd/project guess is under this repo.")
    args = parser.parse_args(argv)
    result = repair_serena_process_state(
        execute=args.execute,
        allow_partial_safe_execute=args.allow_partial_safe_execute,
        approve_review_only_candidates=args.approve_review_only_candidates,
        approval_token=args.approval_token,
        target_repo=args.target_repo,
    )
    if args.out:
        to_json_file(args.out, result)
    if args.format == "text":
        print(format_repair_table(result))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    if int(result["stale_candidate_process_count"] or 0) == 0:
        return 0
    if result["status"] in {
        "refused_partial_cleanup",
        "blocked_no_safe_candidates",
        "refused_missing_review_only_approval",
    }:
        return 2
    if args.execute and int(result["executable_candidate_process_count"] or 0) > 0:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
