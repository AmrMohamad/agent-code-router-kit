from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from dataclasses import asdict

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.probe_live_agent_adapters import probe_agent
from scripts.benchmarks.run_real_agent_benchmark import agent_path
from scripts.lib.agent_session import append_jsonl, load_agent_profile, to_json_file, utc_now
from scripts.lib.serena_readiness import serena_process_state, serena_process_state_warnings


NEXT_ACTIONS = {
    "": "ready",
    "adapter_supports_live_false": "enable or implement the live adapter before benchmark use",
    "command_not_found": "install the subject-agent CLI or fix the adapter command path",
    "authentication_failed": "authenticate or switch the CLI to an organization/model with access",
    "model_access_denied": "the CLI is authenticated but the selected organization has no Claude model access; switch organization/account or ask the administrator to grant access",
    "quota_exceeded": "wait for quota reset, increase quota, or use another authenticated account",
    "prompt_delivery_failed": "fix prompt delivery mode or adapter CLI flags",
    "adapter_flags_invalid": "update adapter CLI flags for the installed CLI version",
    "timeout": "increase timeout or inspect the captured transcript for an interactive prompt",
    "missing_contract": "inspect transcript; the adapter returned the sentinel without the benchmark contract",
    "missing_sentinel": "inspect transcript; the adapter did not return the benchmark contract",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|authorization)[=: ][^ \n]+")
UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


def classify_next_action(reason: str) -> str:
    return NEXT_ACTIONS.get(reason, "inspect transcript and adapter flags")


def first_present(*values: object) -> object | None:
    for value in values:
        if value is not None:
            return value
    return None


def row_has_non_proxy_token_totals(row: dict[str, object]) -> bool:
    token_source = str(row.get("probe_token_source") or row.get("token_source") or "")
    if token_source == "exact":
        return first_present(row.get("probe_exact_total_tokens"), row.get("exact_total_tokens")) is not None
    if token_source == "agent_reported":
        return first_present(
            row.get("probe_agent_reported_total_tokens"),
            row.get("agent_reported_total_tokens"),
        ) is not None
    return False


def command_candidates(agent_id: str) -> list[str]:
    profile = load_agent_profile(agent_path(agent_id))
    return [profile.command, *profile.fallback_commands]


def redact_diagnostic_text(value: str) -> str:
    value = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return UUID_RE.sub("[REDACTED_UUID]", value)


def run_metadata_command(command: list[str], *, timeout_seconds: int = 8) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = redact_diagnostic_text(completed.stdout.strip())
        stderr = redact_diagnostic_text(completed.stderr.strip())
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": stdout[:4000],
            "stderr": stderr[:4000],
        }
    except subprocess.TimeoutExpired:
        return {"command": command, "returncode": None, "stdout": "", "stderr": "timeout"}


def parse_claude_auth_status(command_result: dict[str, object]) -> dict[str, object]:
    stdout = str(command_result.get("stdout", ""))
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"raw": stdout[:1000]}
    return {
        key: payload.get(key)
        for key in ("loggedIn", "authMethod", "apiProvider", "subscriptionType")
        if key in payload
    }


def parse_cursor_about(command_result: dict[str, object]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for line in str(command_result.get("stdout", "")).splitlines():
        for label, key in (
            ("CLI Version", "version"),
            ("Model", "model"),
            ("Subscription Tier", "subscription_tier"),
            ("OS", "os"),
        ):
            if line.startswith(label):
                fields[key] = line[len(label):].strip()
    return fields


def cli_diagnostics(agent_id: str, resolved_command: str | None) -> dict[str, object]:
    if not resolved_command:
        return {}
    diagnostics: dict[str, object] = {}
    version = run_metadata_command([resolved_command, "--version"])
    diagnostics["version"] = version.get("stdout") or version.get("stderr")
    diagnostics["version_returncode"] = version.get("returncode")
    if agent_id == "claude-code":
        auth = run_metadata_command([resolved_command, "auth", "status"])
        diagnostics["auth_status"] = parse_claude_auth_status(auth)
        diagnostics["diagnostic_commands"] = {
            "auth_status": auth,
            "repair": "claude auth login or claude setup-token; verify org has Claude access",
        }
    elif agent_id == "cursor-agent":
        status = run_metadata_command([resolved_command, "status"])
        about = run_metadata_command([resolved_command, "about"])
        models = run_metadata_command([resolved_command, "models"])
        diagnostics["auth_status"] = {
            "logged_in": "logged in" in str(status.get("stdout", "")).lower(),
            "returncode": status.get("returncode"),
        }
        diagnostics["about"] = parse_cursor_about(about)
        diagnostics["model_list_available"] = models.get("returncode") == 0
        diagnostics["model_count"] = len([line for line in str(models.get("stdout", "")).splitlines() if " - " in line])
        diagnostics["diagnostic_commands"] = {
            "status": status,
            "about": about,
            "repair": "agent login, set CURSOR_API_KEY, choose an available model with --model, or ask admin to increase limits",
        }
    return diagnostics


def doctor_agent(
    *,
    agent_id: str,
    repo: str | Path,
    out_root: str | Path,
    timeout_seconds: int,
    terminal_mode: str | None,
    run_probe: bool,
    require_clean_serena_process_state: bool = False,
    serena_state: object | None = None,
    serena_warnings: list[str] | None = None,
) -> dict[str, object]:
    profile = load_agent_profile(agent_path(agent_id))
    candidates = [profile.command, *profile.fallback_commands]
    resolved = next((shutil.which(candidate) for candidate in candidates if shutil.which(candidate)), None)
    row: dict[str, object] = {
        "agent": profile.agent_id,
        "created_at": utc_now(),
        "supports_live": profile.supports_live,
        "terminal_mode": terminal_mode or profile.terminal_mode,
        "telemetry_sources": profile.telemetry_sources,
        "command_candidates": candidates,
        "resolved_command": resolved,
        "status": "fail",
        "reason": "",
        "ready_for_live_benchmark": False,
    }
    row["cli_diagnostics"] = cli_diagnostics(profile.agent_id, resolved)
    if not profile.supports_live:
        row["reason"] = "adapter_supports_live_false"
    elif not resolved:
        row["reason"] = "command_not_found"
    elif run_probe:
        probe = probe_agent(
            agent_id=agent_id,
            repo=repo,
            out_root=out_root,
            timeout_seconds=timeout_seconds,
            terminal_mode=terminal_mode,
        )
        row.update({f"probe_{key}": value for key, value in probe.items() if key not in {"agent", "created_at"}})
        row["status"] = str(probe.get("status", "fail"))
        row["reason"] = str(probe.get("reason", ""))
        row["ready_for_live_benchmark"] = row["status"] == "pass"
    else:
        row["status"] = "not_probed"
        row["reason"] = "probe_skipped"
    row["next_action"] = classify_next_action(str(row.get("reason", "")))
    weak_controls = row.get("probe_route_weak_controls", [])
    if isinstance(weak_controls, list) and weak_controls:
        row["ready_for_live_benchmark"] = False
        row["route_isolation_ready"] = False
        row["next_action"] = "fix weak route-isolation controls before benchmark use"
    else:
        row["route_isolation_ready"] = True
    row["token_telemetry_ready"] = row_has_non_proxy_token_totals(row)
    row["token_telemetry_next_action"] = (
        "ready"
        if row["token_telemetry_ready"]
        else "enable exact or agent-reported token telemetry before making real-token benchmark claims"
    )
    if require_clean_serena_process_state:
        state = serena_state or serena_process_state()
        warnings = serena_warnings if serena_warnings is not None else serena_process_state_warnings(state)  # type: ignore[arg-type]
        row["serena_process_state"] = asdict(state)  # type: ignore[arg-type]
        row["serena_process_state_warnings"] = warnings
        row["serena_process_state_ready"] = not warnings
        if warnings:
            row["ready_for_live_benchmark"] = False
            row["next_action"] = "clean stale Serena/Kotlin/JSON LSP sessions before full-router benchmark use"
    if row["status"] == "pass":
        row["ready_for_live_benchmark"] = bool(row.get("route_isolation_ready", True)) and bool(
            row.get("serena_process_state_ready", True)
        )
    return row


def run_doctor(
    *,
    agents: list[str],
    repo: str | Path,
    out_root: str | Path,
    timeout_seconds: int,
    terminal_mode: str | None,
    run_probe: bool,
    require_clean_serena_process_state: bool = False,
) -> dict[str, object]:
    out = Path(out_root).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    state = serena_process_state() if require_clean_serena_process_state else None
    warnings = serena_process_state_warnings(state) if state else []
    rows = [
        doctor_agent(
            agent_id=agent,
            repo=repo,
            out_root=out,
            timeout_seconds=timeout_seconds,
            terminal_mode=terminal_mode,
            run_probe=run_probe,
            require_clean_serena_process_state=require_clean_serena_process_state,
            serena_state=state,
            serena_warnings=warnings,
        )
        for agent in agents
    ]
    for row in rows:
        append_jsonl(out / "adapter-doctor.jsonl", row)
    blockers = [
        {
            "agent": row["agent"],
            "reason": row.get("reason", ""),
            "next_action": row.get("next_action", ""),
        }
        for row in rows
        if not row.get("ready_for_live_benchmark")
    ]
    summary = {
        "created_at": utc_now(),
        "out": str(out),
        "agents": len(rows),
        "ready": sum(1 for row in rows if row.get("ready_for_live_benchmark")),
        "blocked": len(blockers),
        "status": "pass" if not blockers else "fail",
        "require_clean_serena_process_state": require_clean_serena_process_state,
        "serena_process_state": asdict(state) if state else {},
        "serena_process_state_warnings": warnings,
        "blockers": blockers,
        "rows": rows,
    }
    to_json_file(out / "adapter-doctor-summary.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose live subject-agent adapter readiness for RARB.")
    parser.add_argument("--agents", default="codex,claude-code,cursor-agent")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--terminal-mode", choices=["pty", "tmux", "subprocess", "codex-tui"])
    parser.add_argument("--no-probe", action="store_true", help="Only check command/install metadata; do not launch agents.")
    parser.add_argument(
        "--require-clean-serena-process-state",
        action="store_true",
        help="Block readiness if multiple Serena MCP or language-server processes are already active.",
    )
    args = parser.parse_args(argv)
    summary = run_doctor(
        agents=[item.strip() for item in args.agents.split(",") if item.strip()],
        repo=args.repo,
        out_root=args.out,
        timeout_seconds=args.timeout,
        terminal_mode=args.terminal_mode,
        run_probe=not args.no_probe,
        require_clean_serena_process_state=args.require_clean_serena_process_state,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
