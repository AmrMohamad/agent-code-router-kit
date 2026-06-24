from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DROP_FIELDS = {"traceback", "stderr", "stdout", "source_text", "snippet", "bounded_excerpt"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class TelemetryWriter:
    path: Path | None
    repo_root: Path | None = None

    def _repository_id(self) -> str:
        if self.repo_root is None:
            return ""
        return hashlib.sha256(str(self.repo_root).encode("utf-8")).hexdigest()[:16]

    def _hash_text(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    def _hash_pathish_value(self, value: str) -> str:
        if self.repo_root is None:
            return self._hash_text(value)
        try:
            relative = Path(value).expanduser().resolve().relative_to(self.repo_root)
        except Exception:
            digest_input = value
        else:
            digest_input = relative.as_posix()
        return self._hash_text(digest_input)

    def _sanitize_value(self, key: str, value: Any) -> tuple[str, Any] | None:
        if key in DROP_FIELDS:
            return None
        if key == "repo_root":
            return "repository_id", self._repository_id()
        if key == "error":
            return "error_hash", self._hash_text(str(value))
        if isinstance(value, str) and key.endswith("path"):
            return key + "_hash", self._hash_pathish_value(value)
        if isinstance(value, list) and (key.endswith("paths") or key.endswith("files")):
            return key + "_hashes", [self._hash_pathish_value(str(item)) for item in value]
        return key, value

    def emit(self, event: str, **fields: Any) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sanitized_fields: dict[str, Any] = {}
        for key, value in fields.items():
            sanitized = self._sanitize_value(key, value)
            if sanitized is None:
                continue
            clean_key, clean_value = sanitized
            sanitized_fields[clean_key] = clean_value
        payload = {"event": event, "timestamp": utc_now(), **sanitized_fields}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
