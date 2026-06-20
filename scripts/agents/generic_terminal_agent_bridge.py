from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import pty
import select
import shlex
import shutil
import struct
import subprocess
import sys
import termios
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import AgentProfile, LaunchPlan, append_jsonl, load_agent_profile, to_json_file, utc_now
from scripts.lib.serena_readiness import new_processes_since, serena_related_processes, terminate_processes
from scripts.lib.token_proxy import byte_count, normalize_token_fields
from scripts.lib.transcript_parser import (
    classify_failure_reason,
    count_tool_mentions,
    count_tools_from_events,
    extract_token_usage,
    has_done_sentinel,
    observed_tool_output_bytes,
    observed_tool_events,
    parse_benchmark_response,
    redact_secrets,
    tool_output_bytes,
)


DEFAULT_SENTINEL = "BENCHMARK_DONE"
TMUX_CAPTURE_HISTORY_LINES = "50000"
CODEX_TUI_BRIDGE = Path(__file__).with_name("codex_tui_terminal_bridge.py")


@dataclass(frozen=True)
class BridgeRunResult:
    run_id: str
    completion_reason: str
    wall_seconds: float
    transcript_path: str
    telemetry_path: str
    metrics_path: str
    final_answer_path: str


class OutputBudgetExceeded(Exception):
    def __init__(self, output: str) -> None:
        super().__init__("live agent output budget exceeded")
        self.output = output


def _shorten_one_line(value: object, *, max_chars: int = 180) -> str:
    text = str(value or "").replace("\n", "\\n")
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1]}…"


def format_stream_delta_for_operator(text: str) -> str:
    """Render agent JSONL streams as operator-readable progress.

    Raw provider streams stay in transcript artifacts. The terminal stream is
    for humans watching the run, so large nested payloads are summarized.
    """
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            lines.append(raw_line)
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            lines.append(f"    codex thread started {_shorten_one_line(event.get('thread_id'), max_chars=80)}")
            continue
        if event_type == "turn.started":
            lines.append("    codex turn started")
            continue
        if event_type == "turn.completed":
            usage = event.get("usage") or {}
            token_bits = []
            for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
                if usage.get(key) is not None:
                    token_bits.append(f"{key}={usage.get(key)}")
            lines.append("    codex turn completed" + (f" ({', '.join(token_bits)})" if token_bits else ""))
            continue
        if event_type in {"item.started", "item.completed"}:
            item = event.get("item") or {}
            item_type = item.get("type")
            state = "started" if event_type == "item.started" else "completed"
            if item_type == "command_execution":
                command = _shorten_one_line(item.get("command"))
                if state == "completed":
                    output_bytes = byte_count(str(item.get("aggregated_output") or ""))
                    lines.append(
                        f"    command completed exit={item.get('exit_code')} output_bytes={output_bytes}: {command}"
                    )
                else:
                    lines.append(f"    command started: {command}")
                continue
            if item_type == "mcp_tool_call":
                tool_name = f"{item.get('server', 'mcp')}.{item.get('tool', 'tool')}"
                if state == "completed":
                    result_bytes = byte_count(json.dumps(item.get("result") or {}, sort_keys=True))
                    error = item.get("error")
                    suffix = f" error={_shorten_one_line(error)}" if error else f" result_bytes={result_bytes}"
                    lines.append(f"    MCP completed {tool_name}{suffix}")
                else:
                    lines.append(f"    MCP started {tool_name}")
                continue
            if item_type == "agent_message":
                message = _shorten_one_line(item.get("text"), max_chars=240)
                if "BENCHMARK_RESULT" in str(item.get("text") or ""):
                    parsed = parse_benchmark_response(str(item.get("text") or ""))
                    status = parsed.status or "unknown"
                    final_answer = _shorten_one_line(parsed.final_answer, max_chars=240)
                    lines.append(f"    benchmark result {status}: {final_answer}")
                elif message:
                    lines.append(f"    assistant: {message}")
                continue
            lines.append(f"    {item_type or 'item'} {state}")
            continue
        lines.append(_shorten_one_line(line))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def resolve_agent_command(profile: AgentProfile) -> str:
    candidates = [profile.command, *profile.fallback_commands]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return profile.command


def budget_relevant_output_bytes(text: str, *, fallback_to_raw: bool) -> int:
    parsed_output_bytes = tool_output_bytes(text, fallback_to_transcript=fallback_to_raw)
    if parsed_output_bytes:
        return parsed_output_bytes
    return byte_count(text) if fallback_to_raw else 0


def parseable_benchmark_answer_delta(text: str, *, sentinel: str) -> str:
    if "BENCHMARK_RESULT" not in text or sentinel not in text:
        return text
    start = text.rfind("BENCHMARK_RESULT")
    end = text.find(sentinel, start)
    if start == -1 or end == -1:
        return text
    return text[start : end + len(sentinel)].strip()


def build_launch_plan(
    profile: AgentProfile,
    *,
    cwd: str,
    command: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    terminal_mode: str | None = None,
) -> LaunchPlan:
    return LaunchPlan(
        agent_id=profile.agent_id,
        command=[command or resolve_agent_command(profile), *(args if args is not None else profile.args)],
        cwd=cwd,
        prompt_mode=profile.prompt_mode,
        telemetry_sources=profile.telemetry_sources,
        supports_live=profile.supports_live,
        terminal_mode=terminal_mode or profile.terminal_mode,
        env=env or profile.env,
    )


def fake_agent_response(*, agent_id: str, profile_id: str, task_id: str, sentinel: str) -> str:
    return f"""BENCHMARK_RESULT
status: pass
confidence: medium

tools_used:
  - dry-run-adapter
  - {profile_id}

proof_layers:
  semantic_identity: dry-run placeholder
  references: dry-run placeholder
  runtime: not run

files_opened:
  count: 0
  paths:

raw_dump_incidents:
  count: 0

policy_adherence: pass

final_answer:
  Dry run completed.
  Evidence:
  - agent: {agent_id}
  - task: {task_id}
  - profile: {profile_id}
  - live subject agent launched: no

{sentinel}
"""


class TerminalAgentBridge:
    def __init__(
        self,
        profile: AgentProfile,
        *,
        cwd: str,
        dry_run: bool = True,
        stream_agent_output: bool = False,
        monitor_live_events: bool = False,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        terminal_mode: str | None = None,
    ) -> None:
        self.profile = profile
        self.cwd = cwd
        self.dry_run = dry_run
        self.stream_agent_output = stream_agent_output
        self.monitor_live_events = monitor_live_events
        self._monitor_buckets: dict[tuple[str, str], int] = {}
        self.command = command or resolve_agent_command(profile)
        self.args = args if args is not None else list(profile.args)
        self.env = env or dict(profile.env)
        self.terminal_mode = terminal_mode or profile.terminal_mode

    def _stream_to_operator(self, text: str) -> None:
        if not self.stream_agent_output or not text:
            return
        rendered = format_stream_delta_for_operator(text)
        if rendered:
            print(rendered, end="", flush=True)

    def _live_budget_bytes(self, text: str) -> int:
        if self.profile.agent_id == "codex":
            return observed_tool_output_bytes(text)
        return budget_relevant_output_bytes(text, fallback_to_raw=self.profile.agent_id != "codex")

    def launch_plan(self) -> LaunchPlan:
        return build_launch_plan(
            self.profile,
            cwd=self.cwd,
            command=self.command,
            args=self.args,
            env=self.env,
            terminal_mode=self.terminal_mode,
        )

    def _append_live_event(
        self,
        telemetry_path: str | Path,
        *,
        run_id: str,
        event: str,
        **fields: object,
    ) -> None:
        append_jsonl(
            telemetry_path,
            {
                "event": event,
                "created_at": utc_now(),
                "run_id": run_id,
                "agent": self.profile.agent_id,
                "terminal_mode": self.terminal_mode,
                **fields,
            },
        )
        self._print_live_monitor_event(run_id=run_id, event=event, **fields)

    def _print_live_monitor_event(self, *, run_id: str, event: str, **fields: object) -> None:
        if not self.monitor_live_events:
            return
        prefix = f"  - live {self.profile.agent_id} {event}"
        if event == "process_spawned":
            print(f"{prefix} pid={fields.get('pid', '')}", flush=True)
        elif event == "tmux_session_started":
            print(f"{prefix} session={fields.get('session', '')}", flush=True)
        elif event == "prompt_sent":
            print(
                f"{prefix} bytes={fields.get('prompt_bytes', 0)} transport={fields.get('prompt_transport', '')}",
                flush=True,
            )
        elif event in {"process_exited", "tmux_session_closed", "sentinel_observed", "terminal_prompt_observed", "tmux_pane_dead"}:
            detail = ""
            if fields.get("returncode") is not None:
                detail = f" returncode={fields.get('returncode')}"
            elif fields.get("session"):
                detail = f" session={fields.get('session')}"
            print(f"{prefix}{detail}", flush=True)
        elif event == "process_timeout":
            print(
                f"{prefix} timeout_seconds={fields.get('timeout_seconds', 0)} observed_bytes={fields.get('observed_bytes', 0)}",
                flush=True,
            )
        elif event in {"process_output_chunk", "terminal_capture_changed"}:
            observed = int(fields.get("observed_bytes") or fields.get("capture_bytes") or 0)
            bucket = observed // 4096
            key = (run_id, event)
            if bucket <= self._monitor_buckets.get(key, -1):
                return
            self._monitor_buckets[key] = bucket
            label = "observed_bytes" if event == "process_output_chunk" else "capture_bytes"
            print(f"{prefix} {label}={observed}", flush=True)

    def run_prompt(
        self,
        *,
        run_id: str,
        prompt: str,
        out_dir: str | Path,
        timeout_seconds: int,
        sentinel: str = DEFAULT_SENTINEL,
        profile_id: str,
        task_id: str,
        max_output_bytes: int | None = None,
    ) -> BridgeRunResult:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        transcript_path = out / "transcript.txt"
        telemetry_path = out / "telemetry.jsonl"
        metrics_path = out / "metrics.normalized.json"
        final_answer_path = out / "agent_final_answer.md"
        started = time.monotonic()
        completion_reason = "dry_run"
        if self.dry_run:
            response = fake_agent_response(
                agent_id=self.profile.agent_id,
                profile_id=profile_id,
                task_id=task_id,
                sentinel=sentinel,
            )
        else:
            if not self.profile.supports_live:
                raise RuntimeError(f"agent {self.profile.agent_id} does not support live execution yet")
            append_jsonl(
                telemetry_path,
                {
                    "event": "process_started",
                    "created_at": utc_now(),
                    "run_id": run_id,
                    "agent": self.profile.agent_id,
                    "command": [self.command, *self.args],
                    "terminal_mode": self.terminal_mode,
                    "prompt_mode": self.profile.prompt_mode,
                    "cwd": self.cwd,
                },
            )
            try:
                response = self._run_live(
                    prompt,
                    timeout_seconds=timeout_seconds,
                    sentinel=sentinel,
                    telemetry_path=telemetry_path,
                    run_id=run_id,
                    max_output_bytes=max_output_bytes,
                )
                completion_reason = "sentinel" if has_done_sentinel(response, sentinel) else "missing_sentinel"
            except subprocess.TimeoutExpired as exc:
                response = (exc.output or "") if isinstance(exc.output, str) else ""
                completion_reason = "timeout"
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="process_timeout",
                    timeout_seconds=timeout_seconds,
                    observed_bytes=byte_count(response),
                )
            except OutputBudgetExceeded as exc:
                response = exc.output
                completion_reason = "output_budget_exceeded"
        wall_seconds = round(time.monotonic() - started, 6)
        redacted = redact_secrets(response)
        transcript_path.write_text(redacted, encoding="utf-8")
        parsed = parse_benchmark_response(redacted, sentinel=sentinel)
        final_answer_path.write_text(parsed.final_answer + "\n", encoding="utf-8")
        tool_counts = count_tool_mentions(redacted)
        observed_events = observed_tool_events(redacted)
        observed_tools = [event["tool"] for event in observed_events]
        observed_task_events = [event for event in observed_events if event.get("phase") != "bootstrap_context"]
        observed_task_tools = [event["tool"] for event in observed_task_events]
        tool_counts = count_tools_from_events(observed_task_events) if observed_task_events else tool_counts
        output_bytes = tool_output_bytes(redacted, fallback_to_transcript=not self.dry_run)
        total_observed_output_bytes = observed_tool_output_bytes(redacted, include_bootstrap=True)
        bootstrap_output_bytes = max(total_observed_output_bytes - observed_tool_output_bytes(redacted), 0)
        token_usage = extract_token_usage(redacted)
        token_metrics = normalize_token_fields(
            prompt_bytes=byte_count(prompt),
            answer_bytes=byte_count(parsed.final_answer),
            transcript_bytes=byte_count(redacted),
            tool_output_bytes=output_bytes,
            exact_tokens=token_usage.get("exact"),  # type: ignore[arg-type]
            agent_reported_tokens=token_usage.get("agent_reported"),  # type: ignore[arg-type]
        )
        metrics = {
            "run_id": run_id,
            "agent": self.profile.agent_id,
            "completion_reason": completion_reason,
            "failure_reason": classify_failure_reason(redacted),
            "wall_seconds": wall_seconds,
            "done": parsed.done,
            "contract_present": parsed.contract_present,
            "status": parsed.status,
            "policy_adherence": parsed.policy_adherence,
            "tool_call_count": len(parsed.tools_used),
            "files_opened_count": len(parsed.files_opened),
            "raw_dump_incidents": parsed.raw_dump_incidents,
            "raw_output_bytes": output_bytes,
            "raw_task_output_bytes": output_bytes,
            "raw_bootstrap_output_bytes": bootstrap_output_bytes,
            "raw_total_observed_output_bytes": total_observed_output_bytes,
            "observed_tool_events": observed_events,
            "observed_tools": observed_tools,
            "observed_task_tools": observed_task_tools,
            "tool_evidence_source": "observed" if observed_task_tools else "self_report" if parsed.tools_used else "missing",
            **tool_counts,
            **token_metrics,
        }
        to_json_file(metrics_path, metrics)
        append_jsonl(
            telemetry_path,
            {
                "event": "run_completed",
                "created_at": utc_now(),
                "run_id": run_id,
                "agent": self.profile.agent_id,
                "dry_run": self.dry_run,
                "completion_reason": completion_reason,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "transcript_sha256": hashlib.sha256(redacted.encode("utf-8")).hexdigest(),
                "observed_tool_event_count": len(observed_events),
            },
        )
        return BridgeRunResult(
            run_id=run_id,
            completion_reason=completion_reason,
            wall_seconds=wall_seconds,
            transcript_path=str(transcript_path),
            telemetry_path=str(telemetry_path),
            metrics_path=str(metrics_path),
            final_answer_path=str(final_answer_path),
        )

    def _command_with_prompt_argument(self, prompt: str) -> list[str]:
        command = [self.command, *self.args]
        variadic_options = {
            "--add-dir",
            "--allowedTools",
            "--allowed-tools",
            "--disallowedTools",
            "--disallowed-tools",
            "--file",
            "--mcp-config",
            "--plugin-dir",
            "--tools",
        }
        insert_at = next((index for index, arg in enumerate(command) if arg in variadic_options), len(command))
        return [*command[:insert_at], prompt, *command[insert_at:]]

    def _run_live(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        sentinel: str,
        telemetry_path: str | Path,
        run_id: str,
        max_output_bytes: int | None = None,
    ) -> str:
        if self.terminal_mode == "pty":
            return self._run_live_pty(
                prompt,
                timeout_seconds=timeout_seconds,
                telemetry_path=telemetry_path,
                run_id=run_id,
                max_output_bytes=max_output_bytes,
            )
        if self.terminal_mode == "tmux":
            return self._run_live_tmux(
                prompt,
                timeout_seconds=timeout_seconds,
                sentinel=sentinel,
                telemetry_path=telemetry_path,
                run_id=run_id,
                max_output_bytes=max_output_bytes,
            )
        if self.terminal_mode == "codex-tui":
            return self._run_live_codex_tui(
                prompt,
                timeout_seconds=timeout_seconds,
                sentinel=sentinel,
                telemetry_path=telemetry_path,
                run_id=run_id,
                max_output_bytes=max_output_bytes,
            )
        command = [self.command, *self.args]
        stdin_input = prompt
        if self.profile.prompt_mode == "argument":
            command = self._command_with_prompt_argument(prompt)
            stdin_input = ""
        if not self.stream_agent_output:
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="prompt_sent",
                prompt_bytes=byte_count(prompt if self.profile.prompt_mode == "argument" else stdin_input),
                prompt_transport=self.profile.prompt_mode,
            )
            completed = subprocess.run(
                command,
                input=stdin_input,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                timeout=timeout_seconds,
                check=False,
                env={**os.environ, **self.env},
            )
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="process_exited",
                returncode=completed.returncode,
                stdout_bytes=byte_count(completed.stdout),
                stderr_bytes=byte_count(completed.stderr),
            )
            output = completed.stdout + ("\nSTDERR:\n" + completed.stderr if completed.stderr else "")
            budget_bytes = self._live_budget_bytes(output)
            if max_output_bytes is not None and budget_bytes > max_output_bytes:
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="output_budget_exceeded",
                    observed_bytes=budget_bytes,
                    raw_stdout_bytes=byte_count(output),
                    max_output_bytes=max_output_bytes,
                )
                raise OutputBudgetExceeded(output)
            return output
        process = subprocess.Popen(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
            cwd=self.cwd,
            env={**os.environ, **self.env},
        )
        self._append_live_event(telemetry_path, run_id=run_id, event="process_spawned", pid=process.pid)
        assert process.stdin is not None
        assert process.stdout is not None
        process.stdin.write(stdin_input)
        process.stdin.close()
        self._append_live_event(
            telemetry_path,
            run_id=run_id,
            event="prompt_sent",
            prompt_bytes=byte_count(stdin_input),
            prompt_transport=self.profile.prompt_mode,
        )
        chunks: list[str] = []
        started = time.monotonic()
        observed_bytes = 0
        while True:
            if time.monotonic() - started > timeout_seconds:
                process.kill()
                raise subprocess.TimeoutExpired(command, timeout_seconds, output="".join(chunks))
            line = process.stdout.readline()
            if line:
                chunks.append(line)
                observed_bytes += byte_count(line)
                current_output = "".join(chunks)
                budget_bytes = self._live_budget_bytes(current_output)
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="process_output_chunk",
                    chunk_bytes=byte_count(line),
                    observed_bytes=observed_bytes,
                    budget_bytes=budget_bytes,
                )
                if max_output_bytes is not None and budget_bytes > max_output_bytes:
                    self._append_live_event(
                        telemetry_path,
                        run_id=run_id,
                        event="output_budget_exceeded",
                        observed_bytes=budget_bytes,
                        raw_stdout_bytes=observed_bytes,
                        max_output_bytes=max_output_bytes,
                    )
                    process.kill()
                    raise OutputBudgetExceeded("".join(chunks))
                self._stream_to_operator(line)
                continue
            if process.poll() is not None:
                break
            time.sleep(0.05)
        remainder = process.stdout.read()
        if remainder:
            chunks.append(remainder)
            observed_bytes += byte_count(remainder)
            current_output = "".join(chunks)
            budget_bytes = self._live_budget_bytes(current_output)
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="process_output_chunk",
                chunk_bytes=byte_count(remainder),
                observed_bytes=observed_bytes,
                budget_bytes=budget_bytes,
            )
            if max_output_bytes is not None and budget_bytes > max_output_bytes:
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="output_budget_exceeded",
                    observed_bytes=budget_bytes,
                    raw_stdout_bytes=observed_bytes,
                    max_output_bytes=max_output_bytes,
                )
                process.kill()
                raise OutputBudgetExceeded("".join(chunks))
            self._stream_to_operator(remainder)
        process.stdout.close()
        process.wait()
        self._append_live_event(
            telemetry_path,
            run_id=run_id,
            event="process_exited",
            returncode=process.returncode,
            observed_bytes=observed_bytes,
        )
        return "".join(chunks)

    def _run_live_tmux(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        sentinel: str,
        telemetry_path: str | Path,
        run_id: str,
        max_output_bytes: int | None = None,
    ) -> str:
        if not shutil.which("tmux"):
            raise RuntimeError("tmux terminal mode requested but tmux is not installed")
        session = f"rarb-{self.profile.agent_id}-{int(time.time() * 1000)}-{os.getpid()}"
        session = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in session)[:80]
        command = [self.command, *self.args]
        stdin_prompt = prompt
        if self.profile.prompt_mode == "argument":
            command = self._command_with_prompt_argument(prompt)
            stdin_prompt = ""
        env_prefix = ""
        merged_env = {**os.environ, "COLUMNS": "1000", "LINES": "80", **self.env}
        for key, value in self.env.items():
            env_prefix += f"{shlex.quote(str(key))}={shlex.quote(str(value))} "
        command_line = env_prefix + shlex.join(command)
        base_env = {**merged_env, "COLUMNS": "1000", "LINES": "80"}
        stderr_file: Path | None = None
        if self.profile.agent_id == "codex":
            stderr_file = Path(telemetry_path).with_name("agent.stderr.txt")
            command_line = f"{command_line} 2> {shlex.quote(str(stderr_file))}"
        prompt_file: str | None = None
        if self.profile.prompt_mode != "argument" and stdin_prompt:
            fd, prompt_file = tempfile.mkstemp(prefix=f"{session}-", suffix=".prompt")
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(stdin_prompt)
            command_line = f"cat {shlex.quote(prompt_file)} | {command_line}"

        def tmux(*args: str, input_text: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["tmux", *args],
                input=input_text,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                env=base_env,
                check=check,
            )

        def capture() -> str:
            completed = tmux("capture-pane", "-p", "-J", "-S", f"-{TMUX_CAPTURE_HISTORY_LINES}", "-t", session, check=False)
            return completed.stdout if completed.returncode == 0 else ""

        started = time.monotonic()
        idle_timeout_seconds = float(os.environ.get("RARB_TERMINAL_IDLE_TIMEOUT_SECONDS", "180"))
        sentinel_seen_at: float | None = None
        try:
            if self.profile.prompt_mode == "argument" or prompt_file:
                tmux("new-session", "-d", "-s", session, "-c", self.cwd, command_line)
            else:
                tmux(
                    "new-session",
                    "-d",
                    "-s",
                    session,
                    "-c",
                    self.cwd,
                    "env COLUMNS=1000 LINES=80 sh -lc 'stty -echo 2>/dev/null; exec sh'",
                )
            self._append_live_event(telemetry_path, run_id=run_id, event="tmux_session_started", session=session)
            tmux("set-option", "-t", session, "remain-on-exit", "on")
            if self.profile.prompt_mode != "argument" and not prompt_file:
                tmux("send-keys", "-t", session, command_line, "Enter")
                time.sleep(0.1)
            if stdin_prompt:
                if not prompt_file:
                    buffer_name = f"{session}-prompt"
                    tmux("load-buffer", "-b", buffer_name, "-", input_text=stdin_prompt)
                    tmux("paste-buffer", "-d", "-b", buffer_name, "-t", session)
                    if not stdin_prompt.endswith("\n"):
                        tmux("send-keys", "-t", session, "Enter")
                    tmux("send-keys", "-t", session, "C-d")
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="prompt_sent",
                    prompt_bytes=byte_count(stdin_prompt),
                    prompt_transport="tmux-stdin-pipe" if prompt_file else "tmux-buffer",
                )
            elif self.profile.prompt_mode == "argument":
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="prompt_sent",
                    prompt_bytes=byte_count(prompt),
                    prompt_transport="argument",
                )
            last_capture = ""
            last_changed = time.monotonic()
            while True:
                current = capture()
                if current != last_capture:
                    previous_capture = last_capture
                    self._append_live_event(
                        telemetry_path,
                        run_id=run_id,
                        event="terminal_capture_changed",
                        session=session,
                        capture_bytes=byte_count(current),
                    )
                    budget_bytes = budget_relevant_output_bytes(current, fallback_to_raw=False)
                    if max_output_bytes is not None and budget_bytes > max_output_bytes:
                        self._append_live_event(
                            telemetry_path,
                            run_id=run_id,
                            event="output_budget_exceeded",
                            session=session,
                            observed_bytes=budget_bytes,
                            capture_bytes=byte_count(current),
                            max_output_bytes=max_output_bytes,
                        )
                        raise OutputBudgetExceeded(current)
                    if self.stream_agent_output:
                        if current.startswith(previous_capture):
                            delta = current[len(previous_capture) :]
                        else:
                            delta = current
                        self._stream_to_operator(delta)
                    last_capture = current
                    last_changed = time.monotonic()
                if has_done_sentinel(current, sentinel):
                    if sentinel_seen_at is None:
                        sentinel_seen_at = time.monotonic()
                        self._append_live_event(telemetry_path, run_id=run_id, event="sentinel_observed", session=session)
                    usage_captured = '"usage"' in current and (
                        '"input_tokens"' in current or '"output_tokens"' in current or '"total_tokens"' in current
                    )
                    if usage_captured:
                        self._append_live_event(
                            telemetry_path,
                            run_id=run_id,
                            event="post_sentinel_capture_complete",
                            session=session,
                            reason="usage_captured",
                        )
                        return current
                    if time.monotonic() - last_changed > 0.75 or time.monotonic() - sentinel_seen_at > 3.0:
                        self._append_live_event(
                            telemetry_path,
                            run_id=run_id,
                            event="post_sentinel_capture_complete",
                            session=session,
                            reason="quiet_after_sentinel",
                        )
                        return current
                if "Pane is dead" in current:
                    self._append_live_event(telemetry_path, run_id=run_id, event="tmux_pane_dead", session=session)
                    return current
                elapsed = time.monotonic() - started
                if elapsed > timeout_seconds:
                    raise subprocess.TimeoutExpired(command, timeout_seconds, output=current)
                if (
                    idle_timeout_seconds > 0
                    and current
                    and time.monotonic() - last_changed > idle_timeout_seconds
                ):
                    self._append_live_event(
                        telemetry_path,
                        run_id=run_id,
                        event="terminal_idle_timeout",
                        session=session,
                        idle_seconds=round(time.monotonic() - last_changed, 3),
                        timeout_seconds=idle_timeout_seconds,
                    )
                    raise subprocess.TimeoutExpired(command, idle_timeout_seconds, output=current)
                if current and time.monotonic() - last_changed > 1.0:
                    prompt_seen = current.rstrip().endswith(("%", "$", "#"))
                    if prompt_seen:
                        self._append_live_event(telemetry_path, run_id=run_id, event="terminal_prompt_observed", session=session)
                        return current
                time.sleep(0.1)
        finally:
            tmux("kill-session", "-t", session, check=False)
            if prompt_file:
                Path(prompt_file).unlink(missing_ok=True)
            if stderr_file and stderr_file.exists():
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="stderr_captured",
                    path=str(stderr_file),
                    stderr_bytes=stderr_file.stat().st_size,
                )
            self._append_live_event(telemetry_path, run_id=run_id, event="tmux_session_closed", session=session)

    def _run_codex_tui_bridge_command(self, args: list[str], *, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CODEX_TUI_BRIDGE), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            timeout=timeout_seconds,
            check=False,
            env={**os.environ, **self.env},
        )

    def _run_live_codex_tui(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        sentinel: str,
        telemetry_path: str | Path,
        run_id: str,
        max_output_bytes: int | None = None,
    ) -> str:
        if self.profile.agent_id != "codex":
            raise RuntimeError("codex-tui terminal mode is only valid for the Codex agent")
        if not shutil.which("tmux"):
            raise RuntimeError("codex-tui terminal mode requested but tmux is not installed")
        session = f"rarb-codex-tui-{run_id}"
        session = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in session)[:80]
        visible_transcript_path = Path(telemetry_path).with_name("visible-terminal-transcript.txt")
        answer_payload_path = Path(telemetry_path).with_name("codex-tui-answer.json")
        cleanup_path = Path(telemetry_path).with_name("codex-tui-process-cleanup.json")
        attach_terminal = os.environ.get("RARB_CODEX_TUI_NO_TERMINAL_ATTACH", "0").lower() not in {"1", "true", "yes"}
        cleanup_serena = os.environ.get("RARB_CODEX_TUI_CLEANUP_SERENA", "1").lower() not in {"0", "false", "no"}
        before_processes = serena_related_processes() if cleanup_serena else []
        prompt_file = Path(telemetry_path).with_name("codex-tui-prompt.md")
        prompt_file.write_text(prompt, encoding="utf-8")
        run_once_args = [
            "run-once",
            "--cwd",
            self.cwd,
            "--session",
            session,
            "--codex-bin",
            self.command,
            "--prompt-file",
            str(prompt_file),
            "--sentinel",
            sentinel,
            "--require-sentinel",
            "--wait",
            str(max(1, timeout_seconds - 5)),
            "--tail",
            os.environ.get("RARB_CODEX_TUI_CAPTURE_TAIL", "2000"),
            "--json",
        ]
        if not attach_terminal:
            run_once_args.append("--no-terminal-attach")
        self._append_live_event(
            telemetry_path,
            run_id=run_id,
            event="codex_tui_open_started",
            session=session,
            terminal_attached=attach_terminal,
        )
        self._append_live_event(
            telemetry_path,
            run_id=run_id,
            event="prompt_sent",
            session=session,
            prompt_bytes=byte_count(prompt),
            prompt_transport="codex-tui-initial-argument",
        )
        try:
            asked = self._run_codex_tui_bridge_command(run_once_args, timeout_seconds=timeout_seconds)
            if asked.stdout.strip():
                answer_payload_path.write_text(asked.stdout, encoding="utf-8")
            if asked.returncode not in {0, 2}:
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="codex_tui_ask_failed",
                    session=session,
                    returncode=asked.returncode,
                    stderr=asked.stderr[-2000:],
                )
                raise RuntimeError(f"codex-tui ask failed: {asked.stderr.strip()}")
            self._append_live_event(telemetry_path, run_id=run_id, event="tmux_session_started", session=session)
            self._append_live_event(telemetry_path, run_id=run_id, event="codex_tui_opened", session=session)
            try:
                payload = json.loads(asked.stdout)
            except json.JSONDecodeError as exc:
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="codex_tui_answer_json_invalid",
                    session=session,
                    error=str(exc),
                    stdout_bytes=byte_count(asked.stdout),
                )
                return asked.stdout
            visible_transcript = str(payload.get("transcript") or "")
            answer_delta = str(payload.get("answer_delta") or "")
            answer_delta = parseable_benchmark_answer_delta(answer_delta, sentinel=sentinel)
            visible_transcript_path.write_text(redact_secrets(visible_transcript), encoding="utf-8")
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="terminal_capture_changed",
                session=session,
                capture_bytes=byte_count(visible_transcript),
                answer_delta_bytes=byte_count(answer_delta),
            )
            if bool(payload.get("complete")) or has_done_sentinel(answer_delta or visible_transcript, sentinel):
                self._append_live_event(telemetry_path, run_id=run_id, event="sentinel_observed", session=session)
            observed_bytes = budget_relevant_output_bytes(answer_delta, fallback_to_raw=True)
            if max_output_bytes is not None and observed_bytes > max_output_bytes:
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="output_budget_exceeded",
                    session=session,
                    observed_bytes=observed_bytes,
                    max_output_bytes=max_output_bytes,
                )
                raise OutputBudgetExceeded(answer_delta)
            if self.stream_agent_output:
                print(answer_delta, flush=True)
            return answer_delta or visible_transcript
        finally:
            closed = self._run_codex_tui_bridge_command(["close", "--session", session], timeout_seconds=10)
            cleanup_payload: dict[str, object] = {
                "enabled": cleanup_serena,
                "before_pids": [process.pid for process in before_processes],
                "closed_returncode": closed.returncode,
                "terminated": [],
            }
            if cleanup_serena:
                after_processes = serena_related_processes()
                spawned_processes = new_processes_since(before_processes, after_processes)
                terminated = terminate_processes(spawned_processes)
                cleanup_payload.update(
                    {
                        "after_pids": [process.pid for process in after_processes],
                        "spawned_pids": [process.pid for process in spawned_processes],
                        "terminated": terminated,
                    }
                )
                self._append_live_event(
                    telemetry_path,
                    run_id=run_id,
                    event="codex_tui_process_cleanup",
                    session=session,
                    spawned_pids=[process.pid for process in spawned_processes],
                    terminated_count=len([item for item in terminated if item.get("terminated")]),
                )
            to_json_file(cleanup_path, cleanup_payload)
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="tmux_session_closed",
                session=session,
                returncode=closed.returncode,
            )

    def _run_live_pty(
        self,
        prompt: str,
        *,
        timeout_seconds: int,
        telemetry_path: str | Path,
        run_id: str,
        max_output_bytes: int | None = None,
    ) -> str:
        master_fd, slave_fd = pty.openpty()
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, struct.pack("HHHH", 80, 1000, 0, 0))
        attrs = termios.tcgetattr(slave_fd)
        attrs[3] = attrs[3] & ~termios.ECHO
        termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        command = [self.command, *self.args]
        stdin_prompt = prompt
        if self.profile.prompt_mode == "argument":
            command = self._command_with_prompt_argument(prompt)
            stdin_prompt = ""
        process = subprocess.Popen(
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=self.cwd,
            env={**os.environ, "COLUMNS": "1000", "LINES": "80", **self.env},
            close_fds=True,
        )
        self._append_live_event(telemetry_path, run_id=run_id, event="process_spawned", pid=process.pid)
        os.close(slave_fd)
        chunks: list[str] = []
        started = time.monotonic()
        observed_bytes = 0
        if stdin_prompt:
            prompt_bytes = stdin_prompt.encode("utf-8", errors="replace")
            os.write(master_fd, prompt_bytes)
            if not stdin_prompt.endswith("\n"):
                os.write(master_fd, b"\n")
            os.write(master_fd, b"\x04")
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="prompt_sent",
                prompt_bytes=len(prompt_bytes),
                prompt_transport="pty-stdin",
            )
        elif self.profile.prompt_mode == "argument":
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="prompt_sent",
                prompt_bytes=byte_count(prompt),
                prompt_transport="argument",
            )
        try:
            while True:
                if time.monotonic() - started > timeout_seconds:
                    process.kill()
                    raise subprocess.TimeoutExpired(command, timeout_seconds, output="".join(chunks))
                readable, _, _ = select.select([master_fd], [], [], 0.1)
                if readable:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    chunks.append(text)
                    observed_bytes += len(data)
                    current_output = "".join(chunks)
                    budget_bytes = self._live_budget_bytes(current_output)
                    self._append_live_event(
                        telemetry_path,
                        run_id=run_id,
                        event="process_output_chunk",
                        chunk_bytes=len(data),
                        observed_bytes=observed_bytes,
                        budget_bytes=budget_bytes,
                    )
                    if max_output_bytes is not None and budget_bytes > max_output_bytes:
                        self._append_live_event(
                            telemetry_path,
                            run_id=run_id,
                            event="output_budget_exceeded",
                            observed_bytes=budget_bytes,
                            raw_stdout_bytes=observed_bytes,
                            max_output_bytes=max_output_bytes,
                        )
                        process.kill()
                        raise OutputBudgetExceeded("".join(chunks))
                    if self.stream_agent_output:
                        self._stream_to_operator(text)
                    continue
                if process.poll() is not None:
                    try:
                        while True:
                            data = os.read(master_fd, 4096)
                            if not data:
                                break
                            text = data.decode("utf-8", errors="replace")
                            chunks.append(text)
                            observed_bytes += len(data)
                            current_output = "".join(chunks)
                            budget_bytes = self._live_budget_bytes(current_output)
                            self._append_live_event(
                                telemetry_path,
                                run_id=run_id,
                                event="process_output_chunk",
                                chunk_bytes=len(data),
                                observed_bytes=observed_bytes,
                                budget_bytes=budget_bytes,
                            )
                            if max_output_bytes is not None and budget_bytes > max_output_bytes:
                                self._append_live_event(
                                    telemetry_path,
                                    run_id=run_id,
                                    event="output_budget_exceeded",
                                    observed_bytes=budget_bytes,
                                    raw_stdout_bytes=observed_bytes,
                                    max_output_bytes=max_output_bytes,
                                )
                                process.kill()
                                raise OutputBudgetExceeded("".join(chunks))
                            if self.stream_agent_output:
                                self._stream_to_operator(text)
                    except OSError:
                        pass
                    break
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            self._append_live_event(
                telemetry_path,
                run_id=run_id,
                event="process_exited",
                returncode=process.returncode,
                observed_bytes=observed_bytes,
            )
        return "".join(chunks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generic terminal bridge for RARB subject agents.")
    parser.add_argument("command", choices=["launch-plan"])
    parser.add_argument("--agent-config", required=True)
    parser.add_argument("--cwd", default=".")
    args = parser.parse_args(argv)
    profile = load_agent_profile(args.agent_config)
    plan = build_launch_plan(profile, cwd=str(Path(args.cwd).resolve()))
    print(json.dumps(asdict(plan), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
