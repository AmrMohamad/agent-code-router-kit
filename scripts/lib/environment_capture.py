from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path
from typing import Iterable


LOCKFILE_NAMES = (
    "Package.resolved",
    "pnpm-lock.yaml",
    "package-lock.json",
    "yarn.lock",
    "bun.lockb",
    "Cargo.lock",
    "Gemfile.lock",
    "gradle.lockfile",
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def command_output(command: list[str], *, cwd: str | Path | None = None, timeout: int = 15) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=Path(cwd).resolve() if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"not_available:{exc.__class__.__name__}"
    output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
    return output.splitlines()[0] if output else f"returncode:{completed.returncode}"


def git_output(repo: str | Path, *args: str) -> str:
    return command_output(["git", *args], cwd=repo)


def git_tree_hash(repo: str | Path) -> str:
    return git_output(repo, "rev-parse", "HEAD^{tree}")


def lockfile_hash(repo: str | Path, *, names: Iterable[str] = LOCKFILE_NAMES) -> str:
    repo_path = Path(repo).resolve()
    matches: list[dict[str, str]] = []
    for name in names:
        for path in repo_path.rglob(name):
            if ".git" in path.parts:
                continue
            try:
                rel = str(path.relative_to(repo_path))
            except ValueError:
                rel = str(path)
            matches.append({"path": rel, "sha256": file_sha256(path)})
    if not matches:
        return "none"
    payload = json.dumps(sorted(matches, key=lambda item: item["path"]), sort_keys=True)
    return text_sha256(payload)


def capture_tool_versions(*, cwd: str | Path) -> dict[str, str]:
    return {
        "os": platform.platform(),
        "python": platform.python_version(),
        "codex": command_output(["codex", "--version"], cwd=cwd),
        "serena": command_output(["serena", "--version"], cwd=cwd),
        "rg": command_output(["rg", "--version"], cwd=cwd),
        "fd": command_output(["fd", "--version"], cwd=cwd),
        "ast-grep": command_output(["ast-grep", "--version"], cwd=cwd),
        "git": command_output(["git", "--version"], cwd=cwd),
    }
