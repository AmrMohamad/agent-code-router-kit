#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


REQUIRED_COLUMNS = [
    "case_id",
    "repo",
    "category",
    "tool",
    "command_label",
    "metric_mode",
    "command",
    "expected_first_tool",
    "purpose",
]

VALID_TOOLS = {"rg", "fd", "ast-grep"}
VALID_METRIC_MODES = {"path_lines", "rg_lines", "rg_count", "rg_json", "ast_grep"}
DISALLOWED_TOOL_ARGS = {
    "fd": {"-x", "--exec", "-X", "--exec-batch"},
    "rg": {"--pre"},
    "ast-grep": {"-r", "--rewrite", "--update-all", "--interactive"},
}

RG_PATH_RE = re.compile(r"^(?P<path>.*?):\d+(?::\d+)?:")
AST_GREP_PATH_RE = re.compile(r"^(?P<path>.*?):\d+:")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def split_command(command: str) -> list[str]:
    return shlex.split(command)


def validate_safe_argv(argv: list[str], line: int) -> list[str]:
    if not argv:
        return []
    tool = argv[0]
    disallowed = DISALLOWED_TOOL_ARGS.get(tool, set())
    errors = []
    for arg in argv[1:]:
        flag = arg.split("=", 1)[0]
        if flag in disallowed:
            errors.append(f"line {line}: {tool} argument {flag!r} is not allowed in read-only benchmark manifests")
    return errors


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise SystemExit(
                "case manifest schema mismatch\n"
                f"expected: {REQUIRED_COLUMNS}\n"
                f"actual:   {reader.fieldnames}"
            )
        rows = list(reader)
    if not rows:
        raise SystemExit("case manifest has no rows")
    return rows


def parse_repo_args(values: list[str]) -> dict[str, Path]:
    repos: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--repo must be name=/path, got: {value}")
        name, raw_path = value.split("=", 1)
        if not name:
            raise SystemExit(f"--repo name is empty: {value}")
        repos[name] = Path(raw_path).expanduser().resolve()
    return repos


def repo_from_env() -> dict[str, Path]:
    raw = os.environ.get("AGENT_ROUTER_REPOS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"AGENT_ROUTER_REPOS must be JSON object: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("AGENT_ROUTER_REPOS must be a JSON object")
    return {str(k): Path(str(v)).expanduser().resolve() for k, v in data.items()}


def validate_cases(cases: list[dict[str, str]], repos: dict[str, Path], require_repos: bool) -> list[str]:
    errors: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    for i, row in enumerate(cases, start=2):
        for col in REQUIRED_COLUMNS:
            if not row.get(col):
                errors.append(f"line {i}: missing {col}")
        if row.get("tool") not in VALID_TOOLS:
            errors.append(f"line {i}: unexpected tool {row.get('tool')!r}")
        if row.get("metric_mode") not in VALID_METRIC_MODES:
            errors.append(f"line {i}: invalid metric_mode {row.get('metric_mode')!r}")
        try:
            argv = split_command(row.get("command", ""))
        except ValueError as exc:
            errors.append(f"line {i}: invalid command quoting: {exc}")
            argv = []
        if argv and argv[0] != row.get("tool"):
            errors.append(f"line {i}: command must start with declared tool")
        errors.extend(validate_safe_argv(argv, i))
        key = (row.get("repo", ""), row.get("case_id", ""), row.get("tool", ""), row.get("command_label", ""))
        if key in seen:
            errors.append(f"line {i}: duplicate case key {key}")
        seen.add(key)
        if require_repos:
            repo_name = row.get("repo", "")
            if repo_name not in repos:
                errors.append(f"line {i}: repo {repo_name!r} not provided")
            elif not repos[repo_name].exists():
                errors.append(f"line {i}: repo path missing for {repo_name}: {repos[repo_name]}")
        policy = expected_policy_for(row)
        if policy and not expected_matches(row.get("expected_first_tool", ""), policy):
            errors.append(
                f"line {i}: expected_first_tool {row.get('expected_first_tool')!r} "
                f"does not match policy {policy!r}"
            )
    return errors


def expected_policy_for(row: dict[str, str]) -> str:
    category = row["category"]
    case_id = row["case_id"]
    if category == "known_swift_symbol":
        return "lsp_summary" if "high_fanout" in case_id else "lsp"
    if category == "structural_swift_pattern":
        return "ast-grep"
    if category in {"literal_key", "literal_surface", "resource_surface", "generated_surface", "dynamic_surface"}:
        return "rg_fd"
    if category == "discovery":
        return "fd"
    return ""


def expected_matches(expected: str, policy: str) -> bool:
    value = expected.lower().strip()
    if policy == "lsp":
        return "lsp" in value or "serena" in value or "sourcekit" in value
    if policy == "lsp_summary":
        return ("lsp" in value or "serena" in value or "sourcekit" in value) and "summary" in value
    if policy == "ast-grep":
        return "ast-grep" in value
    if policy == "fd":
        return value.startswith("fd")
    if policy == "rg_fd":
        return "rg" in value or "fd" in value
    return True


def safe_name(*parts: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", "_".join(parts)).strip("_")


def parse_rg_lines(text: str) -> set[str]:
    paths: set[str] = set()
    for line in text.splitlines():
        match = RG_PATH_RE.match(line)
        if match:
            paths.add(match.group("path"))
    return paths


def parse_rg_count(text: str) -> tuple[set[str], int]:
    paths: set[str] = set()
    matches = 0
    for line in text.splitlines():
        if ":" not in line:
            continue
        path, count_text = line.rsplit(":", 1)
        paths.add(path)
        try:
            matches += int(count_text)
        except ValueError:
            pass
    return paths, matches


def parse_rg_json(text: str) -> tuple[set[str], int, int]:
    paths: set[str] = set()
    matches = 0
    parse_errors = 0
    for line in text.splitlines():
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if obj.get("type") != "match":
            continue
        matches += 1
        path_text = (((obj.get("data") or {}).get("path") or {}).get("text"))
        if path_text:
            paths.add(path_text)
    return paths, matches, parse_errors


def parse_ast_grep(text: str) -> set[str]:
    paths: set[str] = set()
    for line in text.splitlines():
        match = AST_GREP_PATH_RE.match(line)
        if match:
            paths.add(match.group("path"))
    return paths


def measure(mode: str, output: str) -> dict[str, int]:
    lines = output.splitlines()
    byte_count = len(output.encode())
    if mode == "path_lines":
        nonempty = [line for line in lines if line.strip()]
        return {
            "line_count": len(lines),
            "byte_count": byte_count,
            "unique_file_count": len(nonempty),
            "match_count": len(nonempty),
            "parse_error_count": 0,
        }
    if mode == "rg_lines":
        paths = parse_rg_lines(output)
        return {
            "line_count": len(lines),
            "byte_count": byte_count,
            "unique_file_count": len(paths),
            "match_count": len(lines),
            "parse_error_count": 0,
        }
    if mode == "rg_count":
        paths, matches = parse_rg_count(output)
        return {
            "line_count": len(lines),
            "byte_count": byte_count,
            "unique_file_count": len(paths),
            "match_count": matches,
            "parse_error_count": 0,
        }
    if mode == "rg_json":
        paths, matches, errors = parse_rg_json(output)
        return {
            "line_count": len(lines),
            "byte_count": byte_count,
            "unique_file_count": len(paths),
            "match_count": matches,
            "parse_error_count": errors,
        }
    if mode == "ast_grep":
        paths = parse_ast_grep(output)
        return {
            "line_count": len(lines),
            "byte_count": byte_count,
            "unique_file_count": len(paths),
            "match_count": len(lines),
            "parse_error_count": 0,
        }
    raise ValueError(f"unsupported mode: {mode}")


def text_from_timeout(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def execute(row: dict[str, str], repo_path: Path, timeout: float) -> dict[str, Any]:
    argv = split_command(row["command"])
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            cwd=repo_path,
            shell=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        wall = time.perf_counter() - start
        return {
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "exit_code": proc.returncode,
            "timed_out": False,
            "wall_seconds": wall,
            "argv": argv,
        }
    except subprocess.TimeoutExpired as exc:
        wall = time.perf_counter() - start
        return {
            "stdout": text_from_timeout(exc.stdout),
            "stderr": text_from_timeout(exc.stderr),
            "exit_code": 124,
            "timed_out": True,
            "wall_seconds": wall,
            "argv": argv,
        }
    except FileNotFoundError as exc:
        wall = time.perf_counter() - start
        return {
            "stdout": "",
            "stderr": str(exc),
            "exit_code": 127,
            "timed_out": False,
            "wall_seconds": wall,
            "argv": argv,
        }


def run_case(
    row: dict[str, str],
    repo_path: Path,
    output_root: Path,
    run_id: str,
    pass_index: int,
    cache_label: str,
    timeout: float,
) -> dict[str, Any]:
    raw_dir = output_root / "raw" / run_id / f"pass-{pass_index}"
    raw_dir.mkdir(parents=True, exist_ok=True)
    base = safe_name(row["repo"], row["case_id"], row["tool"], row["command_label"])
    stdout_path = raw_dir / f"{base}.stdout"
    stderr_path = raw_dir / f"{base}.stderr"

    result = execute(row, repo_path, timeout)
    stdout_path.write_text(result["stdout"])
    stderr_path.write_text(result["stderr"])
    metrics = measure(row["metric_mode"], result["stdout"])
    return {
        "pass_index": pass_index,
        "cache_label": cache_label,
        "repo": row["repo"],
        "case_id": row["case_id"],
        "category": row["category"],
        "tool": row["tool"],
        "command_label": row["command_label"],
        "metric_mode": row["metric_mode"],
        "expected_first_tool": row["expected_first_tool"],
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "timeout_seconds": timeout,
        "wall_seconds": f"{result['wall_seconds']:.6f}",
        **metrics,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "command": row["command"],
        "command_argv": json.dumps(result["argv"]),
    }


def write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "pass_index",
        "cache_label",
        "repo",
        "case_id",
        "category",
        "tool",
        "command_label",
        "metric_mode",
        "expected_first_tool",
        "exit_code",
        "timed_out",
        "timeout_seconds",
        "wall_seconds",
        "line_count",
        "byte_count",
        "unique_file_count",
        "match_count",
        "parse_error_count",
        "stdout_path",
        "stderr_path",
        "command",
        "command_argv",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["repo"], row["case_id"], row["tool"], row["command_label"])].append(row)
    summary = []
    for (repo, case_id, tool, label), group in sorted(grouped.items()):
        walls = [float(row["wall_seconds"]) for row in group]
        last = group[-1]
        summary.append(
            {
                "repo": repo,
                "case_id": case_id,
                "tool": tool,
                "command_label": label,
                "passes": len(group),
                "exit_codes": sorted({int(row["exit_code"]) for row in group}),
                "timeout_count": sum(1 for row in group if row["timed_out"]),
                "best_wall_seconds": min(walls),
                "avg_wall_seconds": mean(walls),
                "median_wall_seconds": median(walls),
                "last_line_count": int(last["line_count"]),
                "last_byte_count": int(last["byte_count"]),
                "last_unique_file_count": int(last["unique_file_count"]),
                "last_match_count": int(last["match_count"]),
                "last_parse_error_count": int(last["parse_error_count"]),
                "metric_mode": last["metric_mode"],
                "expected_first_tool": last["expected_first_tool"],
                "category": last["category"],
            }
        )
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


def write_assertions(path: Path, rows: list[dict[str, Any]], large_output_bytes: int) -> tuple[int, int, int]:
    assertions: list[dict[str, Any]] = []
    for row in rows:
        context = {
            "repo": row["repo"],
            "case_id": row["case_id"],
            "command_label": row["command_label"],
            "pass_index": row["pass_index"],
        }
        checks = [
            ("command_exit_zero", int(row["exit_code"]) == 0, f"exit={row['exit_code']}"),
            ("command_did_not_timeout", not bool(row["timed_out"]), f"timeout={row['timed_out']}"),
            ("parser_had_no_errors", int(row["parse_error_count"]) == 0, f"parse_errors={row['parse_error_count']}"),
        ]
        for name, ok, message in checks:
            assertions.append(
                {
                    "status": "pass" if ok else "fail",
                    "check": name,
                    "message": message,
                    "context": context,
                }
            )
        if int(row["byte_count"]) > large_output_bytes:
            assertions.append(
                {
                    "status": "warn",
                    "check": "large_output_requires_summary_first",
                    "message": f"bytes={row['byte_count']}",
                    "context": context,
                }
            )
        if "high_fanout" in row["case_id"] and row["command_label"].startswith(("raw_", "json_")):
            assertions.append(
                {
                    "status": "warn",
                    "check": "high_fanout_raw_or_json_is_benchmark_only",
                    "message": "live agent work should request grouped semantic counts first",
                    "context": context,
                }
            )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    payload = {
        "schema": "agent-code-router-kit.policy-assertions.v1",
        "date_utc": utc_now(),
        "summary": counts,
        "assertions": assertions,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return counts["pass"], counts["warn"], counts["fail"]


def short_text(path_text: str, limit: int = 500) -> str:
    text = Path(path_text).read_text(errors="replace").strip()
    text = text.replace("\n", "\\n")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def run(args: argparse.Namespace, cases: list[dict[str, str]], repos: dict[str, Path]) -> int:
    output_root = Path(args.output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = stamp()

    for _ in range(args.warmups):
        for row in cases:
            execute(row, repos[row["repo"]], args.timeout)

    rows: list[dict[str, Any]] = []
    for pass_index in range(1, args.repeats + 1):
        label = "first_observed_after_warmup" if pass_index == 1 and args.warmups else "repeat_warm"
        if pass_index == 1 and not args.warmups:
            label = "first_observed"
        for row in cases:
            rows.append(run_case(row, repos[row["repo"]], output_root, run_id, pass_index, label, args.timeout))

    tsv_path = output_root / f"default-search-{run_id}.tsv"
    summary_path = output_root / f"summary-{run_id}.json"
    assertions_path = output_root / f"policy-assertions-{run_id}.json"
    environment_path = output_root / f"environment-{run_id}.json"
    write_tsv(tsv_path, rows)
    write_summary(summary_path, rows)
    pass_count, warn_count, fail_count = write_assertions(assertions_path, rows, args.large_output_bytes)
    environment_path.write_text(
        json.dumps(
            {
                "schema": "agent-code-router-kit.environment.v1",
                "date_utc": utc_now(),
                "repeats": args.repeats,
                "warmups": args.warmups,
                "timeout_seconds": args.timeout,
                "repos": {name: str(path) for name, path in repos.items()},
                "notes": [
                    "Commands use shell=False.",
                    "Benchmark is read-only.",
                    "No build, test, simulator, or runtime proof is claimed.",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"Wrote {tsv_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(f"Wrote {environment_path}")
    print(f"Policy assertions: pass={pass_count}, warn={warn_count}, fail={fail_count}")
    if fail_count:
        print("Failed assertion details:")
        details = json.loads(assertions_path.read_text())
        rows_by_context = {
            (row["repo"], row["case_id"], row["command_label"], row["pass_index"]): row
            for row in rows
        }
        for item in details["assertions"]:
            if item["status"] == "fail":
                print(f"- {item['check']}: {item['message']} {item['context']}")
                context = item["context"]
                row = rows_by_context.get(
                    (
                        context["repo"],
                        context["case_id"],
                        context["command_label"],
                        context["pass_index"],
                    )
                )
                if row:
                    print(f"  command: {row['command']}")
                    print(f"  stdout: {short_text(row['stdout_path'])}")
                    print(f"  stderr: {short_text(row['stderr_path'])}")
    return 3 if args.enforce_assertions and fail_count else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a public Swift/iOS agent routing benchmark.")
    parser.add_argument("--cases", required=True, help="Path to TSV case manifest.")
    parser.add_argument("--repo", action="append", default=[], help="Repo mapping in the form name=/path.")
    parser.add_argument("--output", default="results", help="Output directory.")
    parser.add_argument("--validate", action="store_true", help="Validate cases and optional repo mappings.")
    parser.add_argument("--run", action="store_true", help="Run benchmark cases.")
    parser.add_argument("--repeats", type=int, default=3, help="Measured passes.")
    parser.add_argument("--warmups", type=int, default=0, help="Unrecorded warmup passes.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-command timeout in seconds.")
    parser.add_argument("--large-output-bytes", type=int, default=100000, help="Warn when output exceeds this size.")
    parser.add_argument("--enforce-assertions", action="store_true", help="Exit non-zero on assertion failures.")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    if args.warmups < 0:
        parser.error("--warmups must be >= 0")
    if args.timeout <= 0:
        parser.error("--timeout must be > 0")

    cases = load_cases(Path(args.cases))
    repos = {**repo_from_env(), **parse_repo_args(args.repo)}
    errors = validate_cases(cases, repos, require_repos=args.run)
    if errors:
        print("VALIDATION FAILED", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases")
    if args.run:
        return run(args, cases, repos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
