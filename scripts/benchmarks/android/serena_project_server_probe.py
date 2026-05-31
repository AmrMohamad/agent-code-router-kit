#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from statistics import mean, median


REQUIRED_COLUMNS = [
    "case_id",
    "repo",
    "project",
    "tool_name",
    "tool_params_json",
    "expected_status",
    "min_byte_count",
    "purpose",
]
VALID_TOOLS = {"find_symbol", "find_referencing_symbols", "find_implementations", "get_symbols_overview", "get_diagnostics_for_file"}
VALID_STATUSES = {"pass", "probe", "empty", "error", "timeout"}
MAX_ANSWER_CHARS_LIMIT = 6000


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise SystemExit(f"schema mismatch: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise SystemExit("case manifest is empty")
    return rows


def parse_repo_args(values: list[str]) -> dict[str, Path]:
    repos: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--repo must be name=/path, got {value!r}")
        name, raw = value.split("=", 1)
        repos[name] = Path(raw).expanduser().resolve()
    return repos


def validate(cases: list[dict[str, str]], repos: dict[str, Path], require_repos: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(cases, start=2):
        for column in REQUIRED_COLUMNS:
            if column not in row or not row[column]:
                errors.append(f"line {index}: missing {column}")
        case_id = row.get("case_id", "")
        if case_id in seen:
            errors.append(f"line {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        if row.get("tool_name") not in VALID_TOOLS:
            errors.append(f"line {index}: invalid tool_name {row.get('tool_name')!r}")
        if row.get("expected_status") not in VALID_STATUSES:
            errors.append(f"line {index}: invalid expected_status {row.get('expected_status')!r}")
        params: dict[str, object] | None = None
        try:
            decoded_params = json.loads(row.get("tool_params_json", ""))
            if not isinstance(decoded_params, dict):
                errors.append(f"line {index}: tool_params_json must decode to an object")
            else:
                params = decoded_params
        except json.JSONDecodeError as exc:
            errors.append(f"line {index}: invalid tool_params_json: {exc}")
        if params is not None:
            max_answer_chars = params.get("max_answer_chars")
            if not isinstance(max_answer_chars, int):
                errors.append(f"line {index}: max_answer_chars is required and must be an integer")
            elif max_answer_chars <= 0 or max_answer_chars > MAX_ANSWER_CHARS_LIMIT:
                errors.append(
                    f"line {index}: max_answer_chars must be between 1 and {MAX_ANSWER_CHARS_LIMIT}"
                )
            if row.get("tool_name") == "find_symbol":
                max_matches = params.get("max_matches")
                if max_matches is not None and (not isinstance(max_matches, int) or max_matches <= 0 or max_matches > 10):
                    errors.append(f"line {index}: find_symbol max_matches must be an integer between 1 and 10")
        try:
            if int(row.get("min_byte_count", "")) < 0:
                errors.append(f"line {index}: min_byte_count must be >= 0")
        except ValueError:
            errors.append(f"line {index}: min_byte_count must be an integer")
        if require_repos:
            repo = row.get("repo", "")
            if repo not in repos:
                errors.append(f"line {index}: repo {repo!r} not provided")
            elif not repos[repo].exists():
                errors.append(f"line {index}: repo path missing: {repos[repo]}")
    return errors


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("_")


def request_text(port: int, path: str, payload: dict[str, object] | None = None, timeout: float = 30) -> str:
    url = f"http://127.0.0.1:{port}{path}"
    if payload is None:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode(errors="replace")
    data = json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode(errors="replace")


def wait_for_server(port: int, timeout: float) -> None:
    deadline = time.perf_counter() + timeout
    last_error: Exception | None = None
    while time.perf_counter() < deadline:
        try:
            request_text(port, "/heartbeat", timeout=2)
            return
        except Exception as exc:  # noqa: BLE001 - surface final connection error.
            last_error = exc
            time.sleep(0.5)
    raise TimeoutError(f"Serena ProjectServer did not become ready on port {port}: {last_error}")


def start_server(port: int, startup_timeout: float) -> subprocess.Popen[str]:
    proc = subprocess.Popen(
        ["serena", "start-project-server", "--port", str(port), "--log-level", "WARNING"],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_server(port, startup_timeout)
    except Exception:
        proc.terminate()
        raise
    return proc


def stop_server(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def classify(text: str, error: str, timed_out: bool, min_byte_count: int) -> str:
    if timed_out:
        return "timeout"
    if error or "Error executing tool:" in text:
        return "error"
    if len(text.encode()) < min_byte_count:
        return "empty"
    return "pass"


def execute(row: dict[str, str], port: int, timeout: float) -> dict[str, object]:
    params = json.loads(row["tool_params_json"])
    payload = {
        "project_name": row["project"],
        "tool_name": row["tool_name"],
        "tool_params_json": json.dumps(params),
    }
    started = time.perf_counter()
    try:
        text = request_text(port, "/query_project", payload=payload, timeout=timeout)
        error = ""
        timed_out = False
    except TimeoutError as exc:
        text = ""
        error = str(exc)
        timed_out = True
    except urllib.error.URLError as exc:
        text = ""
        error = str(exc)
        timed_out = False
    wall = time.perf_counter() - started
    min_bytes = int(row["min_byte_count"])
    combined = text + error
    return {
        "stdout": text,
        "stderr": error,
        "status": classify(text, error, timed_out, min_bytes),
        "timed_out": timed_out,
        "wall_seconds": wall,
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
        "line_count": len(combined.splitlines()),
    }


def build_assertions(rows: list[dict[str, object]], expected_repeats: int | None = None) -> dict[str, object]:
    assertions = []
    for row in rows:
        expected = str(row["expected_status"])
        status = str(row["status"])
        ok = expected == "probe" or expected == status
        assertions.append(
            {
                "status": "pass" if ok else "fail",
                "check": "expected_status",
                "message": f"expected={expected} actual={status}",
                "context": {"repo": row["repo"], "case_id": row["case_id"], "pass_index": row["pass_index"]},
            }
        )
        if int(row["estimated_tokens"]) > 1500:
            assertions.append(
                {
                    "status": "warn",
                    "check": "large_semantic_output",
                    "message": f"estimated_tokens={row['estimated_tokens']}",
                    "context": {"repo": row["repo"], "case_id": row["case_id"], "pass_index": row["pass_index"]},
                }
            )
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault((str(row["repo"]), str(row["case_id"])), []).append(row)
    for (repo, case_id), group in sorted(grouped.items()):
        statuses = sorted({str(row["status"]) for row in group})
        assertions.append(
            {
                "status": "pass" if len(statuses) == 1 else "fail",
                "check": "stable_status",
                "message": f"statuses={','.join(statuses)} measured_passes={len(group)}",
                "context": {"repo": repo, "case_id": case_id},
            }
        )
        if expected_repeats is not None:
            assertions.append(
                {
                    "status": "pass" if len(group) == expected_repeats else "fail",
                    "check": "measured_pass_count",
                    "message": f"expected={expected_repeats} actual={len(group)}",
                    "context": {"repo": repo, "case_id": case_id},
                }
            )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions}


def run(args: argparse.Namespace, cases: list[dict[str, str]]) -> int:
    output_root = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output_root / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    server = start_server(args.port, args.startup_timeout)
    rows: list[dict[str, object]] = []
    try:
        for _ in range(args.warmups):
            for row in cases:
                execute(row, args.port, args.timeout)
        for pass_index in range(1, args.repeats + 1):
            for row in cases:
                result = execute(row, args.port, args.timeout)
                base = safe_name(f"{row['repo']}_{row['case_id']}_pass{pass_index}")
                stdout_path = raw_dir / f"{base}.stdout"
                stderr_path = raw_dir / f"{base}.stderr"
                stdout_path.write_text(str(result["stdout"]))
                stderr_path.write_text(str(result["stderr"]))
                rows.append(
                    {
                        "pass_index": pass_index,
                        "repo": row["repo"],
                        "case_id": row["case_id"],
                        "project": row["project"],
                        "tool_name": row["tool_name"],
                        "expected_status": row["expected_status"],
                        "min_byte_count": int(row["min_byte_count"]),
                        "purpose": row["purpose"],
                        "status": result["status"],
                        "timed_out": result["timed_out"],
                        "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                        "line_count": result["line_count"],
                        "byte_count": result["byte_count"],
                        "estimated_tokens": result["estimated_tokens"],
                        "stdout_path": str(stdout_path),
                        "stderr_path": str(stderr_path),
                    }
                )
    finally:
        stop_server(server)

    rows_path = output_root / f"serena-project-server-{run_id}.tsv"
    summary_path = output_root / f"serena-project-server-summary-{run_id}.json"
    assertions_path = output_root / f"serena-project-server-assertions-{run_id}.json"
    fieldnames = list(rows[0].keys()) if rows else []
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), []).append(row)
    summary = []
    for case_id, group in sorted(grouped.items()):
        walls = [float(row["wall_seconds"]) for row in group]
        last = group[-1]
        summary.append(
            {
                "case_id": case_id,
                "repo": last["repo"],
                "tool_name": last["tool_name"],
                "statuses": sorted({str(row["status"]) for row in group}),
                "best_wall_seconds": min(walls),
                "median_wall_seconds": median(walls),
                "avg_wall_seconds": mean(walls),
                "measured_pass_count": len(group),
                "last_byte_count": int(last["byte_count"]),
                "last_estimated_tokens": int(last["estimated_tokens"]),
                "expected_status": last["expected_status"],
            }
        )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertion_payload = build_assertions(rows, expected_repeats=args.repeats)
    assertions_path.write_text(json.dumps(assertion_payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    counts = assertion_payload["summary"]
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}")
    return 1 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Serena ProjectServer semantic tools for Android/Kotlin repos.")
    parser.add_argument("--cases", default="benchmarks/android/serena-project-server-cases.sample.tsv")
    parser.add_argument("--repo", action="append", default=[])
    parser.add_argument("--output", default="results/android/serena-project-server")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--warmups", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--startup-timeout", type=float, default=30)
    parser.add_argument("--port", type=int, default=24392)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    if args.warmups < 0:
        parser.error("--warmups must be >= 0")
    if args.timeout <= 0 or args.startup_timeout <= 0:
        parser.error("timeouts must be > 0")
    cases = load_cases(Path(args.cases))
    repos = parse_repo_args(args.repo)
    errors = validate(cases, repos, require_repos=bool(args.repo))
    if errors:
        for error in errors:
            print(error)
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases")
    if args.run:
        return run(args, cases)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
