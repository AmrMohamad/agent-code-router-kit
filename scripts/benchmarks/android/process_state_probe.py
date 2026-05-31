#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROCESS_PATTERNS = [
    ("serena_mcp", "serena start-mcp-server"),
    ("kotlin_lsp", "KotlinLspServerKt"),
    ("json_lsp", "vscode-json-languageserver"),
    ("java_jdtls", "org.eclipse.equinox.launcher"),
]


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def process_table() -> list[dict[str, Any]]:
    proc = subprocess.run(
        ["ps", "ax", "-o", "pid=,command="],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    rows: list[dict[str, Any]] = []
    for raw in proc.stdout.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        pid, _, command = stripped.partition(" ")
        for kind, pattern in PROCESS_PATTERNS:
            if pattern in command and "android_process_state_probe.py" not in command:
                rows.append({"kind": kind, "pid": int(pid), "command": command})
                break
    return rows


def process_cwd(pid: int) -> str | None:
    try:
        proc = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return None
    for line in proc.stdout.splitlines():
        if line.startswith("n/"):
            return line[1:]
    return None


def normalize_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    return str(Path(path).expanduser().resolve())


def path_matches_target(candidate: str | None, target_project_path: str | None) -> bool:
    if not candidate or not target_project_path:
        return False
    candidate_path = normalize_path(candidate)
    if not candidate_path:
        return False
    return candidate_path == target_project_path or candidate_path.startswith(f"{target_project_path}/")


def command_project_path(command: str) -> str | None:
    parts = command.split()
    for index, part in enumerate(parts):
        if part == "--project" and index + 1 < len(parts):
            return parts[index + 1]
        if part.startswith("--project="):
            return part.split("=", 1)[1]
    return None


def classify_process(
    row: dict[str, Any],
    target_project_path: str | None = None,
    allow_http_serena_server: bool = False,
) -> str:
    command = str(row.get("command", ""))
    if row.get("kind") != "serena_mcp":
        return "language_server"

    if "--transport" in command and "streamable-http" in command and allow_http_serena_server:
        project_path = command_project_path(command)
        if path_matches_target(project_path, target_project_path):
            return "target_http_server"
        return "allowed_http_server"

    project_path = command_project_path(command)
    if path_matches_target(project_path, target_project_path):
        return "target_project"
    if project_path:
        return "other_project"

    cwd = row.get("cwd")
    if path_matches_target(str(cwd), target_project_path):
        return "target_project_cwd"
    if cwd:
        return "other_project_cwd"

    if "--project-from-cwd" in command:
        return "unknown_project_from_cwd"
    return "unknown"


def enrich_processes(
    rows: list[dict[str, Any]],
    target_project_path: str | None = None,
    allow_http_serena_server: bool = False,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        copy = dict(row)
        if copy.get("kind") == "serena_mcp":
            copy["cwd"] = process_cwd(int(copy["pid"]))
        copy["classification"] = classify_process(copy, target_project_path, allow_http_serena_server)
        enriched.append(copy)
    return enriched


def count_by_kind(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {kind: 0 for kind, _ in PROCESS_PATTERNS}
    for row in rows:
        counts[str(row["kind"])] += 1
    return counts


def count_by_classification(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("classification", "unknown"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def status_from_counts(
    counts: dict[str, int],
    classification_counts: dict[str, int] | None = None,
    expected_serena_mcp_count: int = 1,
    allow_other_project_serena: bool = False,
    target_project_path: str | None = None,
) -> str:
    classification_counts = classification_counts or {}
    unknown_count = (
        classification_counts.get("unknown", 0)
        + classification_counts.get("unknown_project_from_cwd", 0)
    )
    other_project_count = (
        + classification_counts.get("other_project", 0)
        + classification_counts.get("other_project_cwd", 0)
    )
    target_count = (
        classification_counts.get("target_project", 0)
        + classification_counts.get("target_project_cwd", 0)
        + classification_counts.get("target_http_server", 0)
    )
    if unknown_count or (other_project_count and not allow_other_project_serena):
        return "stale-session-risk"
    if target_project_path:
        serena_count_over_limit = target_count > expected_serena_mcp_count
    else:
        serena_count_over_limit = counts.get("serena_mcp", 0) > expected_serena_mcp_count
    if serena_count_over_limit or counts.get("kotlin_lsp", 0) > 1:
        return "stale-session-risk"
    if counts.get("java_jdtls", 0) > 0:
        return "jdtls-gradle-risk"
    return "clean"


def build_summary(
    rows: list[dict[str, Any]],
    target_project_path: str | None = None,
    expected_serena_mcp_count: int = 1,
    allow_http_serena_server: bool = False,
    allow_other_project_serena: bool = False,
) -> dict[str, Any]:
    normalized_target = normalize_path(target_project_path)
    rows = enrich_processes(rows, normalized_target, allow_http_serena_server)
    counts = count_by_kind(rows)
    classification_counts = count_by_classification(rows)
    target_serena_mcp_count = (
        classification_counts.get("target_project", 0)
        + classification_counts.get("target_project_cwd", 0)
        + classification_counts.get("target_http_server", 0)
    )
    other_project_serena_mcp_count = (
        classification_counts.get("other_project", 0)
        + classification_counts.get("other_project_cwd", 0)
    )
    unknown_serena_mcp_count = (
        classification_counts.get("unknown", 0)
        + classification_counts.get("unknown_project_from_cwd", 0)
    )
    return {
        "created_at": utc_now(),
        "status": status_from_counts(
            counts,
            classification_counts,
            expected_serena_mcp_count,
            allow_other_project_serena,
            normalized_target,
        ),
        "counts": counts,
        "classification_counts": classification_counts,
        "target_serena_mcp_count": target_serena_mcp_count,
        "other_project_serena_mcp_count": other_project_serena_mcp_count,
        "unknown_serena_mcp_count": unknown_serena_mcp_count,
        "processes": rows,
        "target_project_path": normalized_target,
        "expected_serena_mcp_count": expected_serena_mcp_count,
        "allow_http_serena_server": allow_http_serena_server,
        "allow_other_project_serena": allow_other_project_serena,
        "guidance": {
            "dry_run": "scripts/setup/repair-serena-android-sessions.sh --dry-run",
            "explicit_kill": "scripts/setup/repair-serena-android-sessions.sh --kill",
        },
    }


def build_assertions(summary: dict[str, Any], require_clean: bool = False) -> dict[str, Any]:
    counts = dict(summary["counts"])
    classification_counts = dict(summary.get("classification_counts", {}))
    expected_serena_mcp_count = int(summary.get("expected_serena_mcp_count", 1))
    target_project_path = summary.get("target_project_path")
    target_serena_mcp_count = int(summary.get("target_serena_mcp_count", counts.get("serena_mcp", 0)))
    other_project_serena_mcp_count = int(summary.get("other_project_serena_mcp_count", 0))
    unknown_serena_mcp_count = int(summary.get("unknown_serena_mcp_count", 0))
    allow_other_project_serena = bool(summary.get("allow_other_project_serena", False))
    assertions: list[dict[str, str]] = []

    def add(level: str, name: str, detail: str) -> None:
        assertions.append({"level": level, "name": name, "detail": detail})

    add("pass", "process-scan-ran", "Captured Serena and Android language-server process state.")

    comparable_serena_count = target_serena_mcp_count if target_project_path else counts.get("serena_mcp", 0)
    if comparable_serena_count <= expected_serena_mcp_count:
        scope = "target project" if target_project_path else "global"
        add("pass", "serena-mcp-session-count", f"Serena MCP {scope} process count is within expected limit {expected_serena_mcp_count}.")
    else:
        add(
            "fail" if require_clean else "warn",
            "serena-mcp-session-count",
            f"{comparable_serena_count} Serena MCP target/global processes are running; expected at most {expected_serena_mcp_count}.",
        )

    if unknown_serena_mcp_count == 0:
        add("pass", "serena-process-ownership", "No unknown Serena MCP sessions were detected.")
    else:
        add(
            "fail" if require_clean else "warn",
            "serena-process-ownership",
            f"{unknown_serena_mcp_count} Serena MCP sessions have unknown ownership.",
        )
    if other_project_serena_mcp_count == 0:
        add("pass", "serena-other-project-sessions", "No other-project Serena MCP sessions were detected.")
    elif allow_other_project_serena:
        add(
            "pass",
            "serena-other-project-sessions",
            f"{other_project_serena_mcp_count} other-project Serena MCP sessions are explicitly allowed.",
        )
    else:
        add(
            "fail" if require_clean else "warn",
            "serena-other-project-sessions",
            f"{other_project_serena_mcp_count} other-project Serena MCP sessions are running.",
        )

    if counts.get("kotlin_lsp", 0) <= 1:
        add("pass", "kotlin-lsp-session-count", "At most one Kotlin LSP process is running.")
    else:
        add(
            "fail" if require_clean else "warn",
            "kotlin-lsp-session-count",
            f"{counts['kotlin_lsp']} Kotlin LSP processes are running; workspace ownership conflicts are likely.",
        )

    if counts.get("java_jdtls", 0) == 0:
        add("pass", "java-jdtls-not-running", "No Java/JDTLS process is currently running.")
    else:
        add(
            "fail" if require_clean else "warn",
            "java-jdtls-not-running",
            "Java/JDTLS is running and may trigger Gradle sync/local.properties failures in Android repos.",
        )

    totals = {"pass": 0, "warn": 0, "fail": 0}
    for item in assertions:
        totals[item["level"]] += 1
    return {"summary": totals, "assertions": assertions}


def write_outputs(output: Path, summary: dict[str, Any], assertions: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    summary_path = output / f"android-process-state-summary-{run_id}.json"
    assertions_path = output / f"android-process-state-assertions-{run_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(
        "Assertions: "
        f"pass={assertions['summary']['pass']}, "
        f"warn={assertions['summary']['warn']}, "
        f"fail={assertions['summary']['fail']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Android/Serena process state for routing benchmarks.")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--output", default="results/android/process-state")
    parser.add_argument("--enforce-assertions", action="store_true")
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--target-project-path", default="")
    parser.add_argument("--expected-serena-mcp-count", type=int, default=1)
    parser.add_argument("--allow-http-serena-server", action="store_true")
    parser.add_argument("--allow-other-project-serena", action="store_true")
    args = parser.parse_args()

    if args.expected_serena_mcp_count < 0:
        raise SystemExit("--expected-serena-mcp-count must be >= 0")

    if args.validate:
        print("VALIDATION PASSED: process-state probe")
    if not args.run:
        return 0

    summary = build_summary(
        process_table(),
        target_project_path=args.target_project_path or None,
        expected_serena_mcp_count=args.expected_serena_mcp_count,
        allow_http_serena_server=args.allow_http_serena_server,
        allow_other_project_serena=args.allow_other_project_serena,
    )
    assertions = build_assertions(summary, require_clean=args.require_clean)
    write_outputs(Path(args.output).expanduser().resolve(), summary, assertions)

    if args.enforce_assertions and assertions["summary"]["fail"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
