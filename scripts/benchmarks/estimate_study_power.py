#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.analyze_real_agent_study import paired_log_ratios
from scripts.lib.agent_session import to_json_file


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def estimate(
    rows: list[dict[str, object]],
    *,
    metric: str,
    minimum_effect: float,
    floor_repeats: int,
    alpha: float,
    power: float,
) -> dict[str, object]:
    effects = paired_log_ratios(rows, metric=metric, left="A-search-only", right="D-full-router")
    logs = [float(row["log_ratio"]) for row in effects]
    if len(logs) < 2:
        return {
            "status": "insufficient_pilot_data",
            "metric": metric,
            "pair_count": len(logs),
            "minimum_effect": minimum_effect,
            "recommended_repeats": floor_repeats,
            "alpha": alpha,
            "power": power,
            "power_target_met": False,
        }
    variance = statistics.variance(logs)
    target_log = abs(math.log(1.0 - minimum_effect))
    # Normal-approximation planning constant for two-sided alpha=.05, power=.80.
    needed_pairs = math.ceil(((1.96 + 0.84) ** 2 * variance) / (target_log**2))
    return {
        "status": "estimated",
        "metric": metric,
        "pair_count": len(logs),
        "pilot_log_ratio_variance": round(variance, 8),
        "minimum_effect": minimum_effect,
        "minimum_effect_log": round(target_log, 8),
        "recommended_pairs": max(needed_pairs, floor_repeats),
        "observed_pairs": len(logs),
        "recommended_repeats_floor": floor_repeats,
        "alpha": alpha,
        "power": power,
        "power_target_met": len(logs) >= max(needed_pairs, floor_repeats),
        "method": "normal_approximation_on_paired_log_ratios",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estimate confirmatory study size from pilot paired log-ratio variance.")
    parser.add_argument("--runs", required=True)
    parser.add_argument("--metric", default="exact_uncached_input_tokens")
    parser.add_argument("--minimum-effect", type=float, default=0.15)
    parser.add_argument("--floor-repeats", type=int, default=4)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--power", type=float, default=0.80)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = estimate(
        load_jsonl(Path(args.runs)),
        metric=args.metric,
        minimum_effect=args.minimum_effect,
        floor_repeats=args.floor_repeats,
        alpha=args.alpha,
        power=args.power,
    )
    to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
