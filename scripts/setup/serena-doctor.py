#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROFILE_LANGUAGES = {
    "android": ["kotlin", "json"],
    "swift-ios": ["swift"],
    "python": ["python"],
    "generic": None,
}

PROCESS_PATTERNS = {
    "serena_mcp": "serena start-mcp-server",
    "kotlin_lsp": "KotlinLspServerKt",
    "json_lsp": "vscode-json-languageserver",
    "java_jdtls": "org.eclipse.jdt",
    "sourcekit_lsp": "sourcekit-lsp",
    "python_lsp": "pyright-langserver",
}

LANGUAGE_RISK_NOTES = {
    "java": "Java/JDTLS can trigger Android Gradle sync and local.properties failures; keep it opt-in.",
    "graphql": "Serena does not provide native GraphQL routing; use GraphQL-specific tooling.",
}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    message: str
    details: dict[str, Any]


def normalize_languages(raw: str) -> list[str]:
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def parse_project_languages(project_file: Path) -> list[str]:
    if not project_file.exists():
        return []

    lines = project_file.read_text(encoding="utf-8").splitlines()
    languages: list[str] = []
    in_languages = False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if re.match(r"^languages\s*:", stripped):
            _, _, value = stripped.partition(":")
            value = value.strip()
            if value.startswith("[") and value.endswith("]"):
                return normalize_languages(value.strip("[]").replace('"', "").replace("'", ""))
            if value:
                return normalize_languages(value.replace('"', "").replace("'", ""))
            in_languages = True
            continue

        if in_languages:
            if re.match(r"^[A-Za-z0-9_-]+\s*:", stripped):
                break
            if stripped.startswith("-"):
                language = stripped[1:].strip().strip("\"'").lower()
                if language:
                    languages.append(language)

    return languages


def run_command(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def serena_version() -> tuple[str | None, str]:
    if shutil.which("serena") is None:
        return None, ""

    completed = run_command(["serena", "--version"])
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0:
        return "available", output
    return output or "available", output


def process_counts() -> dict[str, int]:
    completed = run_command(["ps", "ax", "-o", "command="])
    counts = dict.fromkeys(PROCESS_PATTERNS, 0)
    if completed.returncode != 0:
        return counts

    for line in completed.stdout.splitlines():
        if "grep" in line:
            continue
        for kind, pattern in PROCESS_PATTERNS.items():
            if pattern in line:
                counts[kind] += 1
    return counts


def project_config_check(repo: Path, expected_languages: list[str] | None) -> Check:
    project_file = repo / ".serena" / "project.yml"
    if not project_file.exists():
        return Check(
            "project_config",
            "fail",
            ".serena/project.yml is missing.",
            {
                "project_file": str(project_file),
                "expected_languages": expected_languages,
                "next_action": "Create Serena project metadata with the expected languages before relying on semantic tools.",
            },
        )

    actual_languages = parse_project_languages(project_file)
    missing = [language for language in expected_languages if language not in actual_languages] if expected_languages is not None else []
    extra = [language for language in actual_languages if language not in expected_languages] if expected_languages is not None else []
    risky = {language: LANGUAGE_RISK_NOTES[language] for language in actual_languages if language in LANGUAGE_RISK_NOTES}

    if missing:
        status = "fail"
        message = "Serena project languages are missing required entries."
    elif extra or risky:
        status = "warn"
        message = "Serena project languages include extra or risk-prone entries."
    elif expected_languages is None:
        status = "pass"
        message = "Serena project language configuration is present; generic profile does not enforce a language set."
    else:
        status = "pass"
        message = "Serena project language configuration matches the expected profile."

    return Check(
        "project_config",
        status,
        message,
        {
            "project_file": str(project_file),
            "expected_languages": expected_languages,
            "actual_languages": actual_languages,
            "missing_languages": missing,
            "extra_languages": extra,
            "risk_notes": risky,
        },
    )


def executable_check() -> Check:
    version, raw_output = serena_version()
    if version is None:
        return Check(
            "serena_executable",
            "fail",
            "serena executable was not found on PATH.",
            {"next_action": "Install Serena or add it to PATH before enabling Serena routing."},
        )
    return Check(
        "serena_executable",
        "pass",
        "serena executable is available.",
        {"version": version, "raw_output": raw_output},
    )


def process_state_check() -> Check:
    counts = process_counts()
    warnings: list[str] = []
    if counts["serena_mcp"] > 1:
        warnings.append("More than one Serena MCP server is active; confirm the current agent is attached to the target project.")
    for kind in ("kotlin_lsp", "json_lsp", "java_jdtls", "sourcekit_lsp", "python_lsp"):
        if counts[kind] > 1:
            warnings.append(f"More than one {kind} process is active; stale language-server state may affect semantic results.")

    status = "warn" if warnings else "pass"
    message = "Serena-related process state has warnings." if warnings else "Serena-related process state does not show duplicate processes."
    return Check("process_state", status, message, {"counts": counts, "warnings": warnings})


def resolved_repo_file(repo: Path, source_file: str) -> tuple[Path | None, Check | None]:
    raw_path = Path(source_file).expanduser()
    if raw_path.is_absolute():
        return None, Check(
            "source_symbol_smoke",
            "fail",
            "Smoke source file must be relative to the target repo.",
            {"source_file": source_file, "target_repo": str(repo)},
        )

    try:
        repo_root = repo.resolve()
        source_path = (repo_root / raw_path).resolve()
        source_path.relative_to(repo_root)
    except (OSError, ValueError):
        return None, Check(
            "source_symbol_smoke",
            "fail",
            "Smoke source file resolves outside the target repo.",
            {"source_file": source_file, "target_repo": str(repo)},
        )

    return source_path, None


def source_symbol_check(repo: Path, source_file: str, symbol: str) -> Check:
    if not source_file and not symbol:
        return Check(
            "source_symbol_smoke",
            "warn",
            "No source-symbol smoke target was provided.",
            {
                "next_action": "Provide --source-file and --symbol-smoke for the first real source symbol the agent should prove through Serena.",
                "proof_boundary": "Without a real Serena symbolic lookup, MCP connectivity is not semantic readiness proof.",
            },
        )

    if not source_file or not symbol:
        return Check(
            "source_symbol_smoke",
            "fail",
            "--source-file and --symbol-smoke must be provided together.",
            {"source_file": source_file, "symbol": symbol},
        )

    source_path, path_error = resolved_repo_file(repo, source_file)
    if path_error is not None:
        return path_error
    assert source_path is not None

    if not source_path.exists() or not source_path.is_file():
        return Check(
            "source_symbol_smoke",
            "fail",
            "Smoke source file was not found.",
            {"source_file": str(source_path), "symbol": symbol},
        )

    text = source_path.read_text(encoding="utf-8", errors="replace")
    found_locally = re.search(rf"\b{re.escape(symbol)}\b", text) is not None
    status = "warn" if found_locally else "fail"
    message = (
        "Smoke target exists locally; run the Serena symbolic lookup before making semantic claims."
        if found_locally
        else "Smoke symbol was not found in the provided source file."
    )
    return Check(
        "source_symbol_smoke",
        status,
        message,
        {
            "source_file": str(source_path),
            "symbol": symbol,
            "local_text_match": found_locally,
            "suggested_semantic_smoke": f"Use Serena to find declaration/references for {symbol} in {source_file}.",
            "proof_boundary": "Local text match is only a precondition; Serena/LSP lookup is the semantic proof.",
        },
    )


def hooks_check(repo: Path) -> Check:
    hooks_files = [
        repo / ".serena" / "hooks.yml",
        repo / ".serena" / "hooks.yaml",
        repo / ".codex" / "hooks.json",
    ]
    existing = [str(path) for path in hooks_files if path.exists()]
    status = "pass" if existing else "warn"
    return Check(
        "hooks",
        status,
        "Serena/Codex hook configuration was found." if existing else "No hook configuration was found; this is optional.",
        {
            "found": existing,
            "proof_boundary": "Hooks are reminders and automation aids, not Serena semantic readiness proof.",
        },
    )


def proof_boundary_check() -> Check:
    return Check(
        "proof_boundary",
        "pass",
        "Serena proof boundaries are explicit.",
        {
            "serena_proves": ["symbol identity", "definitions", "references", "hover/type info", "diagnostics when the language server is healthy"],
            "serena_does_not_prove": ["build success", "test success", "install success", "runtime behavior", "screenshots", "backend/schema correctness"],
        },
    )


def aggregate_status(checks: list[Check]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if "warn" in statuses:
        return "warn"
    return "pass"


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Serena doctor status: {payload['status']}",
        f"Target repo: {payload['target_repo']}",
        f"Profile: {payload['profile']}",
        "",
    ]
    for check in payload["checks"]:
        lines.append(f"[{check['status']}] {check['name']}: {check['message']}")
        next_action = check["details"].get("next_action")
        if next_action:
            lines.append(f"  next: {next_action}")
        warnings = check["details"].get("warnings") or []
        for warning in warnings:
            lines.append(f"  warning: {warning}")
    return "\n".join(lines) + "\n"


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.target_repo).expanduser().resolve()
    expected_languages = normalize_languages(args.expected_languages) if args.expected_languages else PROFILE_LANGUAGES[args.profile]
    checks = [
        executable_check(),
        project_config_check(repo, expected_languages),
        process_state_check(),
        source_symbol_check(repo, args.source_file, args.symbol_smoke),
        hooks_check(repo),
        proof_boundary_check(),
    ]
    payload = {
        "status": aggregate_status(checks),
        "target_repo": str(repo),
        "profile": args.profile,
        "expected_languages": expected_languages,
        "checks": [asdict(check) for check in checks],
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Serena readiness doctor for agent code routing.")
    parser.add_argument("--target-repo", required=True, help="Repository root to inspect.")
    parser.add_argument("--profile", choices=sorted(PROFILE_LANGUAGES), default="generic")
    parser.add_argument("--expected-languages", default="", help="Comma-separated Serena language list. Overrides --profile defaults.")
    parser.add_argument("--source-file", default="", help="Relative source file used for the source-symbol smoke precondition.")
    parser.add_argument("--symbol-smoke", default="", help="Symbol expected in --source-file for a Serena semantic smoke.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    repo = Path(args.target_repo).expanduser()
    if not repo.exists() or not repo.is_dir():
        print(f"Target repo not found: {repo}", flush=True)
        return 2

    payload = build_payload(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_text(payload), end="")
    return 1 if payload["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
