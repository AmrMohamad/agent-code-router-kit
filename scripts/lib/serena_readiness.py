from __future__ import annotations

import re
import shutil
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.lib.agent_session import to_json_file, utc_now


SOURCE_SYMBOL_RE = re.compile(r"\b[A-Z][A-Za-z0-9_]{3,}\b")
SOURCE_FILE_GLOBS = ["*.kt", "*.java", "*.swift", "*.ts", "*.tsx", "*.js", "*.jsx"]
SERENA_MCP_PATTERN = "serena start-mcp-server"
SOURCEKIT_LSP_PATTERN = "sourcekit-lsp"
KOTLIN_LSP_PATTERN = "KotlinLspServerKt"
JSON_LSP_PATTERN = "vscode-json-languageserver"
PROCESS_KIND_PATTERNS = {
    "serena_mcp": SERENA_MCP_PATTERN,
    "sourcekit_lsp": SOURCEKIT_LSP_PATTERN,
    "kotlin_lsp": KOTLIN_LSP_PATTERN,
    "json_lsp": JSON_LSP_PATTERN,
}
SAFETY_EXCLUSION_PATTERNS = (
    ("codex_process", re.compile(r"(?:^|/)codex(?:\s|$)", re.I)),
    ("android_studio_process", re.compile(r"Android Studio|studio\.app", re.I)),
    ("emulator_process", re.compile(r"\bemulator\b|qemu-system", re.I)),
    ("gradle_process", re.compile(r"\bgradle\b|GradleDaemon", re.I)),
    ("terminal_shell_process", re.compile(r"\b(?:zsh|bash|fish|sh)\b", re.I)),
)


@dataclass(frozen=True)
class SerenaProcessState:
    serena_mcp: int
    kotlin_lsp: int
    json_lsp: int
    sourcekit_lsp: int = 0


@dataclass(frozen=True)
class SerenaProcess:
    pid: int
    command: str


@dataclass(frozen=True)
class SerenaProcessInspection:
    pid: int
    parent_pid: int | None
    parent_command: str
    elapsed: str
    cwd: str
    project_guess: str


@dataclass(frozen=True)
class SerenaReadiness:
    status: str
    ready: bool
    created_at: str
    repo: str
    symbol: str
    source_file: str
    command: list[str]
    returncode: int | None
    stdout_tail: str
    stderr_tail: str
    process_state: SerenaProcessState
    warnings: list[str]
    reason: str
    next_action: str


def count_processes(pattern: str) -> int:
    completed = subprocess.run(
        ["ps", "ax", "-o", "command="],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return sum(1 for line in completed.stdout.splitlines() if pattern in line and "grep" not in line)


def matching_processes(pattern: str) -> list[SerenaProcess]:
    completed = subprocess.run(
        ["ps", "ax", "-o", "pid=,command="],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    processes: list[SerenaProcess] = []
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped or pattern not in stripped or "grep" in stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        if not pid_text.isdigit() or not command:
            continue
        processes.append(SerenaProcess(pid=int(pid_text), command=command.strip()))
    return processes


def serena_related_processes() -> list[SerenaProcess]:
    processes: list[SerenaProcess] = []
    for pattern in PROCESS_KIND_PATTERNS.values():
        processes.extend(matching_processes(pattern))
    by_pid = {process.pid: process for process in processes}
    return [by_pid[pid] for pid in sorted(by_pid)]


def serena_process_kind(command: str) -> str:
    for kind, pattern in PROCESS_KIND_PATTERNS.items():
        if pattern in command:
            return kind
    return "unknown"


def inspect_process(pid: int) -> SerenaProcessInspection:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "ppid=,etime=,command="],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    parent_pid: int | None = None
    elapsed = ""
    if completed.returncode == 0 and completed.stdout.strip():
        parts = completed.stdout.strip().split(None, 2)
        if parts and parts[0].isdigit():
            parent_pid = int(parts[0])
        if len(parts) > 1:
            elapsed = parts[1]
    parent_command = ""
    if parent_pid is not None:
        parent = subprocess.run(
            ["ps", "-p", str(parent_pid), "-o", "command="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if parent.returncode == 0:
            parent_command = parent.stdout.strip()
    cwd = process_cwd(pid)
    return SerenaProcessInspection(
        pid=pid,
        parent_pid=parent_pid,
        parent_command=parent_command,
        elapsed=elapsed,
        cwd=cwd,
        project_guess=project_guess_from_context(cwd=cwd, command=completed.stdout.strip()),
    )


def process_cwd(pid: int) -> str:
    completed = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    for line in completed.stdout.splitlines():
        if line.startswith("n") and len(line) > 1:
            return line[1:]
    return ""


def project_guess_from_context(*, cwd: str, command: str) -> str:
    if cwd:
        return cwd
    project_match = re.search(r"--project(?:=|\s+)(\S+)", command)
    if project_match:
        return project_match.group(1)
    if "--project-from-cwd" in command:
        return "project-from-cwd"
    return ""


def safety_exclusions(*, command: str, parent_command: str) -> list[str]:
    haystack = f"{command}\n{parent_command}"
    exclusions: list[str] = []
    for name, pattern in SAFETY_EXCLUSION_PATTERNS:
        if pattern.search(haystack):
            exclusions.append(name)
    return exclusions


def path_is_under(path_value: str, root_value: str) -> bool:
    if not path_value or not root_value:
        return False
    try:
        Path(path_value).expanduser().resolve().relative_to(Path(root_value).expanduser().resolve())
    except (OSError, ValueError):
        return False
    return True


def target_repo_exclusions(*, cwd: str, project_guess: str, target_repo: str | Path | None) -> list[str]:
    if target_repo is None:
        return []
    root = str(Path(target_repo).expanduser().resolve())
    if path_is_under(cwd, root) or path_is_under(project_guess, root):
        return []
    if cwd or project_guess:
        return ["outside_target_repo"]
    return ["unknown_project_context"]


def kill_reason_for_candidate(*, kind: str, stale_kinds: dict[str, bool], exclusions: list[str]) -> str:
    if kind not in PROCESS_KIND_PATTERNS:
        return "not a recognized Serena/Kotlin/JSON LSP process"
    if not stale_kinds.get(kind, False):
        return f"{kind} count is not stale"
    if exclusions:
        return "manual review required because safety exclusions matched: " + ",".join(exclusions)
    return f"stale {kind} process because more than one {kind} process is active before the benchmark"


def new_processes_since(before: list[SerenaProcess], after: list[SerenaProcess]) -> list[SerenaProcess]:
    before_pids = {process.pid for process in before}
    return [process for process in after if process.pid not in before_pids]


def terminate_processes(processes: list[SerenaProcess], *, grace_seconds: float = 1.0) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for process in processes:
        result: dict[str, object] = {"pid": process.pid, "command": process.command, "terminated": False}
        try:
            signal_name = "TERM"
            import os

            os.kill(process.pid, signal.SIGTERM)
            result["signal"] = signal_name
            result["terminated"] = True
        except ProcessLookupError:
            result["missing"] = True
        except PermissionError as exc:
            result["error"] = str(exc)
        results.append(result)
    if processes and grace_seconds > 0:
        time.sleep(grace_seconds)
    return results


def serena_process_state() -> SerenaProcessState:
    return SerenaProcessState(
        serena_mcp=count_processes(SERENA_MCP_PATTERN),
        sourcekit_lsp=count_processes(SOURCEKIT_LSP_PATTERN),
        kotlin_lsp=count_processes(KOTLIN_LSP_PATTERN),
        json_lsp=count_processes(JSON_LSP_PATTERN),
    )


def serena_process_state_warnings(process_state: SerenaProcessState) -> list[str]:
    warnings: list[str] = []
    if process_state.serena_mcp > 1:
        warnings.append("multiple_serena_mcp_processes")
    if process_state.sourcekit_lsp > 1:
        warnings.append("multiple_sourcekit_lsp_processes")
    if process_state.kotlin_lsp > 1:
        warnings.append("multiple_kotlin_lsp_processes")
    if process_state.json_lsp > 1:
        warnings.append("multiple_json_lsp_processes")
    return warnings


def serena_process_cleanup_plan(
    *,
    processes: list[SerenaProcess] | None = None,
    process_state: SerenaProcessState | None = None,
    warnings: list[str] | None = None,
    inspections: dict[int, SerenaProcessInspection] | None = None,
    target_repo: str | Path | None = None,
) -> dict[str, object]:
    state = process_state or serena_process_state()
    warning_values = warnings if warnings is not None else serena_process_state_warnings(state)
    process_values = processes if processes is not None else serena_related_processes()
    grouped: dict[str, list[SerenaProcess]] = {
        "serena_mcp": [],
        "sourcekit_lsp": [],
        "kotlin_lsp": [],
        "json_lsp": [],
        "unknown": [],
    }
    for process in process_values:
        grouped.setdefault(serena_process_kind(process.command), []).append(process)
    stale_kinds = {
        "serena_mcp": state.serena_mcp > 1,
        "sourcekit_lsp": state.sourcekit_lsp > 1,
        "kotlin_lsp": state.kotlin_lsp > 1,
        "json_lsp": state.json_lsp > 1,
    }
    target_arg = f" --target-repo {Path(target_repo).expanduser().resolve()}" if target_repo is not None else ""
    process_rows: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    inspection_values = inspections or {}
    for process in process_values:
        kind = serena_process_kind(process.command)
        inspection = inspection_values.get(process.pid) or inspect_process(process.pid)
        exclusions = safety_exclusions(command=process.command, parent_command=inspection.parent_command)
        exclusions.extend(
            item
            for item in target_repo_exclusions(
                cwd=inspection.cwd,
                project_guess=inspection.project_guess,
                target_repo=target_repo,
            )
            if item not in exclusions
        )
        row = {
            "kind": kind,
            "pid": process.pid,
            "command": process.command,
            "parent_pid": inspection.parent_pid,
            "parent_command": inspection.parent_command,
            "elapsed": inspection.elapsed,
            "cwd": inspection.cwd,
            "project_guess": inspection.project_guess,
            "target_repo": str(Path(target_repo).expanduser().resolve()) if target_repo is not None else "",
            "safety_exclusions": exclusions,
            "kill_reason": kill_reason_for_candidate(kind=kind, stale_kinds=stale_kinds, exclusions=exclusions),
            "safe_to_terminate": kind in PROCESS_KIND_PATTERNS and stale_kinds.get(kind, False) and not exclusions,
        }
        process_rows.append(row)
    unsafe_pids = {
        int(row["pid"])
        for row in process_rows
        if row.get("safe_to_terminate") is False and row.get("pid") is not None
    }
    for row in process_rows:
        parent_pid = row.get("parent_pid")
        if isinstance(parent_pid, int) and parent_pid in unsafe_pids:
            exclusions = list(row.get("safety_exclusions", []) or [])
            if "parent_process_not_safe" not in exclusions:
                exclusions.append("parent_process_not_safe")
            row["safety_exclusions"] = exclusions
            row["safe_to_terminate"] = False
            row["kill_reason"] = "manual review required because parent process is not safe to terminate"
    candidates = [
        {
            **row,
            "termination_command": f"kill -TERM {row['pid']}",
        }
        for row in process_rows
        if stale_kinds.get(str(row.get("kind")), False)
    ]
    executable_candidates = [candidate for candidate in candidates if candidate.get("safe_to_terminate") is True]
    unsafe_candidates = [candidate for candidate in candidates if candidate.get("safe_to_terminate") is not True]
    safe_to_execute = bool(candidates) and not unsafe_candidates
    if not candidates:
        cleanup_status = "clean"
        operator_required_action = "none"
        recommended_actions = ["No stale Serena/Kotlin/JSON LSP process state detected."]
    elif safe_to_execute:
        cleanup_status = "safe_execute_available"
        operator_required_action = "review candidate table, then run execute cleanup after confirming no active user session is listed"
        recommended_actions = [
            "Review stale_candidate_processes and confirm they are not active user sessions.",
            "Terminate only stale candidates, then rerun the Codex exact paired pilot.",
        ]
    elif executable_candidates:
        cleanup_status = "partial_safe_execute_available"
        operator_required_action = "review unsafe candidates; partial safe cleanup is possible but will not make the benchmark clean"
        recommended_actions = [
            "Review unsafe stale_candidate_processes and identify the owning app/session.",
            "Use partial safe execute only if intentionally cleaning safe candidates while leaving review-only candidates blocked.",
            "Do not run the paired benchmark until unsafe stale candidates are resolved.",
        ]
    else:
        cleanup_status = "manual_review_required"
        operator_required_action = "close or explicitly approve the owning app/session for every review-only candidate; default repair cannot execute"
        recommended_actions = [
            "Close the owning Codex/Serena/project sessions or get explicit approval for a broader process cleanup.",
            "Rerun the dry-run cleanup table after the owner sessions are closed.",
            "Do not run the paired benchmark while only review-only candidates remain.",
        ]
    return {
        "created_at": utc_now(),
        "status": "blocked" if warning_values else "clean",
        "process_state": asdict(state),
        "target_repo": str(Path(target_repo).expanduser().resolve()) if target_repo is not None else "",
        "warnings": warning_values,
        "processes": process_rows,
        "stale_candidate_processes": candidates,
        "executable_candidate_process_count": len(executable_candidates),
        "unsafe_candidate_process_count": len(unsafe_candidates),
        "safe_to_execute": safe_to_execute,
        "manual_review_required": bool(candidates),
        "unsafe_manual_review_required": bool(unsafe_candidates),
        "cleanup_status": cleanup_status,
        "operator_required_action": operator_required_action,
        "recommended_actions": recommended_actions,
        "inspection_command": "ps ax -o pid=,command= | egrep 'serena start-mcp-server|KotlinLspServerKt|vscode-json-languageserver'",
        "dry_run_cleanup_command": f"python3 scripts/benchmarks/repair_serena_process_state.py --dry-run{target_arg} --out /tmp/serena-process-repair.json",
        "dry_run_table_command": f"python3 scripts/benchmarks/repair_serena_process_state.py --dry-run --format text{target_arg} --out /tmp/serena-process-repair.json",
        "execute_cleanup_command": f"python3 scripts/benchmarks/repair_serena_process_state.py --execute{target_arg} --out /tmp/serena-process-repair.json",
        "partial_safe_execute_command": f"python3 scripts/benchmarks/repair_serena_process_state.py --execute --allow-partial-safe-execute{target_arg} --out /tmp/serena-process-repair.json",
        "review_only_execute_command": (
            "python3 scripts/benchmarks/repair_serena_process_state.py --execute "
            "--approve-review-only-candidates --approval-token TERMINATE_REVIEW_ONLY_SERENA_PROCESSES"
            f"{target_arg} --out /tmp/serena-process-repair.json"
        ),
    }


def stale_processes_from_cleanup_plan(plan: dict[str, object]) -> list[SerenaProcess]:
    values = plan.get("stale_candidate_processes")
    if not isinstance(values, list):
        return []
    processes: list[SerenaProcess] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        if item.get("safe_to_terminate") is not True:
            continue
        pid = item.get("pid")
        command = item.get("command")
        if isinstance(pid, bool) or not isinstance(pid, int) or not isinstance(command, str):
            continue
        processes.append(SerenaProcess(pid=pid, command=command))
    return processes


def extract_source_symbol(prompt: str) -> str:
    candidates = SOURCE_SYMBOL_RE.findall(prompt)
    ignored = {
        "Find",
        "Determine",
        "Report",
        "Evidence",
        "Serena",
        "Kotlin",
        "Java",
        "Android",
        "Swift",
        "SourceKit",
        "TypeScript",
        "JavaScript",
        "React",
        "Web",
    }
    for candidate in candidates:
        if candidate not in ignored:
            return candidate
    return ""


def candidate_source_files(repo: str | Path, symbol: str, *, limit: int = 20) -> list[str]:
    if not symbol:
        return []
    repo_path = Path(repo).expanduser().resolve()
    pattern = rf"\b{re.escape(symbol)}\b"
    command = ["rg", "--no-config", "-l"]
    for glob in SOURCE_FILE_GLOBS:
        command.extend(["-g", glob])
    command.extend([pattern, "."])
    completed = subprocess.run(
        command,
        cwd=repo_path,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    files = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not files:
        return []
    expected_basenames = {
        f"{symbol}.kt",
        f"{symbol}.java",
        f"{symbol}.swift",
        f"{symbol}.ts",
        f"{symbol}.tsx",
        f"{symbol}.js",
        f"{symbol}.jsx",
    }
    files.sort(key=lambda value: (Path(value).name not in expected_basenames, len(Path(value).parts), value))
    return files[:limit]


def classify_index_output(*, symbol: str, source_file: str, returncode: int | None, stdout: str, stderr: str) -> tuple[str, bool, str, str]:
    combined = f"{stdout}\n{stderr}"
    if returncode is None:
        return "fail", False, "timeout", "increase Serena readiness timeout and inspect language-server logs"
    if returncode != 0:
        if "language server manager is not initialized" in combined:
            return "fail", False, "language_server_manager_not_initialized", "restart stale Serena sessions and warm the project language server before full-router runs"
        if "cancelled (-32800)" in combined:
            return "fail", False, "language_server_initialization_cancelled", "restart stale Serena/LSP sessions and retry source-symbol smoke"
        return "fail", False, "serena_index_file_failed", "inspect serena project index-file output and project configuration"
    symbol_line = re.compile(rf"^\s*-\s+{re.escape(symbol)}\s+at line\s+\d+\s+of kind\s+\d+\s*$", re.MULTILINE)
    if source_file and symbol_line.search(stdout):
        return "pass", True, "", "ready"
    return "fail", False, "symbol_not_seen_in_index_output", "choose a real source declaration file and rerun Serena source-symbol smoke"


def run_serena_source_symbol_readiness(
    *,
    repo: str | Path,
    prompt: str,
    source_symbol: str | None = None,
    source_file: str | None = None,
    timeout_seconds: int = 90,
) -> SerenaReadiness:
    repo_path = Path(repo).expanduser().resolve()
    process_state = serena_process_state()
    warnings = serena_process_state_warnings(process_state)

    symbol = source_symbol or extract_source_symbol(prompt)
    if not shutil.which("serena"):
        return SerenaReadiness(
            status="fail",
            ready=False,
            created_at=utc_now(),
            repo=str(repo_path),
            symbol=symbol,
            source_file=source_file or "",
            command=["serena"],
            returncode=None,
            stdout_tail="",
            stderr_tail="",
            process_state=process_state,
            warnings=warnings,
            reason="serena_not_found",
            next_action="install Serena or fix PATH before full-router semantic runs",
        )
    selected_file = source_file or ""
    if not selected_file:
        candidates = candidate_source_files(repo_path, symbol)
        selected_file = candidates[0] if candidates else ""
    if not symbol or not selected_file:
        return SerenaReadiness(
            status="fail",
            ready=False,
            created_at=utc_now(),
            repo=str(repo_path),
            symbol=symbol,
            source_file=selected_file,
            command=["serena", "project", "index-file"],
            returncode=None,
            stdout_tail="",
            stderr_tail="",
            process_state=process_state,
            warnings=warnings,
            reason="source_symbol_or_file_not_resolved",
            next_action="provide a known source symbol/file in a supported source file for Serena readiness smoke",
        )
    command = ["serena", "project", "index-file", selected_file, str(repo_path), "--verbose"]
    try:
        completed = subprocess.run(
            command,
            cwd=repo_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        status, ready, reason, next_action = classify_index_output(
            symbol=symbol,
            source_file=selected_file,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        return SerenaReadiness(
            status=status,
            ready=ready,
            created_at=utc_now(),
            repo=str(repo_path),
            symbol=symbol,
            source_file=selected_file,
            command=command,
            returncode=completed.returncode,
            stdout_tail=completed.stdout[-4000:],
            stderr_tail=completed.stderr[-4000:],
            process_state=process_state,
            warnings=warnings,
            reason=reason,
            next_action=next_action,
        )
    except subprocess.TimeoutExpired as exc:
        return SerenaReadiness(
            status="fail",
            ready=False,
            created_at=utc_now(),
            repo=str(repo_path),
            symbol=symbol,
            source_file=selected_file,
            command=command,
            returncode=None,
            stdout_tail=(exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            stderr_tail=(exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            process_state=process_state,
            warnings=warnings,
            reason="timeout",
            next_action="increase readiness timeout or inspect Kotlin LSP startup logs",
        )


def write_serena_readiness(path: str | Path, readiness: SerenaReadiness) -> None:
    to_json_file(path, asdict(readiness))
