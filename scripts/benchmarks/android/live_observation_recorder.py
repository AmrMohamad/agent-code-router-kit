#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_FIRST_TOOLS = {
    "serena_kotlin_lsp",
    "serena_json_lsp",
    "android_studio_usages",
    "grouped_summary",
    "rg_fd",
    "graphql_workbench_rg_fd",
    "fd_rg_gradle_mapping",
    "ast_grep",
    "gradle_android_runtime",
    "rg_fd_then_semantic_disambiguation",
}

VALID_STATUS = {"pass", "fail", "warn", "blocked"}
TRUE_VALUES = {"1", "true", "yes"}
FALSE_VALUES = {"0", "false", "no"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_payload(path: Path) -> dict[str, Any]:
    if path.exists():
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise SystemExit("observation file must be a JSON object")
        data.setdefault("observations", [])
        return data
    return {
        "schema": "agent-code-router-kit.android-live-observations.v1",
        "date_utc": utc_now(),
        "observations": [],
    }


def write_payload(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now()
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def update_row(rows: list[dict[str, Any]], key: str, value: str, update: dict[str, Any]) -> None:
    for row in rows:
        if str(row.get(key, "")) == value:
            row.update(update)
            return
    rows.append(update)


def normalize_bool(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in TRUE_VALUES:
        return "true"
    if lowered in FALSE_VALUES:
        return "false"
    raise SystemExit(f"expected boolean value, got {value!r}")


def non_negative_int(value: str) -> str:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise SystemExit(f"expected integer process growth, got {value!r}") from exc
    if parsed < 0:
        raise SystemExit("--process-growth must be >= 0")
    return str(parsed)


def add_behavior(args: argparse.Namespace) -> dict[str, Any]:
    if args.observed_first_tool not in VALID_FIRST_TOOLS:
        raise SystemExit(f"invalid --observed-first-tool {args.observed_first_tool!r}")
    if not args.evidence.strip():
        raise SystemExit("--evidence is required for live behavior observations")
    payload = load_payload(Path(args.log).expanduser().resolve())
    payload["schema"] = "agent-code-router-kit.android-live-behavior-observations.v1"
    row = {
        "case_id": args.case_id,
        "observed_first_tool": args.observed_first_tool,
        "observed_notes": args.notes,
        "evidence": args.evidence,
        "recorded_at": utc_now(),
    }
    update_row(payload["observations"], "case_id", args.case_id, row)
    return payload


def add_transport(args: argparse.Namespace) -> dict[str, Any]:
    if args.status not in VALID_STATUS:
        raise SystemExit(f"invalid --status {args.status!r}")
    if not args.transport.strip():
        raise SystemExit("--transport is required")
    if not args.evidence.strip():
        raise SystemExit("--evidence is required for transport observations")
    payload = load_payload(Path(args.log).expanduser().resolve())
    payload["schema"] = "agent-code-router-kit.android-transport-real-task-observations.v1"
    row = {
        "task_id": args.task_id,
        "transport": args.transport,
        "status": args.status,
        "transport_error": normalize_bool(args.transport_error),
        "process_growth": non_negative_int(args.process_growth),
        "notes": args.notes,
        "evidence": args.evidence,
        "recorded_at": utc_now(),
    }
    update_row(payload["observations"], "task_id", args.task_id, row)
    return payload


def validate_behavior(payload: dict[str, Any], min_count: int) -> dict[str, Any]:
    rows = payload.get("observations", [])
    valid = 0
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        case_id = str(row.get("case_id", ""))
        tool = str(row.get("observed_first_tool", ""))
        evidence = str(row.get("evidence", ""))
        if not case_id:
            errors.append(f"row {index}: missing case_id")
        if case_id in seen:
            errors.append(f"row {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        if tool not in VALID_FIRST_TOOLS:
            errors.append(f"row {index}: invalid observed_first_tool {tool!r}")
        if not evidence.strip():
            errors.append(f"row {index}: missing evidence")
        if case_id and tool in VALID_FIRST_TOOLS and evidence.strip():
            valid += 1
    return {"valid_observations": valid, "minimum_observations": min_count, "errors": errors}


def validate_transport(payload: dict[str, Any], min_count: int) -> dict[str, Any]:
    rows = payload.get("observations", [])
    valid = 0
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        task_id = str(row.get("task_id", ""))
        status = str(row.get("status", ""))
        transport = str(row.get("transport", ""))
        transport_error = str(row.get("transport_error", "")).lower()
        process_growth = str(row.get("process_growth", ""))
        evidence = str(row.get("evidence", ""))
        if not task_id:
            errors.append(f"row {index}: missing task_id")
        if task_id in seen:
            errors.append(f"row {index}: duplicate task_id {task_id}")
        seen.add(task_id)
        if not transport:
            errors.append(f"row {index}: missing transport")
        if status not in VALID_STATUS:
            errors.append(f"row {index}: invalid status {status!r}")
        if transport_error not in TRUE_VALUES | FALSE_VALUES:
            errors.append(f"row {index}: invalid transport_error {transport_error!r}")
        try:
            growth = int(process_growth)
        except ValueError:
            errors.append(f"row {index}: invalid process_growth {process_growth!r}")
            growth = -1
        if growth < 0:
            errors.append(f"row {index}: process_growth must be >= 0")
        if not evidence.strip():
            errors.append(f"row {index}: missing evidence")
        if task_id and transport and status == "pass" and transport_error in FALSE_VALUES and growth == 0 and evidence.strip():
            valid += 1
    return {"valid_observations": valid, "minimum_observations": min_count, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description="Append and validate Android live observation logs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    behavior = subparsers.add_parser("behavior", help="Record a live first-tool observation.")
    behavior.add_argument("--log", required=True)
    behavior.add_argument("--case-id", required=True)
    behavior.add_argument("--observed-first-tool", required=True)
    behavior.add_argument("--notes", default="")
    behavior.add_argument("--evidence", required=True)

    transport = subparsers.add_parser("transport", help="Record a real-task transport observation.")
    transport.add_argument("--log", required=True)
    transport.add_argument("--task-id", required=True)
    transport.add_argument("--transport", required=True)
    transport.add_argument("--status", required=True, choices=sorted(VALID_STATUS))
    transport.add_argument("--transport-error", required=True)
    transport.add_argument("--process-growth", required=True)
    transport.add_argument("--notes", default="")
    transport.add_argument("--evidence", required=True)

    validate = subparsers.add_parser("validate", help="Validate a behavior or transport observation log.")
    validate.add_argument("--log", required=True)
    validate.add_argument("--kind", required=True, choices=["behavior", "transport"])
    validate.add_argument("--min-observations", type=int, default=10)
    validate.add_argument("--enforce", action="store_true")

    args = parser.parse_args()
    if args.command == "behavior":
        path = Path(args.log).expanduser().resolve()
        data = add_behavior(args)
        write_payload(path, data)
        print(f"Wrote {path}")
        print(f"Observation count: {len(data['observations'])}")
        return 0
    if args.command == "transport":
        path = Path(args.log).expanduser().resolve()
        data = add_transport(args)
        write_payload(path, data)
        print(f"Wrote {path}")
        print(f"Observation count: {len(data['observations'])}")
        return 0

    path = Path(args.log).expanduser().resolve()
    data = load_payload(path)
    result = (
        validate_behavior(data, args.min_observations)
        if args.kind == "behavior"
        else validate_transport(data, args.min_observations)
    )
    ok = not result["errors"] and result["valid_observations"] >= result["minimum_observations"]
    print(json.dumps({"ok": ok, **result}, indent=2, sort_keys=True))
    return 3 if args.enforce and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
