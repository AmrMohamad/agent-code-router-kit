#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.codegraph_readiness import codegraph_readiness, readiness_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only CodeGraph readiness checks")
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--gateway-command", default="acr-codegraph-gateway")
    args = parser.parse_args()
    report = codegraph_readiness(Path(args.target_repo), gateway_command=args.gateway_command)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(readiness_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
