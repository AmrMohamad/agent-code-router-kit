from __future__ import annotations

import csv
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id(prefix: str = "rarb") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    display_name: str
    command: str
    fallback_commands: list[str]
    args: list[str]
    env: dict[str, str]
    prompt_mode: str
    telemetry_sources: list[str]
    supports_live: bool
    default_timeout_seconds: int
    terminal_mode: str


@dataclass(frozen=True)
class RouteProfile:
    profile_id: str
    display_name: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    required_first_tool: str
    high_fanout_policy: str
    max_raw_output_bytes: int
    instructions: str


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    task_family: str
    repo: str
    prompt: str
    route_profiles: list[str]
    edit_allowed: bool
    build_allowed: bool
    expected_proof_layer: str
    expected_success_signal: str
    forbidden_claims: str
    timeout_seconds: int


@dataclass(frozen=True)
class LaunchPlan:
    agent_id: str
    command: list[str]
    cwd: str
    prompt_mode: str
    telemetry_sources: list[str]
    supports_live: bool
    terminal_mode: str
    env: dict[str, str]


def to_json_file(path: str | Path, data: object) -> None:
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: str | Path, data: object) -> None:
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, sort_keys=True) + "\n")


def load_simple_yaml(path: str | Path) -> dict[str, object]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    data: dict[str, object] = {}
    key: str | None = None
    block_key: str | None = None
    block_lines: list[str] = []
    index = 0
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        index += 1
        if not stripped or stripped.startswith("#"):
            continue
        if block_key is not None:
            if raw.startswith(" ") or raw.startswith("\t") or not stripped:
                block_lines.append(raw[2:] if raw.startswith("  ") else raw.lstrip())
                continue
            data[block_key] = "\n".join(block_lines).rstrip()
            block_key = None
            block_lines = []
        if stripped.endswith(": |"):
            block_key = stripped[:-3]
            block_lines = []
            continue
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", stripped)
        if not match:
            if key and stripped.startswith("- "):
                current = data.setdefault(key, [])
                if isinstance(current, list):
                    current.append(stripped[2:].strip())
            continue
        key = match.group(1)
        value = match.group(2)
        if value == "":
            values: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                values.append(lines[index].strip()[2:].strip())
                index += 1
            data[key] = values
        elif value in {"true", "false"}:
            data[key] = value == "true"
        elif value.isdigit():
            data[key] = int(value)
        elif value == "[]":
            data[key] = []
        else:
            data[key] = value.strip('"')
    if block_key is not None:
        data[block_key] = "\n".join(block_lines).rstrip()
    return data


def load_agent_profile(path: str | Path) -> AgentProfile:
    data = load_simple_yaml(path)
    return AgentProfile(
        agent_id=str(data["agent_id"]),
        display_name=str(data.get("display_name", data["agent_id"])),
        command=str(data["command"]),
        fallback_commands=[str(item) for item in data.get("fallback_commands", [])],
        args=[str(item) for item in data.get("args", [])],
        env={str(key): str(value) for key, value in dict(data.get("env", {})).items()},
        prompt_mode=str(data.get("prompt_mode", "stdin")),
        telemetry_sources=[str(item) for item in data.get("telemetry_sources", ["transcript_proxy"])],
        supports_live=bool(data.get("supports_live", False)),
        default_timeout_seconds=int(data.get("default_timeout_seconds", 900)),
        terminal_mode=str(data.get("terminal_mode", "pty")),
    )


def load_route_profile(path: str | Path) -> RouteProfile:
    data = load_simple_yaml(path)
    return RouteProfile(
        profile_id=str(data["profile_id"]),
        display_name=str(data.get("display_name", data["profile_id"])),
        allowed_tools=[str(item) for item in data.get("allowed_tools", [])],
        blocked_tools=[str(item) for item in data.get("blocked_tools", [])],
        required_first_tool=str(data.get("required_first_tool", "")),
        high_fanout_policy=str(data.get("high_fanout_policy", "")),
        max_raw_output_bytes=int(data.get("max_raw_output_bytes", 12000)),
        instructions=str(data.get("instructions", "")),
    )


def load_tasks(path: str | Path) -> list[TaskSpec]:
    tasks: list[TaskSpec] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        required = {
            "task_id",
            "task_family",
            "repo",
            "prompt",
            "route_profiles",
            "edit_allowed",
            "build_allowed",
            "expected_proof_layer",
            "expected_success_signal",
            "forbidden_claims",
            "timeout_seconds",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"task manifest missing columns: {sorted(missing)}")
        for row in reader:
            tasks.append(
                TaskSpec(
                    task_id=row["task_id"],
                    task_family=row["task_family"],
                    repo=row["repo"],
                    prompt=row["prompt"],
                    route_profiles=[item.strip() for item in row["route_profiles"].split(",") if item.strip()],
                    edit_allowed=row["edit_allowed"].lower() == "true",
                    build_allowed=row["build_allowed"].lower() == "true",
                    expected_proof_layer=row["expected_proof_layer"],
                    expected_success_signal=row["expected_success_signal"],
                    forbidden_claims=row["forbidden_claims"],
                    timeout_seconds=int(row["timeout_seconds"]),
                )
            )
    return tasks


def dataclass_dict(value: object) -> dict[str, object]:
    return asdict(value)


def filter_tasks_for_profiles(tasks: Iterable[TaskSpec], profiles: set[str]) -> list[TaskSpec]:
    return [task for task in tasks if profiles.intersection(task.route_profiles)]
