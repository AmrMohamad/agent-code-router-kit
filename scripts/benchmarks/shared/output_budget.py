from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
from typing import Callable


DEFAULT_WARN_BYTES = 12 * 1024
DEFAULT_FAIL_BYTES = 50 * 1024


def evaluate_output_size(
    byte_count: int,
    *,
    warn_bytes: int = DEFAULT_WARN_BYTES,
    fail_bytes: int = DEFAULT_FAIL_BYTES,
    baseline: bool = False,
) -> dict[str, object]:
    if byte_count < 0:
        raise ValueError("byte_count must be >= 0")
    if warn_bytes < 0 or fail_bytes < 0:
        raise ValueError("budget thresholds must be >= 0")
    if warn_bytes > fail_bytes:
        raise ValueError("warn_bytes must be <= fail_bytes")

    if byte_count > fail_bytes and not baseline:
        status = "fail"
    elif byte_count > warn_bytes:
        status = "warn"
    else:
        status = "pass"
    return {
        "status": status,
        "byte_count": byte_count,
        "warn_bytes": warn_bytes,
        "fail_bytes": fail_bytes,
        "baseline": baseline,
        "message": (
            f"bytes={byte_count} warn>{warn_bytes} fail>{fail_bytes} "
            f"baseline={baseline}"
        ),
    }


def android_module_from_path(path: str) -> str:
    parts = PurePosixPath(path).parts
    return parts[0] if parts else "(root)"


def android_package_from_path(path: str) -> str:
    parts = list(PurePosixPath(path).parts)
    for marker in ("java", "kotlin"):
        if marker in parts:
            index = parts.index(marker)
            package_parts = parts[index + 1 : -1]
            if package_parts:
                return ".".join(package_parts)
    return android_module_from_path(path)


def top_group_counts(
    rows: list[tuple[str, int]],
    key_func: Callable[[str], str],
    *,
    limit: int,
) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    counter: Counter[str] = Counter()
    for path, count in rows:
        counter[key_func(path)] += int(count)
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [{"key": key, "matches": count} for key, count in ordered[:limit]]
