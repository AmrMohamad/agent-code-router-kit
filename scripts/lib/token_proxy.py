from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Mapping


BYTES_PER_TOKEN = 4


def byte_count(text: str) -> int:
    return len(text.encode("utf-8", errors="replace"))


def estimate_tokens_from_bytes(value: int, *, bytes_per_token: int = BYTES_PER_TOKEN) -> int:
    if value < 0:
        raise ValueError("byte count must be >= 0")
    if bytes_per_token < 1:
        raise ValueError("bytes_per_token must be >= 1")
    return ceil(value / bytes_per_token)


def estimate_tokens(text: str, *, bytes_per_token: int = BYTES_PER_TOKEN) -> int:
    return estimate_tokens_from_bytes(byte_count(text), bytes_per_token=bytes_per_token)


def read_text_metrics(path: str | Path) -> dict[str, int]:
    text = Path(path).read_text(encoding="utf-8")
    bytes_value = byte_count(text)
    return {"bytes": bytes_value, "proxy_tokens": estimate_tokens_from_bytes(bytes_value)}


def normalize_token_fields(
    *,
    prompt_bytes: int,
    answer_bytes: int,
    transcript_bytes: int,
    tool_output_bytes: int = 0,
    exact_tokens: Mapping[str, int] | None = None,
    agent_reported_tokens: Mapping[str, int] | None = None,
) -> dict[str, object]:
    for name, value in {
        "prompt_bytes": prompt_bytes,
        "answer_bytes": answer_bytes,
        "transcript_bytes": transcript_bytes,
        "tool_output_bytes": tool_output_bytes,
    }.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0")

    model_visible_bytes = prompt_bytes + answer_bytes + tool_output_bytes
    metrics: dict[str, object] = {
        "prompt_bytes": prompt_bytes,
        "answer_bytes": answer_bytes,
        "transcript_bytes": transcript_bytes,
        "tool_output_bytes": tool_output_bytes,
        "model_visible_bytes": model_visible_bytes,
        "prompt_proxy_tokens": estimate_tokens_from_bytes(prompt_bytes),
        "answer_proxy_tokens": estimate_tokens_from_bytes(answer_bytes),
        "tool_output_proxy_tokens": estimate_tokens_from_bytes(tool_output_bytes),
        "model_visible_proxy_tokens": estimate_tokens_from_bytes(model_visible_bytes),
        "transcript_proxy_tokens": estimate_tokens_from_bytes(transcript_bytes),
        "token_source": "proxy",
        "exact_input_tokens": None,
        "exact_output_tokens": None,
        "exact_total_tokens": None,
        "exact_cached_input_tokens": None,
        "exact_uncached_total_tokens": None,
        "exact_cache_creation_input_tokens": None,
        "exact_cache_read_input_tokens": None,
        "exact_reasoning_output_tokens": None,
        "exact_usage_event_count": None,
        "agent_reported_input_tokens": None,
        "agent_reported_output_tokens": None,
        "agent_reported_total_tokens": None,
    }
    if exact_tokens:
        metrics["exact_input_tokens"] = exact_tokens.get("input")
        metrics["exact_output_tokens"] = exact_tokens.get("output")
        metrics["exact_total_tokens"] = exact_tokens.get("total")
        metrics["exact_cached_input_tokens"] = exact_tokens.get("cached_input")
        total = exact_tokens.get("total")
        cached_input = exact_tokens.get("cached_input")
        if total is not None and cached_input is not None:
            metrics["exact_uncached_total_tokens"] = max(int(total) - int(cached_input), 0)
        metrics["exact_cache_creation_input_tokens"] = exact_tokens.get("cache_creation_input")
        metrics["exact_cache_read_input_tokens"] = exact_tokens.get("cache_read_input")
        metrics["exact_reasoning_output_tokens"] = exact_tokens.get("reasoning_output")
        metrics["exact_usage_event_count"] = exact_tokens.get("usage_event_count")
        if total is not None:
            metrics["token_source"] = "exact"
    if metrics["token_source"] != "exact" and agent_reported_tokens and agent_reported_tokens.get("total") is not None:
        metrics["token_source"] = "agent_reported"
        metrics["agent_reported_input_tokens"] = agent_reported_tokens.get("input")
        metrics["agent_reported_output_tokens"] = agent_reported_tokens.get("output")
        metrics["agent_reported_total_tokens"] = agent_reported_tokens.get("total")
    return metrics
