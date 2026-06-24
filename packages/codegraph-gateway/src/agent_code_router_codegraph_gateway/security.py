from __future__ import annotations

import os
from pathlib import Path


def ensure_repo_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"repo root does not exist: {resolved}")
    allowed_root = os.environ.get("ACR_ALLOWED_REPO_ROOT", "").strip()
    if allowed_root:
        allowed = Path(allowed_root).expanduser().resolve()
        if not allowed.exists() or not allowed.is_dir():
            raise ValueError("ACR_ALLOWED_REPO_ROOT does not exist or is not a directory")
        try:
            resolved.relative_to(allowed)
        except ValueError as exc:
            raise ValueError("repo root is outside ACR_ALLOWED_REPO_ROOT") from exc
    return resolved


def repo_relative_path(repo_root: Path, candidate: str) -> str:
    path = (repo_root / candidate).resolve()
    try:
        relative = path.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"path escapes repo root: {candidate}") from exc
    return relative.as_posix()


def normalize_focus_paths(repo_root: Path, values: list[str] | None) -> list[str]:
    return [repo_relative_path(repo_root, value) for value in (values or [])]
