from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file
from scripts.lib.serena_readiness import serena_process_cleanup_plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Write a non-destructive cleanup plan for stale Serena/Kotlin/JSON LSP "
            "processes. This does not terminate anything."
        )
    )
    parser.add_argument("--out", help="Optional JSON output path.")
    args = parser.parse_args(argv)
    plan = serena_process_cleanup_plan()
    if args.out:
        to_json_file(args.out, plan)
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0 if plan["status"] == "clean" else 2


if __name__ == "__main__":
    raise SystemExit(main())
