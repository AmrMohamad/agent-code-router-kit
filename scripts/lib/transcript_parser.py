from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from typing import Any


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bauthorization\s*:\s*(?:bearer|basic)\s+\S+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{6,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


@dataclass(frozen=True)
class ParsedTranscript:
    done: bool
    contract_present: bool
    status: str | None
    confidence: str | None
    tools_used: list[str]
    files_opened: list[str]
    raw_dump_incidents: int
    policy_adherence: str | None
    final_answer: str
    redacted_text: str


TEXT_KEYS = {"content", "text", "message", "delta", "output", "result", "final_answer"}
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BOOTSTRAP_TOOL_NAMES = {"activate_project", "initial_instructions", "onboarding"}
CURSOR_TOOL_NAME_MAP = {
    "grepToolCall": "rg",
    "readToolCall": "read",
    "listDirToolCall": "fd",
    "fileSearchToolCall": "fd",
}


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def normalize_terminal_text(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")


def _collect_json_text_values(value: Any) -> list[str]:
    fragments: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in TEXT_KEYS and isinstance(child, str):
                fragments.append(child)
            else:
                fragments.extend(_collect_json_text_values(child))
    elif isinstance(value, list):
        for child in value:
            fragments.extend(_collect_json_text_values(child))
    return fragments


def _is_user_prompt_payload(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("type") == "user":
        return True
    message = payload.get("message")
    if isinstance(message, dict) and message.get("role") == "user":
        return True
    if payload.get("role") == "user":
        return True
    return False


def _json_payloads_from_terminal_text(text: str) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    pending = ""
    pending_lines = 0
    for raw in normalize_terminal_text(text).splitlines():
        if not raw.strip():
            continue
        if pending:
            pending += raw.lstrip()
            pending_lines += 1
        elif raw.lstrip().startswith("{"):
            pending = raw.lstrip()
            pending_lines = 1
        else:
            continue
        if not pending.rstrip().endswith("}"):
            if pending_lines > 200:
                pending = ""
                pending_lines = 0
            continue
        try:
            payload = json.loads(pending)
        except json.JSONDecodeError:
            if pending_lines > 200:
                pending = ""
                pending_lines = 0
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
        pending = ""
        pending_lines = 0
    return payloads


def expand_json_text_fragments(text: str) -> str:
    fragments: list[str] = []
    kept_lines: list[str] = []
    normalized = normalize_terminal_text(text)
    for line in normalized.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("{") and stripped.endswith("}")):
            kept_lines.append(line)
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            kept_lines.append(line)
            continue
        if _is_user_prompt_payload(payload):
            continue
        kept_lines.append(line)
        fragments.extend(_collect_json_text_values(payload))
    for payload in _json_payloads_from_terminal_text(normalized):
        if _is_user_prompt_payload(payload):
            continue
        fragments.extend(_collect_json_text_values(payload))
    base = "\n".join(kept_lines)
    if not fragments:
        return base
    return base + "\n" + "\n".join(fragments)


def has_done_sentinel(text: str, sentinel: str = "BENCHMARK_DONE") -> bool:
    return sentinel in expand_json_text_fragments(text)


def _section_lines(text: str, section: str) -> list[str]:
    body = _section_text(text, section)
    return [line.strip() for line in body.splitlines() if line.strip()]


def _section_text(text: str, section: str) -> str:
    pattern = re.compile(rf"(?im)^{re.escape(section)}:\s*$")
    match = pattern.search(text)
    if not match:
        return ""
    start = match.end()
    next_section = re.search(r"(?m)^[A-Za-z_]+:\s*$", text[start:])
    end = start + next_section.start() if next_section else len(text)
    return "\n".join(line[2:] if line.startswith("  ") else line for line in text[start:end].splitlines()).strip()


def parse_benchmark_response(text: str, *, sentinel: str = "BENCHMARK_DONE") -> ParsedTranscript:
    redacted = redact_secrets(expand_json_text_fragments(text))
    contract_present = "BENCHMARK_RESULT" in redacted
    status_match = re.search(r"(?im)^status:\s*(pass|partial|fail|blocked)\s*$", redacted)
    confidence_match = re.search(r"(?im)^confidence:\s*(high|medium|low)\s*$", redacted)
    adherence_match = re.search(r"(?im)^policy_adherence:\s*(pass|warn|fail)\s*$", redacted)
    raw_dump_match = re.search(r"(?ims)^raw_dump_incidents:\s*\n\s*count:\s*(\d+)", redacted)
    tools = [line[2:].strip() for line in _section_lines(redacted, "tools_used") if line.startswith("- ")]
    files_block_match = re.search(
        r"(?ims)^files_opened:\s*(.*?)(?:^raw_dump_incidents:|\Z)",
        redacted,
    )
    files_block = files_block_match.group(1) if files_block_match else ""
    files = [line.strip()[2:].strip() for line in files_block.splitlines() if line.strip().startswith("- ")]
    final_answer_lines = _section_lines(redacted, "final_answer")
    if sentinel in final_answer_lines:
        final_answer_lines = final_answer_lines[: final_answer_lines.index(sentinel)]
    return ParsedTranscript(
        done=has_done_sentinel(redacted, sentinel),
        contract_present=contract_present,
        status=status_match.group(1).lower() if status_match else None,
        confidence=confidence_match.group(1).lower() if confidence_match else None,
        tools_used=tools,
        files_opened=files,
        raw_dump_incidents=int(raw_dump_match.group(1)) if raw_dump_match else 0,
        policy_adherence=adherence_match.group(1).lower() if adherence_match else None,
        final_answer="\n".join(final_answer_lines).strip(),
        redacted_text=redacted,
    )


def count_tool_mentions(text: str) -> dict[str, int]:
    lowered = expand_json_text_fragments(text).lower()
    return {
        "search_count": len(re.findall(r"\b(rg|fd)\b", lowered)),
        "semantic_tool_count": len(re.findall(r"\b(serena|lsp|android studio|studio usages)\b", lowered)),
        "runtime_tool_count": len(re.findall(r"\b(gradle|adb|emulator|install|launch)\b", lowered)),
        "ast_grep_count": len(re.findall(r"\b(ast-grep|ast_grep)\b", lowered)),
    }


def count_tools_from_events(events: list[dict[str, str]]) -> dict[str, int]:
    counts = {
        "search_count": 0,
        "semantic_tool_count": 0,
        "runtime_tool_count": 0,
        "ast_grep_count": 0,
    }
    for event in events:
        tool = str(event.get("tool", "")).lower()
        if tool in {"rg", "fd", "grep", "glob", "read", "nl", "sed", "cat"}:
            counts["search_count"] += 1
        if (
            "serena" in tool
            or "lsp" in tool
            or tool
            in {
                "find_symbol",
                "find_referencing_symbols",
                "get_symbols_overview",
                "find_declaration",
                "find_references",
                "hover",
                "semsearch",
                "semantic_search",
                "studio_usages",
                "android_studio_usages",
            }
        ):
            counts["semantic_tool_count"] += 1
        if tool in {"gradle", "adb", "emulator"} or "gradlew" in tool or "xcrun" in tool:
            counts["runtime_tool_count"] += 1
        if tool in {"ast-grep", "ast_grep"}:
            counts["ast_grep_count"] += 1
    return counts


def _cursor_tool_name(node: dict[str, Any]) -> str | None:
    found = _cursor_tool_call(node)
    return found[0] if found else None


def _cursor_tool_call(node: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    tool_call = node.get("tool_call")
    if not isinstance(tool_call, dict):
        return None
    for key, payload in tool_call.items():
        normalized = CURSOR_TOOL_NAME_MAP.get(key)
        tool_payload = payload if isinstance(payload, dict) else {}
        if normalized:
            return normalized, tool_payload
        if key.endswith("ToolCall"):
            return key[:-8] or key, tool_payload
    return None


def _cursor_tool_phase(node: dict[str, Any], tool: str) -> str:
    found = _cursor_tool_call(node)
    payload = found[1] if found else {}
    args = payload.get("args") if isinstance(payload, dict) else None
    if isinstance(args, dict):
        path = str(args.get("path") or args.get("cwd") or "")
        if event_phase(path) == "bootstrap_context":
            return "bootstrap_context"
    return event_phase(tool)


def _cursor_tool_permission_denied(node: dict[str, Any]) -> bool:
    found = _cursor_tool_call(node)
    payload = found[1] if found else {}
    result = payload.get("result") if isinstance(payload, dict) else None
    return isinstance(result, dict) and "permissionDenied" in result


def observed_tool_output_bytes(text: str, *, include_bootstrap: bool = False) -> int:
    by_id: dict[str, int] = {}
    anonymous: list[int] = []

    def record_result(node: dict[str, Any], result: Any) -> None:
        output_text = json.dumps(result, sort_keys=True) if not isinstance(result, str) else result
        output_size = len(output_text.encode("utf-8", errors="replace"))
        item_id = str(node.get("call_id") or node.get("id") or "")
        if item_id:
            by_id[item_id] = max(by_id.get(item_id, 0), output_size)
        else:
            anonymous.append(output_size)

    for payload in _json_payloads_from_terminal_text(text):
        if _is_user_prompt_payload(payload):
            continue
        for node in _walk_json(payload):
            event_type = str(node.get("type") or node.get("event") or "")
            if "command_execution" in event_type:
                command = str(node.get("command") or "")
                if event_phase(command) == "bootstrap_context" and not include_bootstrap:
                    continue
                output = node.get("aggregated_output")
                if not isinstance(output, str):
                    output = node.get("stdout")
                if not isinstance(output, str) or not output:
                    continue
                output_size = len(output.encode("utf-8", errors="replace"))
                item_id = str(node.get("id") or "")
                if item_id:
                    by_id[item_id] = max(by_id.get(item_id, 0), output_size)
                else:
                    anonymous.append(output_size)
                continue
            cursor_tool = _cursor_tool_name(node)
            if cursor_tool:
                if _cursor_tool_permission_denied(node):
                    continue
                if _cursor_tool_phase(node, cursor_tool) == "bootstrap_context" and not include_bootstrap:
                    continue
                result = node.get("result")
                if result is None:
                    nested = node.get("tool_call")
                    if isinstance(nested, dict):
                        for child in nested.values():
                            if isinstance(child, dict) and "result" in child:
                                result = child.get("result")
                                break
                if result is None:
                    continue
                record_result(node, result)
                continue
            name = node.get("tool") or node.get("tool_name") or node.get("name")
            if not isinstance(name, str):
                continue
            if event_phase(name) == "bootstrap_context" and not include_bootstrap:
                continue
            if "tool" not in event_type.lower() and event_type not in {"mcp", "function_call"}:
                continue
            result = node.get("result")
            if result is None:
                result = node.get("output")
            if result is None:
                continue
            record_result(node, result)
    return sum(by_id.values()) + sum(anonymous)


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _first_int(*values: object) -> int | None:
    for value in values:
        parsed = _as_int(value)
        if parsed is not None:
            return parsed
    return None


def extract_token_usage(text: str) -> dict[str, object]:
    exact_events: list[dict[str, int]] = []
    agent_reported: dict[str, int] = {}
    for payload in _json_payloads_from_terminal_text(text):
        for node in _walk_json(payload):
            input_value = _first_int(
                node.get("input_tokens"),
                node.get("prompt_tokens"),
                node.get("inputTokens"),
                node.get("promptTokens"),
            )
            output_value = _first_int(
                node.get("output_tokens"),
                node.get("completion_tokens"),
                node.get("outputTokens"),
                node.get("completionTokens"),
            )
            total_value = _first_int(node.get("total_tokens"), node.get("totalTokens"))
            cache_creation_input_value = _first_int(
                node.get("cache_creation_input_tokens"),
                node.get("cacheCreationInputTokens"),
                node.get("cacheWriteTokens"),
            )
            cache_read_input_value = _first_int(
                node.get("cache_read_input_tokens"),
                node.get("cacheReadInputTokens"),
                node.get("cacheReadTokens"),
            )
            cached_input_value = _first_int(node.get("cached_input_tokens"), node.get("cachedInputTokens"), cache_read_input_value)
            reasoning_output_value = _first_int(node.get("reasoning_output_tokens"), node.get("reasoningOutputTokens"))
            event = {
                key: value
                for key, value in {
                    "input": input_value,
                    "output": output_value,
                    "total": total_value,
                    "cached_input": cached_input_value,
                    "cache_creation_input": cache_creation_input_value,
                    "cache_read_input": cache_read_input_value,
                    "reasoning_output": reasoning_output_value,
                }.items()
                if value is not None
            }
            if event:
                exact_events.append(event)
    exact: dict[str, int] = {}
    if exact_events:
        for key in (
            "input",
            "output",
            "cached_input",
            "cache_creation_input",
            "cache_read_input",
            "reasoning_output",
        ):
            values = [event[key] for event in exact_events if key in event]
            if values:
                exact[key] = sum(values)
        total_values = [event["total"] for event in exact_events if "total" in event]
        if total_values:
            exact["total"] = sum(total_values)
        else:
            total = sum(
                exact.get(key, 0)
                for key in ("input", "output", "cache_creation_input", "cache_read_input")
            )
            if total:
                exact["total"] = total
        exact["usage_event_count"] = len(exact_events)
    patterns = {
        "input": r"(?i)\b(?:input|prompt)\s+tokens?\s*[:=]\s*(\d+)",
        "output": r"(?i)\b(?:output|completion)\s+tokens?\s*[:=]\s*(\d+)",
        "total": r"(?i)\btotal\s+tokens?\s*[:=]\s*(\d+)",
    }
    for key, pattern in patterns.items():
        matches = [int(match) for match in re.findall(pattern, text)]
        if matches:
            agent_reported[key] = max(matches)
    if agent_reported and "total" not in agent_reported and {"input", "output"} <= set(agent_reported):
        agent_reported["total"] = agent_reported["input"] + agent_reported["output"]
    return {"exact": exact or None, "agent_reported": agent_reported or None}


def observed_tool_events(text: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    for payload in _json_payloads_from_terminal_text(text):
        if _is_user_prompt_payload(payload):
            continue
        for node in _walk_json(payload):
            command = node.get("command")
            event_type = str(node.get("type") or node.get("event") or "")
            if isinstance(command, str) and "command_execution" in event_type:
                events.append(
                    {
                        "tool": command_primary_tool(command),
                        "source": "command_execution",
                        "phase": event_phase(command),
                        "line": json.dumps(payload, sort_keys=True)[:240],
                    }
                )
                break
            cursor_tool = _cursor_tool_name(node)
            if cursor_tool and "tool_call" in event_type:
                if str(node.get("subtype") or "") != "completed":
                    continue
                if _cursor_tool_permission_denied(node):
                    continue
                phase = _cursor_tool_phase(node, cursor_tool)
                events.append(
                    {
                        "tool": cursor_tool,
                        "source": "cursor_tool_call",
                        "phase": phase,
                        "line": json.dumps(payload, sort_keys=True)[:240],
                    }
                )
                break
            name = node.get("tool") or node.get("tool_name") or node.get("name")
            if isinstance(name, str) and ("tool" in event_type.lower() or event_type in {"mcp", "function_call"}):
                events.append({"tool": name, "source": "json_event", "phase": event_phase(name), "line": json.dumps(payload, sort_keys=True)[:240]})
                break
    expanded = expand_json_text_fragments(text)
    for line in expanded.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped:
            continue
        mcp_match = re.search(r"\bmcp:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", stripped)
        if mcp_match:
            events.append({"tool": mcp_match.group(1), "source": "mcp_event", "line": stripped[:240]})
            continue
        ran_match = re.search(r"(?i)\bRan\s+([A-Za-z0-9_.:/-]+)", stripped)
        if ran_match:
            tool = ran_match.group(1)
            if tool[:1].isupper():
                continue
            events.append({"tool": tool, "source": "terminal_event", "line": stripped[:240]})
            continue
        if stripped.startswith("{"):
            continue
        if (
            lowered.startswith(('\\"', '"'))
            or '"type"' in lowered
            or '"command"' in lowered
            or "command_execution" in lowered
        ):
            continue
        first = stripped.split()[0].strip(":")
        first_lower = first.lower()
        if (
            first_lower in {"rg", "fd", "ast-grep", "ast_grep", "gradle", "adb"}
            or first_lower.startswith(("mcp__", "serena/"))
            or first_lower == "android"
        ):
            events.append({"tool": first, "source": "text_heuristic", "line": stripped[:240]})
    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for event in events:
        key = (event["tool"], event["source"], event["line"])
        if key not in seen:
            deduped.append(event)
            seen.add(key)
    return deduped


def command_primary_tool(command: str) -> str:
    command = command.replace('\\"', '"')

    def clean_tool(value: str) -> str:
        return value.strip().strip("\"'`")

    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if len(parts) >= 3 and parts[0].endswith(("zsh", "bash", "sh")) and parts[1] == "-lc":
        try:
            inner = shlex.split(parts[2])
        except ValueError:
            inner = parts[2].split()
        return clean_tool(inner[0]) if inner else clean_tool(parts[0])
    return clean_tool(parts[0]) if parts else clean_tool(command)


def event_phase(command_or_line: str) -> str:
    lowered = command_or_line.lower()
    if lowered in BOOTSTRAP_TOOL_NAMES:
        return "bootstrap_context"
    if (
        lowered.startswith(('\\"', '"'))
        or '"type"' in lowered
        or '"command"' in lowered
        or "command_execution" in lowered
        or lowered.startswith(("type", "item", "command"))
    ):
        return "bootstrap_context" if "agents.md" in lowered or "skill.md" in lowered else "task"
    if (
        "/.codex/memories" in lowered
        or "/.codex/skills" in lowered
        or "/.codex/knowledge" in lowered
        or "agents.md" in lowered
        or "skill.md" in lowered
    ):
        return "bootstrap_context"
    return "task"


def classify_failure_reason(text: str) -> str:
    lowered = text.lower()
    if "does not have access to claude" in lowered:
        return "model_access_denied"
    if "authentication_failed" in lowered:
        return "authentication_failed"
    if "out of usage" in lowered or "increase limits" in lowered:
        return "quota_exceeded"
    if "no prompt provided" in lowered or "input must be provided either through stdin or as a prompt argument" in lowered:
        return "prompt_delivery_failed"
    if "requires --verbose" in lowered:
        return "adapter_flags_invalid"
    return ""


def tool_output_bytes(text: str, *, fallback_to_transcript: bool = False) -> int:
    redacted = redact_secrets(expand_json_text_fragments(text))
    tool_outputs = _section_text(redacted, "tool_outputs")
    structured_bytes = len(tool_outputs.encode("utf-8", errors="replace")) if tool_outputs else 0
    observed_bytes = observed_tool_output_bytes(redacted)
    if observed_bytes:
        return max(structured_bytes, observed_bytes)
    if not fallback_to_transcript:
        return structured_bytes
    if _json_payloads_from_terminal_text(redacted):
        return structured_bytes
    parsed = parse_benchmark_response(redacted)
    final_answer_bytes = len(parsed.final_answer.encode("utf-8", errors="replace"))
    transcript_output_bytes = max(len(redacted.encode("utf-8", errors="replace")) - final_answer_bytes, 0)
    return max(structured_bytes, transcript_output_bytes)
