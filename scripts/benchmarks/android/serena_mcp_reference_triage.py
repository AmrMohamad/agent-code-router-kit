#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import process_state_probe as process_probe  # noqa: E402
import studio_semantic_probe as studio_probe  # noqa: E402
import serena_mcp_lifecycle_probe as mcp_probe  # noqa: E402
from serena_reference_triage import extract_paths, text_is_empty_semantic_result  # noqa: E402


REQUIRED_COLUMNS = [
    "case_id",
    "transport",
    "studio_project",
    "symbol_label",
    "find_symbol_args_json",
    "reference_args_json",
    "studio_symbol",
    "studio_context_file",
    "expected_classification",
    "expected_studio_files_json",
    "purpose",
]

VALID_CLASSIFICATIONS = {
    "probe",
    "fixed",
    "query-shape issue",
    "transport/process issue",
    "kotlin-lsp limitation",
    "serena-tool limitation",
    "serena-reference-empty-boundary",
    "studio-probe unavailable",
    "unclassified disagreement",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("_")


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise SystemExit(f"schema mismatch: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise SystemExit("case manifest is empty")
    return rows


def validate_cases(cases: list[dict[str, str]], repo: str | None = None) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(cases, start=2):
        for column in REQUIRED_COLUMNS:
            if column not in row or row[column] == "":
                errors.append(f"line {index}: missing {column}")
        case_id = row.get("case_id", "")
        if case_id in seen:
            errors.append(f"line {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        if row.get("transport") not in mcp_probe.SUPPORTED_TRANSPORTS:
            errors.append(f"line {index}: unsupported transport {row.get('transport')!r}")
        if row.get("expected_classification") not in VALID_CLASSIFICATIONS:
            errors.append(f"line {index}: invalid expected_classification {row.get('expected_classification')!r}")
        for json_column in ("find_symbol_args_json", "reference_args_json"):
            try:
                decoded = json.loads(row.get(json_column, ""))
            except json.JSONDecodeError as exc:
                errors.append(f"line {index}: invalid {json_column}: {exc}")
                continue
            if not isinstance(decoded, dict):
                errors.append(f"line {index}: {json_column} must decode to an object")
        try:
            expected = json.loads(row.get("expected_studio_files_json", ""))
        except json.JSONDecodeError as exc:
            errors.append(f"line {index}: invalid expected_studio_files_json: {exc}")
        else:
            if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
                errors.append(f"line {index}: expected_studio_files_json must decode to a list of strings")
        if repo:
            root = Path(repo)
            if not root.exists():
                errors.append(f"line {index}: repo path missing: {root}")
            else:
                for json_column in ("find_symbol_args_json", "reference_args_json"):
                    decoded = json.loads(row[json_column])
                    relative_path = decoded.get("relative_path")
                    if isinstance(relative_path, str) and relative_path and not (root / relative_path).exists():
                        errors.append(f"line {index}: {json_column} relative_path missing: {root / relative_path}")
                context_file = row.get("studio_context_file", "")
                if context_file and not (root / context_file).exists():
                    errors.append(f"line {index}: studio_context_file missing: {root / context_file}")
    return errors


def make_tool_call(tool_name: str, arguments: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }


def tool_text(response: dict[str, Any] | None) -> str:
    if not response:
        return ""
    result = response.get("result")
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
        structured = result.get("structuredContent")
        if isinstance(structured, dict) and "result" in structured:
            return str(structured["result"])
    return json.dumps(response, sort_keys=True)


def response_status(response: dict[str, Any] | None) -> str:
    error = mcp_probe.response_error(response)
    text = tool_text(response)
    lowered = f"{error}\n{text}".lower()
    result = response.get("result") if isinstance(response, dict) else None
    is_tool_error = isinstance(result, dict) and bool(result.get("isError"))
    if not error and not is_tool_error and "error executing tool" not in lowered:
        return "pass"
    if "timed out" in lowered:
        return "timeout"
    return "error"


def classify_case(find_response: dict[str, Any], reference_response: dict[str, Any], studio_result: dict[str, Any], serena_paths: set[str], studio_paths: set[str]) -> str:
    find_status = response_status(find_response)
    reference_status = response_status(reference_response)
    studio_status = str(studio_result.get("status"))
    reference_text = tool_text(reference_response)
    if find_status == "timeout" or reference_status == "timeout":
        return "transport/process issue"
    if reference_status == "error":
        lowered = f"{mcp_probe.response_error(reference_response)}\n{tool_text(reference_response)}".lower()
        if "no symbol matching" in lowered or "relative_path" in lowered or "field required" in lowered:
            return "query-shape issue"
        if "textdocument/references" in lowered or "notundercontentroot" in lowered:
            return "kotlin-lsp limitation"
        if "not implemented" in lowered or "unsupported" in lowered:
            return "serena-tool limitation"
        return "transport/process issue"
    if studio_status in {"timeout", "error", "no-result", "empty"}:
        return "studio-probe unavailable"
    if reference_status == "pass" and not text_is_empty_semantic_result(reference_text) and serena_paths & studio_paths:
        return "fixed"
    if find_status == "pass" and studio_status == "pass" and text_is_empty_semantic_result(reference_text):
        return "serena-reference-empty-boundary"
    if reference_status == "pass" and not text_is_empty_semantic_result(reference_text):
        return "unclassified disagreement"
    return "unclassified disagreement"


def run_studio_usages(row: dict[str, str], repo: Path, timeout: float) -> dict[str, Any]:
    studio_row = {
        "case_id": row["case_id"],
        "repo": "sample_b2b_android",
        "project": row["studio_project"],
        "command_type": "find-usages",
        "symbol": row["studio_symbol"],
        "context_file": row["studio_context_file"],
        "expected_status": "probe",
        "purpose": row["purpose"],
    }
    result = studio_probe.execute(studio_row, repo, timeout)
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    if "No running Android Studio instance has project" in text:
        result["status"] = "error"
    return result


def start_client(args: argparse.Namespace, transport: str) -> tuple[Any, list[str], int | None]:
    port = None
    if transport == "streamable-http":
        port = args.http_port if args.http_port > 0 else mcp_probe.choose_port()
    command = mcp_probe.base_serena_command(args, transport, port)
    if transport == "stdio":
        client = mcp_probe.StdioMcpClient(command, timeout=args.timeout)
    else:
        assert port is not None
        client = mcp_probe.HttpMcpClient(command, port=port, timeout=args.timeout)
    client.__enter__()
    return client, command, port


def initialize_client(client: Any, transport: str, startup_timeout: float) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    if transport == "streamable-http":
        initialize = client.request(mcp_probe.make_initialize_request(1), startup_deadline=time.monotonic() + startup_timeout)
        initialized = client.notify_initialized() if not mcp_probe.response_error(initialize) else None
        tools = client.request(mcp_probe.make_tools_list_request(2)) if initialized and not mcp_probe.response_error(initialized) else None
    else:
        initialize = client.request(mcp_probe.make_initialize_request(1))
        if not mcp_probe.response_error(initialize):
            client.notify(mcp_probe.make_initialized_notification())
        initialized = {"status": "sent"}
        tools = client.request(mcp_probe.make_tools_list_request(2)) if not mcp_probe.response_error(initialize) else None
    return initialize, initialized or {}, tools


def execute_transport(args: argparse.Namespace, transport: str, cases: list[dict[str, str]], repo: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    client, command, port = start_client(args, transport)
    request_id = 3
    started_at = time.perf_counter()
    try:
        initialize, initialized, tools = initialize_client(client, transport, args.startup_timeout)
        for row in cases:
            case_started = time.perf_counter()
            find_args = json.loads(row["find_symbol_args_json"])
            ref_args = json.loads(row["reference_args_json"])
            if mcp_probe.response_error(tools):
                find_response = {"error": {"message": "tools/list failed"}}
                reference_response = {"error": {"message": "tools/list failed"}}
            else:
                find_response = client.request(make_tool_call("find_symbol", find_args, request_id))
                request_id += 1
                reference_response = client.request(make_tool_call("find_referencing_symbols", ref_args, request_id))
                request_id += 1
            studio_result = run_studio_usages(row, repo, args.studio_timeout)
            find_text = tool_text(find_response)
            reference_text = tool_text(reference_response)
            studio_text = f"{studio_result.get('stdout', '')}\n{studio_result.get('stderr', '')}"
            serena_reference_paths = extract_paths(reference_text, repo)
            studio_paths = extract_paths(studio_text, repo)
            expected_studio_files = set(json.loads(row["expected_studio_files_json"]))
            classification = classify_case(find_response, reference_response, studio_result, serena_reference_paths, studio_paths)
            rows.append(
                {
                    "case_id": row["case_id"],
                    "transport": transport,
                    "symbol_label": row["symbol_label"],
                    "classification": classification,
                    "expected_classification": row["expected_classification"],
                    "find_status": response_status(find_response),
                    "reference_status": response_status(reference_response),
                    "studio_status": studio_result["status"],
                    "serena_reference_empty": text_is_empty_semantic_result(reference_text),
                    "serena_reference_paths": sorted(serena_reference_paths),
                    "studio_paths": sorted(studio_paths),
                    "overlap_paths": sorted(serena_reference_paths & studio_paths),
                    "expected_studio_files_found": sorted(expected_studio_files & studio_paths),
                    "expected_studio_files_missing": sorted(expected_studio_files - studio_paths),
                    "tool_count": mcp_probe.tool_count(tools),
                    "wall_seconds": time.perf_counter() - case_started,
                    "estimated_tokens": estimate_tokens(find_text + reference_text + studio_text),
                    "byte_count": len((find_text + reference_text + studio_text).encode()),
                    "responses": {
                        "find_symbol": find_response,
                        "find_referencing_symbols": reference_response,
                    },
                    "studio": studio_result,
                }
            )
    finally:
        client.close()
    transport_result = {
        "transport": transport,
        "command": command,
        "port": port,
        "initialize": initialize,
        "initialized": initialized,
        "tools": tools,
        "tool_count": mcp_probe.tool_count(tools),
        "stderr": getattr(client, "stderr_text", ""),
        "wall_seconds": time.perf_counter() - started_at,
    }
    return rows, transport_result


def build_assertions(rows: list[dict[str, Any]], transports: list[dict[str, Any]], before_process: dict[str, Any], after_process: dict[str, Any], max_serena_growth: int) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []

    def add(status: str, check: str, message: str, case_id: str = "") -> None:
        payload: dict[str, Any] = {"status": status, "check": check, "message": message}
        if case_id:
            payload["context"] = {"case_id": case_id}
        assertions.append(payload)

    for transport in transports:
        name = transport["transport"]
        add("pass" if not mcp_probe.response_error(transport["initialize"]) else "fail", f"{name}_initialize", f"{name} initialize")
        add("pass" if transport["tool_count"] >= 10 else "fail", f"{name}_tools_list", f"{name} tool_count={transport['tool_count']}")
        add(
            "pass" if not mcp_probe.transport_error_seen(str(transport["stderr"]) + json.dumps(transport, sort_keys=True, default=str)) else "fail",
            f"{name}_transport_error_absent",
            f"{name} no transport closed/reset markers",
        )

    for row in rows:
        expected = row["expected_classification"]
        classification = row["classification"]
        add(
            "pass" if expected == "probe" or expected == classification else "fail",
            "classification",
            f"expected={expected} actual={classification}",
            row["case_id"],
        )
        add(
            "pass" if row["find_status"] == "pass" else "fail",
            "find_symbol",
            f"find_status={row['find_status']}",
            row["case_id"],
        )
        add(
            "pass" if row["studio_status"] == "pass" else "warn",
            "studio_usages",
            f"studio_status={row['studio_status']}",
            row["case_id"],
        )
        add(
            "pass" if not row["expected_studio_files_missing"] else "warn",
            "studio_expected_file_overlap",
            f"missing={','.join(row['expected_studio_files_missing']) or 'none'}",
            row["case_id"],
        )
        if classification == "fixed":
            add("pass", "serena_studio_reference_overlap", "Serena references overlap Studio usages.", row["case_id"])
        elif classification == "serena-reference-empty-boundary":
            add("warn", "serena_reference_empty_boundary", "Serena references returned empty while Studio usages found expected files.", row["case_id"])
        elif classification == "unclassified disagreement":
            add("warn", "serena_studio_reference_disagreement", "Serena references do not overlap Studio usages.", row["case_id"])
        else:
            add("warn", "serena_reference_boundary", f"classification={classification}", row["case_id"])

    delta = mcp_probe.process_delta(before_process, after_process)
    add(
        "pass" if int(delta.get("serena_mcp", 0)) <= max_serena_growth else "fail",
        "serena_process_growth",
        f"serena_mcp_delta={delta.get('serena_mcp', 0)} max={max_serena_growth}",
    )
    add(
        "pass" if int(delta.get("kotlin_lsp", 0)) <= 1 else "warn",
        "kotlin_lsp_process_growth",
        f"kotlin_lsp_delta={delta.get('kotlin_lsp', 0)}",
    )

    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions, "process_delta": delta}


def write_outputs(output: Path, run_id: str, rows: list[dict[str, Any]], transports: list[dict[str, Any]], summary: dict[str, Any], assertions: dict[str, Any]) -> dict[str, str]:
    output.mkdir(parents=True, exist_ok=True)
    raw_dir = output / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    persisted_rows: list[dict[str, Any]] = []
    for row in rows:
        base = safe_name(f"{row['case_id']}_{row['transport']}")
        response_path = raw_dir / f"{base}.serena.json"
        studio_path = raw_dir / f"{base}.studio.json"
        response_path.write_text(json.dumps(row["responses"], indent=2, sort_keys=True) + "\n")
        studio_path.write_text(json.dumps(row["studio"], indent=2, sort_keys=True) + "\n")
        persisted = {key: value for key, value in row.items() if key not in {"responses", "studio"}}
        for key in ("serena_reference_paths", "studio_paths", "overlap_paths", "expected_studio_files_found", "expected_studio_files_missing"):
            persisted[key] = json.dumps(persisted[key], sort_keys=True)
        persisted["response_path"] = str(response_path)
        persisted["studio_path"] = str(studio_path)
        persisted_rows.append(persisted)

    rows_path = output / f"android-serena-mcp-reference-triage-{run_id}.tsv"
    summary_path = output / f"android-serena-mcp-reference-triage-summary-{run_id}.json"
    assertions_path = output / f"android-serena-mcp-reference-triage-assertions-{run_id}.json"
    transport_path = output / f"android-serena-mcp-reference-triage-transports-{run_id}.json"
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=list(persisted_rows[0].keys()))
        writer.writeheader()
        writer.writerows(persisted_rows)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n")
    transport_path.write_text(json.dumps(transports, indent=2, sort_keys=True, default=str) + "\n")
    return {"rows": str(rows_path), "summary": str(summary_path), "assertions": str(assertions_path), "transports": str(transport_path), "raw_dir": str(raw_dir)}


def run(args: argparse.Namespace, cases: list[dict[str, str]]) -> int:
    selected_transports = set(args.transports.split(",")) if args.transports else mcp_probe.SUPPORTED_TRANSPORTS
    cases = [row for row in cases if row["transport"] in selected_transports]
    repo = Path(args.repo).expanduser().resolve()
    before_process = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=str(repo),
        expected_serena_mcp_count=args.expected_serena_mcp_count,
        allow_http_serena_server=True,
    )
    all_rows: list[dict[str, Any]] = []
    transports: list[dict[str, Any]] = []
    for transport in sorted(selected_transports):
        transport_cases = [row for row in cases if row["transport"] == transport]
        if not transport_cases:
            continue
        rows, transport_result = execute_transport(args, transport, transport_cases, repo)
        all_rows.extend(rows)
        transports.append(transport_result)
        time.sleep(args.cooldown_seconds)
    after_process = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=str(repo),
        expected_serena_mcp_count=args.expected_serena_mcp_count,
        allow_http_serena_server=True,
    )
    assertions = build_assertions(all_rows, transports, before_process, after_process, args.max_serena_growth)
    classification_counts: dict[str, int] = {}
    for row in all_rows:
        classification_counts[row["classification"]] = classification_counts.get(row["classification"], 0) + 1
    run_id = stamp()
    summary = {
        "schema": "agent-code-router-kit.android-serena-mcp-reference-triage.v1",
        "date_utc": utc_now(),
        "scope": "Sample B2B stable direct MCP reference-disagreement triage, not Android completion",
        "repo": str(repo),
        "case_count": len(all_rows),
        "transports": sorted(selected_transports),
        "classification_counts": classification_counts,
        "assertions": assertions["summary"],
        "process_delta": assertions["process_delta"],
        "cases": [
            {
                "case_id": row["case_id"],
                "transport": row["transport"],
                "symbol_label": row["symbol_label"],
                "classification": row["classification"],
                "find_status": row["find_status"],
                "reference_status": row["reference_status"],
                "studio_status": row["studio_status"],
                "overlap_paths": row["overlap_paths"],
                "expected_studio_files_missing": row["expected_studio_files_missing"],
                "wall_seconds": row["wall_seconds"],
            }
            for row in all_rows
        ],
    }
    paths = write_outputs(Path(args.output).expanduser().resolve(), run_id, all_rows, transports, summary, assertions)
    counts = assertions["summary"]
    print(f"Wrote {paths['rows']}")
    print(f"Wrote {paths['summary']}")
    print(f"Wrote {paths['assertions']}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}; classifications={classification_counts}")
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Triages Serena direct MCP references against Android Studio usages for Android.")
    parser.add_argument("--cases", default="benchmarks/android/serena-mcp-reference-triage.sample-b2b.tsv")
    parser.add_argument("--repo", default="")
    parser.add_argument("--output", default="results/android/serena-mcp-reference-triage")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--transports", default="stdio,streamable-http")
    parser.add_argument("--serena-command", default="serena")
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--startup-timeout", type=float, default=90)
    parser.add_argument("--studio-timeout", type=float, default=120)
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
    selected_transports = set(args.transports.split(",")) if args.transports else mcp_probe.SUPPORTED_TRANSPORTS
    invalid = sorted(selected_transports - mcp_probe.SUPPORTED_TRANSPORTS)
    if invalid:
        parser.error(f"unsupported transports: {', '.join(invalid)}")
    if min(args.timeout, args.startup_timeout, args.studio_timeout, args.tool_timeout) <= 0:
        parser.error("timeouts must be > 0")

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
