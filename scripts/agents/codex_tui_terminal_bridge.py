from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path


STATE_DIR = Path.home() / ".codex" / "tmp" / "codex-tui-terminal-bridge"
STATE_FILE = STATE_DIR / "state.json"
DEFAULT_SESSION = "rarb-codex-tui"
DEFAULT_TAIL = 240


def run(command: list[str], *, check: bool = True, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check, **kwargs)


def tmux_bin() -> str:
    resolved = shutil.which("tmux")
    if not resolved:
        raise SystemExit("tmux is required for visible Codex TUI control")
    return resolved


def codex_bin(explicit: str | None = None) -> str:
    resolved = shutil.which(explicit or "codex")
    if not resolved:
        raise SystemExit("codex CLI was not found on PATH")
    return resolved


def osascript(script: str, *args: str) -> str:
    completed = run(["osascript", "-e", script, *args], check=True)
    return completed.stdout.strip()


def save_state(state: dict[str, object]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        STATE_DIR.chmod(0o700)
    except PermissionError:
        pass
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def load_state() -> dict[str, object]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def tmux_target(session: str) -> str:
    return f"{session}:0.0"


def tmux_session_exists(session: str) -> bool:
    return run([tmux_bin(), "has-session", "-t", session], check=False).returncode == 0


def tmux_capture(session: str, *, tail: int = DEFAULT_TAIL) -> str:
    start = f"-{tail}" if tail > 0 else "-5000"
    completed = run([tmux_bin(), "capture-pane", "-t", tmux_target(session), "-p", "-S", start], check=True)
    return completed.stdout.rstrip()


def answer_delta(baseline: str, transcript: str) -> str:
    if transcript.startswith(baseline) and (len(transcript) == len(baseline) or transcript[len(baseline)] == "\n"):
        return transcript[len(baseline) :].strip()
    baseline_lines = baseline.splitlines()
    transcript_lines = transcript.splitlines()
    index = 0
    while index < min(len(baseline_lines), len(transcript_lines)) and baseline_lines[index] == transcript_lines[index]:
        index += 1
    return "\n".join(transcript_lines[index:]).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def paste_prompt(
    session: str,
    text: str,
    *,
    clear_before: bool = True,
    submit_delay: float = 0.18,
    return_count: int = 1,
    return_delay: float = 0.12,
) -> None:
    target = tmux_target(session)
    if clear_before:
        run([tmux_bin(), "send-keys", "-t", target, "C-u"], check=True)
        time.sleep(0.05)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    millis = int(time.time() * 1000)
    prompt_path = STATE_DIR / f"prompt-{millis}.txt"
    buffer_name = f"codex_tui_bridge_{millis}"
    try:
        prompt_path.write_text(text, encoding="utf-8")
        run([tmux_bin(), "load-buffer", "-b", buffer_name, str(prompt_path)], check=True)
        run([tmux_bin(), "paste-buffer", "-d", "-b", buffer_name, "-t", target], check=True)
    finally:
        prompt_path.unlink(missing_ok=True)
    if submit_delay > 0:
        time.sleep(submit_delay)
    for index in range(return_count):
        run([tmux_bin(), "send-keys", "-t", target, "Enter"], check=True)
        if index < return_count - 1 and return_delay > 0:
            time.sleep(return_delay)


def wait_for_completion(
    session: str,
    *,
    baseline: str,
    sentinel: str | None,
    wait: float,
    min_wait: float,
    poll_interval: float,
    idle_timeout: float,
    tail: int,
) -> tuple[str, str, int]:
    deadline = time.monotonic() + wait
    earliest = time.monotonic() + min_wait
    last = baseline
    last_change = time.monotonic()
    started = False
    polls = 0
    current = baseline
    baseline_sentinel_count = baseline.count(sentinel) if sentinel else 0
    while True:
        current = tmux_capture(session, tail=tail)
        polls += 1
        now = time.monotonic()
        if sentinel and current.count(sentinel) > baseline_sentinel_count:
            return current, "sentinel", polls
        if current != last:
            last = current
            last_change = now
            started = current != baseline
        elif started and now >= earliest and now - last_change >= idle_timeout:
            return current, "idle", polls
        if now >= deadline:
            return current, "timeout", polls
        time.sleep(poll_interval)


def cmd_open(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        raise SystemExit(f"cwd is not a directory: {cwd}")
    agent = codex_bin(args.codex_bin)
    session_exists = tmux_session_exists(args.session)
    if session_exists:
        state = load_state()
        same_session = state.get("session") == args.session
        same_cwd = state.get("cwd") == str(cwd)
        same_agent = state.get("codex_bin") == agent
        if not args.reuse_existing and not (same_session and same_cwd and same_agent):
            raise SystemExit(
                "tmux session already exists but saved cwd/codex state does not match; "
                "pass --reuse-existing intentionally or choose another --session"
            )
    else:
        command = shlex.join([agent, *args.codex_args])
        run([tmux_bin(), "new-session", "-d", "-s", args.session, "-c", str(cwd), command], check=True)
        time.sleep(args.startup_delay)

    window_id: int | None = None
    if not args.no_terminal_attach:
        script = """
on run argv
  set shellCommand to item 1 of argv
  tell application "Terminal"
    activate
    set newTab to do script shellCommand
    delay 0.2
    set newWindow to front window
    return id of newWindow
  end tell
end run
"""
        window_id = int(osascript(script, f"tmux attach -t {shlex.quote(args.session)}"))
    state = {
        "session": args.session,
        "cwd": str(cwd),
        "codex_bin": agent,
        "window_id": window_id,
        "created_at": int(time.time()),
        "backend": "tmux",
        "reused_existing": session_exists,
    }
    save_state(state)
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    state = load_state()
    session = args.session or str(state.get("session") or DEFAULT_SESSION)
    if not tmux_session_exists(session):
        raise SystemExit(f"No live tmux session {session!r}. Run open first.")
    text = args.text or ""
    if args.prompt_file:
        text = Path(args.prompt_file).read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit("ask requires --text or --prompt-file")
    sentinel = args.sentinel
    prompt = text
    if sentinel and sentinel not in prompt:
        prompt = f"{prompt.rstrip()}\n\nEnd your answer with exactly this sentinel on its own line:\n{sentinel}\n"
    baseline = tmux_capture(session, tail=args.tail)
    paste_prompt(
        session,
        prompt,
        clear_before=not args.no_clear,
        submit_delay=args.submit_delay,
        return_count=args.return_count,
        return_delay=args.return_delay,
    )
    if args.post_submit_baseline_delay > 0:
        time.sleep(args.post_submit_baseline_delay)
        post_submit_baseline = tmux_capture(session, tail=args.tail)
    else:
        post_submit_baseline = baseline
    transcript, reason, polls = wait_for_completion(
        session,
        baseline=post_submit_baseline,
        sentinel=sentinel,
        wait=args.wait,
        min_wait=args.min_wait,
        poll_interval=args.poll_interval,
        idle_timeout=args.idle_timeout,
        tail=args.tail,
    )
    delta = answer_delta(post_submit_baseline, transcript)
    payload = {
        "session": session,
        "complete": reason == "sentinel" if sentinel else reason in {"idle", "sentinel"},
        "completion_reason": reason,
        "sentinel": sentinel,
        "polls": polls,
        "transcript": transcript,
        "answer_delta": delta,
        "answer_delta_sha256": sha256_text(delta),
        "baseline_sha256": sha256_text(baseline),
        "post_submit_baseline_sha256": sha256_text(post_submit_baseline),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(delta or transcript)
    if args.require_sentinel and sentinel and reason != "sentinel":
        return 2
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    state = load_state()
    session = args.session or str(state.get("session") or DEFAULT_SESSION)
    print(tmux_capture(session, tail=args.tail))
    return 0


def cmd_run_once(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        raise SystemExit(f"cwd is not a directory: {cwd}")
    text = args.text or ""
    if args.prompt_file:
        text = Path(args.prompt_file).read_text(encoding="utf-8")
    if not text.strip():
        raise SystemExit("run-once requires --text or --prompt-file")
    if args.sentinel and args.sentinel not in text:
        text = f"{text.rstrip()}\n\nEnd your answer with exactly this sentinel on its own line:\n{args.sentinel}\n"
    agent = codex_bin(args.codex_bin)
    if tmux_session_exists(args.session):
        if not args.reuse_existing:
            raise SystemExit(f"tmux session already exists: {args.session}")
        run([tmux_bin(), "kill-session", "-t", args.session], check=False)
    command = shlex.join([agent, *args.codex_args, text])
    run([tmux_bin(), "new-session", "-d", "-s", args.session, "-c", str(cwd), command], check=True)
    window_id: int | None = None
    if not args.no_terminal_attach:
        script = """
on run argv
  set shellCommand to item 1 of argv
  tell application "Terminal"
    activate
    set newTab to do script shellCommand
    delay 0.2
    set newWindow to front window
    return id of newWindow
  end tell
end run
"""
        window_id = int(osascript(script, f"tmux attach -t {shlex.quote(args.session)}"))
    state = {
        "session": args.session,
        "cwd": str(cwd),
        "codex_bin": agent,
        "window_id": window_id,
        "created_at": int(time.time()),
        "backend": "tmux",
        "run_once": True,
    }
    save_state(state)
    transcript, reason, polls = wait_for_completion(
        args.session,
        baseline="",
        sentinel=args.sentinel,
        wait=args.wait,
        min_wait=args.min_wait,
        poll_interval=args.poll_interval,
        idle_timeout=args.idle_timeout,
        tail=args.tail,
    )
    payload = {
        "session": args.session,
        "complete": reason == "sentinel" if args.sentinel else reason in {"idle", "sentinel"},
        "completion_reason": reason,
        "sentinel": args.sentinel,
        "polls": polls,
        "transcript": transcript,
        "answer_delta": transcript,
        "answer_delta_sha256": sha256_text(transcript),
        "window_id": window_id,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(transcript)
    if args.require_sentinel and args.sentinel and reason != "sentinel":
        return 2
    return 0


def cmd_close(args: argparse.Namespace) -> int:
    session = args.session or str(load_state().get("session") or DEFAULT_SESSION)
    run([tmux_bin(), "kill-session", "-t", session], check=False)
    print(json.dumps({"session": session, "closed": True}, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate Codex TUI in a visible macOS Terminal via tmux.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    open_cmd = subparsers.add_parser("open", help="Open or attach a visible Codex TUI tmux session.")
    open_cmd.add_argument("--cwd", default=os.getcwd())
    open_cmd.add_argument("--session", default=DEFAULT_SESSION)
    open_cmd.add_argument("--codex-bin")
    open_cmd.add_argument("--codex-args", nargs="*", default=["--no-alt-screen"])
    open_cmd.add_argument("--reuse-existing", action="store_true")
    open_cmd.add_argument("--no-terminal-attach", action="store_true")
    open_cmd.add_argument("--startup-delay", type=float, default=1.5)
    open_cmd.set_defaults(func=cmd_open)

    ask_cmd = subparsers.add_parser("ask", help="Paste a prompt into the visible Codex TUI session and capture the answer delta.")
    ask_cmd.add_argument("--session")
    ask_cmd.add_argument("--text")
    ask_cmd.add_argument("--prompt-file")
    ask_cmd.add_argument("--sentinel")
    ask_cmd.add_argument("--require-sentinel", action="store_true")
    ask_cmd.add_argument("--return-count", type=int, default=1)
    ask_cmd.add_argument("--submit-delay", type=float, default=0.18)
    ask_cmd.add_argument("--return-delay", type=float, default=0.12)
    ask_cmd.add_argument("--post-submit-baseline-delay", type=float, default=0.35)
    ask_cmd.add_argument("--no-clear", action="store_true")
    ask_cmd.add_argument("--wait", type=float, default=45)
    ask_cmd.add_argument("--min-wait", type=float, default=1.0)
    ask_cmd.add_argument("--poll-interval", type=float, default=0.25)
    ask_cmd.add_argument("--idle-timeout", type=float, default=1.2)
    ask_cmd.add_argument("--tail", type=int, default=DEFAULT_TAIL)
    ask_cmd.add_argument("--json", action="store_true")
    ask_cmd.set_defaults(func=cmd_ask)

    read_cmd = subparsers.add_parser("read", help="Read the visible Codex TUI transcript.")
    read_cmd.add_argument("--session")
    read_cmd.add_argument("--tail", type=int, default=DEFAULT_TAIL)
    read_cmd.set_defaults(func=cmd_read)

    run_once_cmd = subparsers.add_parser("run-once", help="Start Codex TUI with one prompt argument and wait for completion.")
    run_once_cmd.add_argument("--cwd", default=os.getcwd())
    run_once_cmd.add_argument("--session", default=DEFAULT_SESSION)
    run_once_cmd.add_argument("--codex-bin")
    run_once_cmd.add_argument("--codex-args", nargs="*", default=["--no-alt-screen"])
    run_once_cmd.add_argument("--reuse-existing", action="store_true")
    run_once_cmd.add_argument("--no-terminal-attach", action="store_true")
    run_once_cmd.add_argument("--text")
    run_once_cmd.add_argument("--prompt-file")
    run_once_cmd.add_argument("--sentinel")
    run_once_cmd.add_argument("--require-sentinel", action="store_true")
    run_once_cmd.add_argument("--wait", type=float, default=45)
    run_once_cmd.add_argument("--min-wait", type=float, default=1.0)
    run_once_cmd.add_argument("--poll-interval", type=float, default=0.25)
    run_once_cmd.add_argument("--idle-timeout", type=float, default=1.2)
    run_once_cmd.add_argument("--tail", type=int, default=2000)
    run_once_cmd.add_argument("--json", action="store_true")
    run_once_cmd.set_defaults(func=cmd_run_once)

    close_cmd = subparsers.add_parser("close", help="Close the visible Codex TUI tmux session.")
    close_cmd.add_argument("--session")
    close_cmd.set_defaults(func=cmd_close)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if sys.platform != "darwin" and args.command in {"open", "run-once"} and not args.no_terminal_attach:
        raise SystemExit("visible Terminal attach requires macOS; pass --no-terminal-attach for tmux-only control")
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
