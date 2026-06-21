#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from statistics import NormalDist

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmarks.analyze_real_agent_study import paired_log_ratios
from scripts.lib.agent_session import to_json_file


PREREGISTERED_COMPARISONS = [
    ("A-search-only", "B-search-summary"),
    ("A-search-only", "C-lsp-naive"),
    ("C-lsp-naive", "D-full-router"),
    ("A-search-only", "D-full-router"),
]
PRIMARY_COMPARISON = "A-search-only_to_D-full-router"


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def comparison_name(left: str, right: str) -> str:
    return f"{left}_to_{right}"


def validate_planning_inputs(*, minimum_effect: float, floor_repeats: int, alpha: float, power: float) -> None:
    if not 0.0 < minimum_effect < 1.0:
        raise ValueError("minimum_effect must be between 0 and 1")
    if floor_repeats < 1:
        raise ValueError("floor_repeats must be >= 1")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be between 0 and 1")
    if not 0.0 < power < 1.0:
        raise ValueError("power must be between 0 and 1")


def estimate_comparison(
    rows: list[dict[str, object]],
    *,
    metric: str,
    left: str,
    right: str,
    minimum_effect: float,
    floor_repeats: int,
    z_alpha: float,
    z_power: float,
) -> dict[str, object]:
    effects = paired_log_ratios(rows, metric=metric, left=left, right=right)
    logs = [float(row["log_ratio"]) for row in effects]
    target_log = abs(math.log(1.0 - minimum_effect))
    if len(logs) < 2:
        return {
            "status": "insufficient_pilot_data",
            "left_profile": left,
            "right_profile": right,
            "pair_count": len(logs),
            "observed_pairs": len(logs),
            "minimum_effect_log": round(target_log, 8),
            "recommended_pairs": floor_repeats,
            "recommended_repeats_floor": floor_repeats,
            "power_target_met": False,
        }
    variance = statistics.variance(logs)
    needed_pairs = math.ceil(((z_alpha + z_power) ** 2 * variance) / (target_log**2))
    recommended_pairs = max(needed_pairs, floor_repeats)
    return {
        "status": "estimated",
        "left_profile": left,
        "right_profile": right,
        "pair_count": len(logs),
        "pilot_log_ratio_variance": round(variance, 8),
        "minimum_effect_log": round(target_log, 8),
        "recommended_pairs": recommended_pairs,
        "observed_pairs": len(logs),
        "recommended_repeats_floor": floor_repeats,
        "power_target_met": len(logs) >= recommended_pairs,
    }


def estimate(
    rows: list[dict[str, object]],
    *,
    metric: str,
    minimum_effect: float,
    floor_repeats: int,
    alpha: float,
    power: float,
) -> dict[str, object]:
    validate_planning_inputs(minimum_effect=minimum_effect, floor_repeats=floor_repeats, alpha=alpha, power=power)
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1.0 - alpha / 2.0)
    z_power = normal.inv_cdf(power)
    pairwise = {
        comparison_name(left, right): estimate_comparison(
            rows,
            metric=metric,
            left=left,
            right=right,
            minimum_effect=minimum_effect,
            floor_repeats=floor_repeats,
            z_alpha=z_alpha,
            z_power=z_power,
        )
        for left, right in PREREGISTERED_COMPARISONS
    }
    primary = pairwise[PRIMARY_COMPARISON]
    pairwise_ready = all(item.get("status") == "estimated" and item.get("power_target_met") is True for item in pairwise.values())
    return {
        "status": "estimated" if primary.get("status") == "estimated" else "insufficient_pilot_data",
        "metric": metric,
        "cell_key_fields": ["agent", "task_id", "repo", "repeat_index"],
        "cluster_unit": "repository_task",
        "primary_comparison": PRIMARY_COMPARISON,
        "pair_count": primary.get("pair_count", 0),
        "pilot_log_ratio_variance": primary.get("pilot_log_ratio_variance"),
        "minimum_effect": minimum_effect,
        "minimum_effect_log": primary.get("minimum_effect_log"),
        "recommended_pairs": primary.get("recommended_pairs", floor_repeats),
        "observed_pairs": primary.get("observed_pairs", 0),
        "recommended_repeats_floor": floor_repeats,
        "alpha": alpha,
        "power": power,
        "z_alpha_two_sided": round(z_alpha, 8),
        "z_power": round(z_power, 8),
        "pairwise_power": pairwise,
        "all_preregistered_comparisons_power_target_met": pairwise_ready,
        "power_target_met": primary.get("power_target_met") is True and pairwise_ready,
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
    try:
        result = estimate(
            load_jsonl(Path(args.runs)),
            metric=args.metric,
            minimum_effect=args.minimum_effect,
            floor_repeats=args.floor_repeats,
            alpha=args.alpha,
            power=args.power,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
