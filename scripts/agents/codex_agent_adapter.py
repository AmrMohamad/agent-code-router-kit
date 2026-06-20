from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.agents.generic_terminal_agent_bridge import build_launch_plan
from scripts.lib.agent_session import load_agent_profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex adapter launch-plan helper.")
    parser.add_argument("--config", default="benchmarks/real-agent-routing/agents/codex.yaml")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    profile = load_agent_profile(args.config)
    plan = build_launch_plan(profile, cwd=str(Path(args.cwd).resolve()))
    print(json.dumps({**asdict(plan), "dry_run": args.dry_run}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
