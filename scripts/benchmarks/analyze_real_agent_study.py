#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.agent_session import to_json_file
from scripts.lib.treatment_config import FACTORIAL_ARM_ORDER


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def numeric(row: dict[str, object], key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def paired_log_ratios(rows: list[dict[str, object]], *, metric: str, left: str, right: str) -> list[dict[str, object]]:
    by_cell: dict[tuple[str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        key = (str(row.get("agent", "")), str(row.get("task_id", "")), int(row.get("repeat_index", 0)))
        by_cell[key][str(row.get("profile", ""))] = row
    result: list[dict[str, object]] = []
    for key, profiles in by_cell.items():
        if left not in profiles or right not in profiles:
            continue
        left_value = numeric(profiles[left], metric)
        right_value = numeric(profiles[right], metric)
        if left_value is None or right_value is None:
            continue
        result.append(
            {
                "agent": key[0],
                "task_id": key[1],
                "repeat_index": key[2],
                "left_profile": left,
                "right_profile": right,
                "left": left_value,
                "right": right_value,
                "log_ratio": math.log(right_value / left_value),
                "percent_change": (right_value - left_value) / left_value * 100.0,
            }
        )
    return result


def summarize_effect(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {"pair_count": 0}
    changes = [float(row["percent_change"]) for row in rows]
    logs = [float(row["log_ratio"]) for row in rows]
    return {
        "pair_count": len(rows),
        "median_percent_change": round(statistics.median(changes), 2),
        "mean_log_effect": round(statistics.mean(logs), 6),
        "mean_log_effect_as_percent": round((math.exp(statistics.mean(logs)) - 1.0) * 100.0, 2),
    }


def analyze(root: str | Path, *, metric: str) -> dict[str, object]:
    base = Path(root).expanduser().resolve()
    rows = load_jsonl(base / "runs.jsonl")
    correctness = Counter(str(row.get("oracle_status") or row.get("correctness_status", "")) for row in rows)
    pairwise = {}
    for left, right in [
        ("A-search-only", "B-search-summary"),
        ("A-search-only", "C-lsp-naive"),
        ("C-lsp-naive", "D-full-router"),
        ("A-search-only", "D-full-router"),
    ]:
        effects = paired_log_ratios(rows, metric=metric, left=left, right=right)
        pairwise[f"{left}_to_{right}"] = summarize_effect(effects)
    return {
        "analysis_id": "router-effect-v1",
        "metric": metric,
        "run_count": len(rows),
        "arm_counts": dict(Counter(str(row.get("profile", "")) for row in rows)),
        "expected_arms": FACTORIAL_ARM_ORDER,
        "correctness_counts": dict(correctness),
        "intention_to_treat_run_count": len(rows),
        "pairwise_effects": pairwise,
        "notes": [
            "Percent change is treatment minus baseline over baseline.",
            "Pass/pass sensitivity and bootstrap confidence intervals should be generated for final public evidence.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze router-effect-v1 benchmark output.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--metric", default="exact_uncached_input_tokens")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = analyze(args.root, metric=args.metric)
    to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
