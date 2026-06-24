#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit CodeGraph project initialization helper")
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    repo = Path(args.target_repo).expanduser().resolve()
    if not repo.exists() or not repo.is_dir():
        raise SystemExit(f"target repository was not found: {repo}")
    command = [shutil.which("codegraph") or "codegraph", "init"]
    if not args.apply:
        print("[dry-run] " + " ".join(command) + f"  # cwd={repo}")
        return 0
    if shutil.which("codegraph") is None:
        raise SystemExit("codegraph executable was not found on PATH")
    completed = subprocess.run(command, cwd=repo, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
