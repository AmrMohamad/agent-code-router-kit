#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import selectors
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import process_state_probe as process_probe  # noqa: E402


SUPPORTED_TRANSPORTS = {"stdio", "streamable-http"}
TRANSPORT_ERROR_MARKERS = (
    "transport closed",
    "connection refused",
    "connection reset",
    "broken pipe",
    "address already in use",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def validate_cases(cases: list[dict[str, str]], repo: str | None = None) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    required = {
        "case_id",
        "transport",
        "expected_status",
        "expected_min_tools",
        "semantic_tool",
        "semantic_name_path",
        "semantic_relative_path",
        "purpose",
    }
    for index, row in enumerate(cases, start=2):
        missing = sorted(required - set(row))
        if missing:
            errors.append(f"line {index}: missing columns {', '.join(missing)}")
            continue
        case_id = row["case_id"]
        if case_id in seen:
            errors.append(f"line {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        if row["transport"] not in SUPPORTED_TRANSPORTS:
            errors.append(f"line {index}: unsupported transport {row['transport']}")
        if row["expected_status"] not in {"pass", "warn", "fail"}:
            errors.append(f"line {index}: invalid expected_status {row['expected_status']}")
        try:
            expected_min_tools = int(row["expected_min_tools"])
        except ValueError:
            errors.append(f"line {index}: expected_min_tools must be an integer")
        else:
            if expected_min_tools < 0:
                errors.append(f"line {index}: expected_min_tools must be >= 0")
        if repo:
            relative_path = Path(row["semantic_relative_path"])
            if relative_path.is_absolute():
                errors.append(f"line {index}: semantic_relative_path must be relative")
            elif not (Path(repo) / relative_path).exists():
                errors.append(f"line {index}: semantic_relative_path does not exist in repo: {relative_path}")
    return errors


def process_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    before_counts = dict(before.get("counts", {}))
    after_counts = dict(after.get("counts", {}))
    keys = sorted(set(before_counts) | set(after_counts))
    return {key: int(after_counts.get(key, 0)) - int(before_counts.get(key, 0)) for key in keys}


def transport_error_seen(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in TRANSPORT_ERROR_MARKERS)


def make_initialize_request(request_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "agent-code-router-kit", "version": "android"},
        },
    }


def make_initialized_notification() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def make_tools_list_request(request_id: int = 2) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": {}}


def make_find_symbol_tool_call(row: dict[str, str], request_id: int = 3) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": row["semantic_tool"],
            "arguments": {
                "name_path_pattern": row["semantic_name_path"],
                "relative_path": row["semantic_relative_path"],
                "include_body": False,
                "depth": 0,
            },
        },
    }


def response_error(response: dict[str, Any] | None) -> str:
    if not response:
        return "missing response"
    if "error" in response:
        return json.dumps(response["error"], sort_keys=True)
    result = response.get("result")
    if isinstance(result, dict) and result.get("isError"):
        return json.dumps(result, sort_keys=True)
    return ""


def tool_count(response: dict[str, Any] | None) -> int:
    if not response:
        return 0
    result = response.get("result")
    if not isinstance(result, dict):
        return 0
    tools = result.get("tools")
    return len(tools) if isinstance(tools, list) else 0


def symbol_seen(response: dict[str, Any] | None, symbol: str) -> bool:
    if not response:
        return False
    return symbol in json.dumps(response, sort_keys=True)


def parse_sse_jsons(body: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.rstrip("\r")
        if line.startswith("data:"):
            data_lines.append(line.partition(":")[2].lstrip())
        elif not line and data_lines:
            payload = "\n".join(data_lines)
            try:
                messages.append(json.loads(payload))
            except json.JSONDecodeError:
                messages.append({"error": {"message": f"invalid SSE JSON payload: {payload[:120]}"}})
            data_lines = []
    if data_lines:
        payload = "\n".join(data_lines)
        try:
            messages.append(json.loads(payload))
        except json.JSONDecodeError:
            messages.append({"error": {"message": f"invalid SSE JSON payload: {payload[:120]}"}})
    return messages


class StdioMcpClient:
    def __init__(self, command: list[str], timeout: float) -> None:
        self.command = command
        self.timeout = timeout
        self.proc: subprocess.Popen[bytes] | None = None
        self.selector = selectors.DefaultSelector()
        self.buffer = b""
        self.received: list[dict[str, Any]] = []
        self.stderr_text = ""

    def __enter__(self) -> "StdioMcpClient":
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        assert self.proc.stdout is not None
        os.set_blocking(self.proc.stdout.fileno(), False)
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except BrokenPipeError:
            pass
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.proc.wait(timeout=5)
        if self.proc.stderr:
            try:
                self.stderr_text += self.proc.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                pass
        try:
            self.selector.close()
        except Exception:
            pass

    def send(self, payload: dict[str, Any]) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("stdio client is not running")
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        self.proc.stdin.write(line.encode("utf-8"))
        self.proc.stdin.flush()

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = payload["id"]
        self.send(payload)
        return self.wait_for_id(request_id)

    def notify(self, payload: dict[str, Any]) -> None:
        self.send(payload)

    def wait_for_id(self, request_id: int) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return {"error": {"message": f"process exited with code {self.proc.returncode}"}}
            self._read_available(max(0.05, min(0.5, deadline - time.monotonic())))
            for item in self.received:
                if item.get("id") == request_id:
                    return item
        return {"error": {"message": f"timed out waiting for response id {request_id}"}}

    def _read_available(self, timeout: float) -> None:
        for key, _ in self.selector.select(timeout):
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                continue
            self.buffer += chunk
            while b"\n" in self.buffer:
                raw_line, self.buffer = self.buffer.split(b"\n", 1)
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    self.received.append(json.loads(line))
                except json.JSONDecodeError:
                    self.received.append({"error": {"message": f"invalid JSON line: {line[:120]}"}})


class HttpMcpClient:
    def __init__(self, command: list[str], port: int, timeout: float) -> None:
        self.command = command
        self.port = port
        self.timeout = timeout
        self.proc: subprocess.Popen[bytes] | None = None
        self.session_id: str | None = None
        self.stderr_text = ""

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"

    def __enter__(self) -> "HttpMcpClient":
        self.proc = subprocess.Popen(
            self.command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                self.proc.wait(timeout=5)
        if self.proc.stderr:
            try:
                self.stderr_text += self.proc.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                pass

    def post(self, payload: dict[str, Any], session_id: str | None = None) -> tuple[int, dict[str, str], str]:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        request = urllib.request.Request(self.url, data=data, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return int(response.status), dict(response.headers), body

    def request(self, payload: dict[str, Any], startup_deadline: float | None = None) -> dict[str, Any]:
        deadline = startup_deadline or (time.monotonic() + self.timeout)
        last_error = ""
        while time.monotonic() < deadline:
            try:
                status, headers, body = self.post(payload, self.session_id)
                if payload.get("method") == "initialize":
                    self.session_id = headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
                messages = parse_sse_jsons(body) if status == 200 else []
                if messages:
                    return messages[0]
                return {"error": {"message": f"HTTP {status} returned no JSON-RPC SSE payload"}}
            except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
                last_error = str(exc)
                time.sleep(0.25)
        return {"error": {"message": f"timed out waiting for HTTP MCP response: {last_error}"}}

    def notify_initialized(self) -> dict[str, Any]:
        if not self.session_id:
            return {"error": {"message": "missing MCP session id"}}
        try:
            status, _, body = self.post(make_initialized_notification(), self.session_id)
        except (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout) as exc:
            return {"error": {"message": str(exc)}}
        return {"status": status, "body": body}


def base_serena_command(args: argparse.Namespace, transport: str, port: int | None = None) -> list[str]:
    command = [
        args.serena_command,
        "start-mcp-server",
        "--transport",
        transport,
        "--project",
        str(Path(args.repo).expanduser().resolve()),
        "--context=codex",
        "--enable-web-dashboard",
        "False",
        "--open-web-dashboard",
        "False",
        "--log-level",
        args.log_level,
    ]
    if transport == "streamable-http":
        command.extend(["--host", "127.0.0.1", "--port", str(port)])
    if args.tool_timeout:
        command.extend(["--tool-timeout", str(args.tool_timeout)])
    return command


def run_stdio_case(args: argparse.Namespace, row: dict[str, str]) -> dict[str, Any]:
    command = base_serena_command(args, "stdio")
    started_at = time.monotonic()
    client = StdioMcpClient(command, timeout=args.timeout)
    client.__enter__()
    try:
        initialize = client.request(make_initialize_request(1))
        if not response_error(initialize):
            client.notify(make_initialized_notification())
        tools = client.request(make_tools_list_request(2)) if not response_error(initialize) else None
        semantic = client.request(make_find_symbol_tool_call(row, 3)) if tools and not response_error(tools) else None
        received = list(client.received)
    finally:
        client.close()
    stderr_text = client.stderr_text
    return build_case_result(row, "stdio", command, None, started_at, initialize, tools, semantic, stderr_text, received)


def run_http_case(args: argparse.Namespace, row: dict[str, str]) -> dict[str, Any]:
    port = args.http_port if args.http_port > 0 else choose_port()
    command = base_serena_command(args, "streamable-http", port)
    started_at = time.monotonic()
    client = HttpMcpClient(command, port=port, timeout=args.timeout)
    client.__enter__()
    try:
        initialize = client.request(make_initialize_request(1), startup_deadline=time.monotonic() + args.startup_timeout)
        initialized = client.notify_initialized() if not response_error(initialize) else None
        tools = client.request(make_tools_list_request(2)) if initialized and not response_error(initialized) else None
        semantic = client.request(make_find_symbol_tool_call(row, 3)) if tools and not response_error(tools) else None
        received = [item for item in [initialize, initialized, tools, semantic] if item]
    finally:
        client.close()
    stderr_text = client.stderr_text
    return build_case_result(row, "streamable-http", command, port, started_at, initialize, tools, semantic, stderr_text, received)


def build_case_result(
    row: dict[str, str],
    transport: str,
    command: list[str],
    port: int | None,
    started_at: float,
    initialize: dict[str, Any] | None,
    tools: dict[str, Any] | None,
    semantic: dict[str, Any] | None,
    stderr_text: str,
    received: list[dict[str, Any]],
) -> dict[str, Any]:
    initialize_error = response_error(initialize)
    tools_error = response_error(tools)
    semantic_error = response_error(semantic)
    min_tools = int(row["expected_min_tools"])
    actual_tool_count = tool_count(tools)
    semantic_symbol_seen = symbol_seen(semantic, row["semantic_name_path"])
    checks = {
        "initialize": not initialize_error,
        "tools_list": not tools_error and actual_tool_count >= min_tools,
        "semantic_tool_call": not semantic_error and semantic_symbol_seen,
        "transport_error_absent": not transport_error_seen(stderr_text + "\n" + json.dumps(received, sort_keys=True)),
    }
    status = "pass" if all(checks.values()) else "fail"
    return {
        "case_id": row["case_id"],
        "transport": transport,
        "expected_status": row["expected_status"],
        "expected_min_tools": min_tools,
        "semantic_tool": row["semantic_tool"],
        "semantic_name_path": row["semantic_name_path"],
        "semantic_relative_path": row["semantic_relative_path"],
        "status": status,
        "checks": checks,
        "initialize_error": initialize_error,
        "tools_error": tools_error,
        "semantic_error": semantic_error,
        "tool_count": actual_tool_count,
        "semantic_symbol_seen": semantic_symbol_seen,
        "wall_seconds": time.monotonic() - started_at,
        "port": port,
        "command": command,
        "stderr": stderr_text,
        "responses": {
            "initialize": initialize,
            "tools": tools,
            "semantic": semantic,
        },
    }


def build_assertions(
    rows: list[dict[str, Any]],
    before_process: dict[str, Any],
    after_process: dict[str, Any],
    max_serena_growth: int = 0,
) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []

    def add(status: str, check: str, message: str) -> None:
        assertions.append({"status": status, "check": check, "message": message})

    failed_rows = [row for row in rows if row["status"] != row["expected_status"]]
    add(
        "pass" if not failed_rows else "fail",
        "expected_status",
        "All MCP lifecycle cases matched expected status." if not failed_rows else f"{len(failed_rows)} cases did not match expected status.",
    )

    for transport in sorted({row["transport"] for row in rows}):
        transport_rows = [row for row in rows if row["transport"] == transport]
        ok = all(row["checks"].get("initialize") for row in transport_rows)
        add("pass" if ok else "fail", f"{transport}_initialize", f"{transport}: initialize {'passed' if ok else 'failed'}.")
        ok = all(row["checks"].get("tools_list") for row in transport_rows)
        add("pass" if ok else "fail", f"{transport}_tools_list", f"{transport}: tools/list {'passed' if ok else 'failed'}.")
        ok = all(row["checks"].get("semantic_tool_call") for row in transport_rows)
        add("pass" if ok else "fail", f"{transport}_semantic_tool_call", f"{transport}: semantic find_symbol call {'passed' if ok else 'failed'}.")

    if any(not row["checks"].get("transport_error_absent") for row in rows):
        add("fail", "transport_error_absent", "Transport closed/reset/refused marker was seen.")
    else:
        add("pass", "transport_error_absent", "No transport closed/reset/refused marker was seen.")

    delta = process_delta(before_process, after_process)
    serena_growth = int(delta.get("serena_mcp", 0))
    add(
        "pass" if serena_growth <= max_serena_growth else "fail",
        "serena_process_growth",
        f"serena_mcp_delta={serena_growth} max={max_serena_growth}",
    )
    kotlin_growth = int(delta.get("kotlin_lsp", 0))
    add(
        "pass" if kotlin_growth <= 1 else "warn",
        "kotlin_lsp_process_growth",
        f"kotlin_lsp_delta={kotlin_growth}",
    )

    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions, "process_delta": delta}


def transport_performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_transport: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_transport.setdefault(str(row["transport"]), []).append(row)

    summaries: dict[str, Any] = {}
    for transport, transport_rows in sorted(by_transport.items()):
        durations = sorted(float(row.get("wall_seconds", 0.0)) for row in transport_rows)
        pass_count = sum(1 for row in transport_rows if row.get("status") == "pass")
        fail_count = len(transport_rows) - pass_count
        avg = sum(durations) / len(durations) if durations else 0.0
        p95_index = max(0, min(len(durations) - 1, int(round((len(durations) - 1) * 0.95)))) if durations else 0
        summaries[transport] = {
            "case_count": len(transport_rows),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "avg_wall_seconds": avg,
            "max_wall_seconds": durations[-1] if durations else 0.0,
            "p95_wall_seconds": durations[p95_index] if durations else 0.0,
        }

    passing = {
        transport: summary
        for transport, summary in summaries.items()
        if summary["case_count"] > 0 and summary["fail_count"] == 0
    }
    candidate = ""
    if passing:
        candidate = min(passing.items(), key=lambda item: (item[1]["avg_wall_seconds"], item[0]))[0]
    return {
        "transports": summaries,
        "candidate_transport": candidate,
        "recommendation_status": "lifecycle_candidate_only" if candidate else "no_candidate",
        "recommendation_boundary": "Do not promote to daily recommendation without repeated real-task evidence.",
    }


def write_outputs(output: Path, run_id: str, rows: list[dict[str, Any]], summary: dict[str, Any], assertions: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    persisted_rows: list[dict[str, Any]] = []
    for row in rows:
        base = safe_name(f"{row['case_id']}_{row['transport']}")
        response_path = raw_dir / f"{base}.json"
        stderr_path = raw_dir / f"{base}.stderr"
        response_path.write_text(json.dumps(row["responses"], indent=2, sort_keys=True) + "\n")
        stderr_path.write_text(str(row["stderr"]))
        persisted = {key: value for key, value in row.items() if key not in {"responses", "stderr", "command", "checks"}}
        persisted["command"] = " ".join(row["command"])
        persisted["checks"] = json.dumps(row["checks"], sort_keys=True)
        persisted["response_path"] = str(response_path)
        persisted["stderr_path"] = str(stderr_path)
        persisted_rows.append(persisted)

    rows_path = output / f"android-serena-mcp-lifecycle-{run_id}.tsv"
    summary_path = output / f"android-serena-mcp-lifecycle-summary-{run_id}.json"
    assertions_path = output / f"android-serena-mcp-lifecycle-assertions-{run_id}.json"
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=list(persisted_rows[0].keys()))
        writer.writeheader()
        writer.writerows(persisted_rows)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n")
    return {"rows": str(rows_path), "summary": str(summary_path), "assertions": str(assertions_path), "raw_dir": str(raw_dir)}


def run(args: argparse.Namespace, cases: list[dict[str, str]]) -> int:
    selected_transports = set(args.transports.split(",")) if args.transports else SUPPORTED_TRANSPORTS
    cases = [row for row in cases if row["transport"] in selected_transports]
    if not cases:
        print("No cases selected")
        return 2

    target_project_path = str(Path(args.repo).expanduser().resolve())
    before_process = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=target_project_path,
        expected_serena_mcp_count=args.expected_serena_mcp_count,
        allow_http_serena_server=True,
    )
    rows: list[dict[str, Any]] = []
    for row in cases:
        if row["transport"] == "stdio":
            rows.append(run_stdio_case(args, row))
        elif row["transport"] == "streamable-http":
            rows.append(run_http_case(args, row))
        time.sleep(args.cooldown_seconds)
    after_process = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=target_project_path,
        expected_serena_mcp_count=args.expected_serena_mcp_count,
        allow_http_serena_server=True,
    )
    assertions = build_assertions(rows, before_process, after_process, max_serena_growth=args.max_serena_growth)
    run_id = stamp()
    summary = {
        "schema": "agent-code-router-kit.android-serena-mcp-lifecycle.v1",
        "date_utc": utc_now(),
        "scope": "Sample B2B stable MCP lifecycle smoke, not Android completion",
        "repo": target_project_path,
        "case_count": len(rows),
        "transports": sorted(selected_transports),
        "before_process_status": before_process["status"],
        "after_process_status": after_process["status"],
        "process_delta": assertions["process_delta"],
        "transport_performance": transport_performance(rows),
        "cases": [
            {
                "case_id": row["case_id"],
                "transport": row["transport"],
                "status": row["status"],
                "tool_count": row["tool_count"],
                "semantic_symbol_seen": row["semantic_symbol_seen"],
                "wall_seconds": row["wall_seconds"],
                "checks": row["checks"],
            }
            for row in rows
        ],
    }
    paths = write_outputs(Path(args.output).expanduser().resolve(), run_id, rows, summary, assertions)
    counts = assertions["summary"]
    print(f"Wrote {paths['rows']}")
    print(f"Wrote {paths['summary']}")
    print(f"Wrote {paths['assertions']}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}; process_delta={assertions['process_delta']}")
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe direct Serena MCP stdio/HTTP lifecycle for Android.")
    parser.add_argument("--cases", default="benchmarks/android/serena-mcp-lifecycle.sample-b2b.tsv")
    parser.add_argument("--repo", default="")
    parser.add_argument("--output", default="results/android/serena-mcp-lifecycle")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--transports", default="stdio,streamable-http")
    parser.add_argument("--serena-command", default="serena")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--startup-timeout", type=float, default=60)
    parser.add_argument("--tool-timeout", type=float, default=180)
    parser.add_argument("--http-port", type=int, default=0)
    parser.add_argument("--cooldown-seconds", type=float, default=1.0)
    parser.add_argument("--expected-serena-mcp-count", type=int, default=1)
    parser.add_argument("--max-serena-growth", type=int, default=0)
    parser.add_argument("--log-level", default="WARNING")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.run and not args.repo:
        parser.error("--repo is required with --run")
    selected_transports = set(args.transports.split(",")) if args.transports else SUPPORTED_TRANSPORTS
    invalid = sorted(selected_transports - SUPPORTED_TRANSPORTS)
    if invalid:
        parser.error(f"unsupported transports: {', '.join(invalid)}")
    if args.timeout <= 0 or args.startup_timeout <= 0 or args.tool_timeout <= 0:
        parser.error("timeouts must be > 0")
    if args.cooldown_seconds < 0:
        parser.error("--cooldown-seconds must be >= 0")

    cases = load_cases(Path(args.cases))
    errors = validate_cases(cases, repo=args.repo if args.repo else None)
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases")
    if args.run:
        return run(args, cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
