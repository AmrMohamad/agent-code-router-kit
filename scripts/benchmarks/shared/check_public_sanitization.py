#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".serena",
    "__pycache__",
    "results",
    "raw",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "build",
    "dist",
}

SKIP_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".jks",
    ".keystore",
    ".pyc",
}


@dataclass(frozen=True)
class BannedToken:
    label: str
    token: str


def join(*parts: str) -> str:
    return "".join(parts)


def banned_tokens() -> list[BannedToken]:
    specs = [
        ("old_company_name", ("ro", "busta")),
        ("old_b2b_app_name", ("ma", "zaya")),
        ("old_retail_app_name", ("pan", "da")),
        ("old_b2b_display_suffix", ("b2", "bapp")),
        ("old_retail_repo_fragment", ("customer", "-app")),
        ("old_b2b_repo_fragment", ("group", "-b2b")),
        ("private_home_path", ("/users/", "amr", "mohamad")),
        ("private_company_path", ("developer/", "ro", "busta")),
        ("old_b2b_package_prefix", ("com.", "ma", "zaya")),
        ("old_retail_package_prefix", ("com.", "pan", "da")),
        ("old_feature_symbol_one", ("notifications", "viewmodel")),
        ("old_feature_symbol_two", ("dynamic", "content", "viewmodel")),
        ("old_service_symbol", ("apppush", "notifications", "service")),
        ("old_graphql_symbol", ("graphql", "clientimp")),
        ("old_analytics_key", ("clar", "ity_id")),
        ("old_staging_map_key", ("staging", ".map", ".api", ".key")),
        ("old_production_map_key", ("production", ".map", ".api", ".key")),
    ]
    return [BannedToken(label, join(*parts).lower()) for label, parts in specs]


def git_release_files(root: Path) -> list[Path]:
    cmd = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    proc = subprocess.run(cmd, cwd=root, check=True, stdout=subprocess.PIPE)
    files: list[Path] = []
    for raw in proc.stdout.split(b"\0"):
        if not raw:
            continue
        files.append(root / raw.decode())
    return files


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    if path.name == ".DS_Store":
        return True
    return path.suffix.lower() in SKIP_SUFFIXES


def read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except UnicodeDecodeError:
        return None


def scan(root: Path) -> list[dict[str, str]]:
    tokens = banned_tokens()
    violations: list[dict[str, str]] = []
    for path in git_release_files(root):
        if not path.exists() or should_skip(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        rel_lower = rel.lower()
        for token in tokens:
            if token.token in rel_lower:
                violations.append({"file": rel, "label": token.label, "where": "path"})
        text = read_text(path)
        if text is None:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for token in tokens:
                if token.token in lower:
                    violations.append(
                        {
                            "file": rel,
                            "label": token.label,
                            "where": f"line {line_no}",
                        }
                    )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check public files for private project identifiers.")
    parser.add_argument("--root", default=Path(__file__).resolve().parents[3])
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    violations = scan(root)
    if violations:
        print("PUBLIC SANITIZATION FAILED")
        for item in violations:
            print(f"{item['file']}:{item['where']}: {item['label']}")
        return 1
    print("PUBLIC SANITIZATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
