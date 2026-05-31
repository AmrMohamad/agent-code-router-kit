#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a compact public-safe summary from benchmark JSON.")
    parser.add_argument("summary_json", help="Path to benchmark summary JSON.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument("--max-items", type=int, default=20, help="Maximum rows to keep.")
    args = parser.parse_args()

    rows = json.loads(Path(args.summary_json).read_text())
    sanitized = []
    for row in rows[: args.max_items]:
        sanitized.append(
            {
                "case_id": row.get("case_id"),
                "category": row.get("category"),
                "tool": row.get("tool"),
                "command_label": row.get("command_label"),
                "passes": row.get("passes"),
                "exit_codes": row.get("exit_codes"),
                "timeout_count": row.get("timeout_count"),
                "last_line_count": row.get("last_line_count"),
                "last_byte_count": row.get("last_byte_count"),
                "last_unique_file_count": row.get("last_unique_file_count"),
                "last_match_count": row.get("last_match_count"),
                "last_parse_error_count": row.get("last_parse_error_count"),
                "expected_first_tool": row.get("expected_first_tool"),
            }
        )
    Path(args.output).write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

