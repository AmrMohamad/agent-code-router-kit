#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def latest_file(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern))
    return matches[-1] if matches else None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def summary_counts(assertions: list[dict[str, str]]) -> dict[str, int]:
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for item in assertions:
        counts[item["level"]] += 1
    return counts


def process_summary_is_project_clean(process: dict[str, Any]) -> bool:
    expected = int(process.get("expected_serena_mcp_count", 1))
    target_count = int(process.get("target_serena_mcp_count", 0))
    unknown_count = int(process.get("unknown_serena_mcp_count", 0))
    return process.get("status") == "clean" and target_count <= expected and unknown_count == 0


def build_acceptance(
    process_summary_path: Path | None,
    process: dict[str, Any] | None,
    *,
    accept_project_aware_strictness: bool,
    accepted_by: str,
    reason: str,
) -> dict[str, Any]:
    assertions: list[dict[str, str]] = []

    def add(level: str, name: str, detail: str) -> None:
        assertions.append({"level": level, "name": name, "detail": detail})

    if process is None:
        add("fail", "process-summary-present", "No project-aware process summary was provided or found.")
        target_count = 0
        other_count = 0
        unknown_count = 0
        expected = 1
        process_status = "missing"
        classification_counts: dict[str, Any] = {}
        target_project_path = ""
    else:
        add("pass", "process-summary-present", "Loaded project-aware process summary.")
        target_count = int(process.get("target_serena_mcp_count", 0))
        other_count = int(process.get("other_project_serena_mcp_count", 0))
        unknown_count = int(process.get("unknown_serena_mcp_count", 0))
        expected = int(process.get("expected_serena_mcp_count", 1))
        process_status = str(process.get("status", ""))
        classification_counts = dict(process.get("classification_counts", {}))
        target_project_path = str(process.get("target_project_path") or "")

    project_clean = process_summary_is_project_clean(process or {})
    if project_clean:
        add(
            "pass",
            "project-aware-process-clean",
            "Target-project Serena process ownership is clean; other-project sessions are outside this acceptance scope.",
        )
    else:
        add(
            "fail",
            "project-aware-process-clean",
            "Target-project process state is not clean enough for project-aware strictness acceptance.",
        )

    if accept_project_aware_strictness:
        if accepted_by.strip() and reason.strip():
            add("pass", "acceptance-recorded", "Project-aware strictness acceptance is explicit and attributable.")
        else:
            add("fail", "acceptance-recorded", "Acceptance requires --accepted-by and --reason.")
    else:
        add(
            "warn",
            "acceptance-recorded",
            "No acceptance was recorded; this remains a template/evidence artifact, not readiness satisfaction.",
        )

    assertions_summary = summary_counts(assertions)
    accepted = (
        accept_project_aware_strictness
        and assertions_summary["fail"] == 0
        and bool(accepted_by.strip())
        and bool(reason.strip())
    )
    return {
        "schema": "agent-code-router-kit.android-process-scope-acceptance.v1",
        "created_at": utc_now(),
        "status": "accepted" if accepted else "blocked" if assertions_summary["fail"] else "template_only",
        "accepted_project_aware_strictness": accepted,
        "accepted_by": accepted_by.strip(),
        "reason": reason.strip(),
        "boundary": (
            "This accepts project-aware strictness only: target-project Serena/LSP ownership is clean, "
            "while unrelated Serena sessions may remain active. It is not clean-room proof."
        ),
        "process_summary_path": str(process_summary_path) if process_summary_path else "",
        "process_summary_status": process_status,
        "target_project_path": target_project_path,
        "expected_serena_mcp_count": expected,
        "target_serena_mcp_count": target_count,
        "other_project_serena_mcp_count": other_count,
        "unknown_serena_mcp_count": unknown_count,
        "classification_counts": classification_counts,
        "assertions": assertions_summary,
        "assertion_details": assertions,
    }


def write_outputs(output: Path, data: dict[str, Any]) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"android-process-scope-acceptance-summary-{stamp()}.json"
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {path}")
    print(
        "Assertions: "
        f"pass={data['assertions']['pass']}, "
        f"warn={data['assertions']['warn']}, "
        f"fail={data['assertions']['fail']}"
    )
    print(f"Status: {data['status']}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Record explicit acceptance of project-aware Android Serena process strictness.")
    parser.add_argument("--results-root", default="results/android")
    parser.add_argument("--process-summary", default="")
    parser.add_argument("--output", default="results/android/process-scope-acceptance")
    parser.add_argument("--accept-project-aware-strictness", action="store_true")
    parser.add_argument("--accepted-by", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    results_root = Path(args.results_root).expanduser().resolve()
    process_path = (
        Path(args.process_summary).expanduser().resolve()
        if args.process_summary
        else latest_file(
            results_root / "process-state-stable-project-aware-allowed-other",
            "android-process-state-summary-*.json",
        )
    )
    process = load_json(process_path) if process_path else None
    data = build_acceptance(
        process_path,
        process,
        accept_project_aware_strictness=args.accept_project_aware_strictness,
        accepted_by=args.accepted_by,
        reason=args.reason,
    )
    write_outputs(Path(args.output).expanduser().resolve(), data)
    if args.enforce_assertions and data["assertions"]["fail"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
