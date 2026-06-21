#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
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


def row_passes(row: dict[str, object]) -> bool:
    status = str(row.get("oracle_status") or row.get("correctness_status") or "")
    return status == "pass"


def paired_log_ratios(
    rows: list[dict[str, object]],
    *,
    metric: str,
    left: str,
    right: str,
    pass_pass_only: bool = False,
) -> list[dict[str, object]]:
    by_cell: dict[tuple[str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        key = (str(row.get("agent", "")), str(row.get("task_id", "")), int(row.get("repeat_index", 0)))
        by_cell[key][str(row.get("profile", ""))] = row
    result: list[dict[str, object]] = []
    for key, profiles in by_cell.items():
        if left not in profiles or right not in profiles:
            continue
        if pass_pass_only and (not row_passes(profiles[left]) or not row_passes(profiles[right])):
            continue
        left_value = numeric(profiles[left], metric)
        right_value = numeric(profiles[right], metric)
        if left_value is None or right_value is None:
            continue
        result.append(
            {
                "agent": key[0],
                "task_id": key[1],
                "repo": profiles[left].get("repo", ""),
                "task_family": profiles[left].get("task_family", ""),
                "repeat_index": key[2],
                "left_profile": left,
                "right_profile": right,
                "left_sequence_position": profiles[left].get("sequence_position"),
                "right_sequence_position": profiles[right].get("sequence_position"),
                "left": left_value,
                "right": right_value,
                "log_ratio": math.log(right_value / left_value),
                "percent_change": (right_value - left_value) / left_value * 100.0,
            }
        )
    return result


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def cluster_bootstrap_log_ci(rows: list[dict[str, object]], *, iterations: int = 1000, seed: int = 12345) -> dict[str, float]:
    if not rows:
        return {}
    by_task: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_task[str(row["task_id"])].append(float(row["log_ratio"]))
    tasks = sorted(by_task)
    if not tasks:
        return {}
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(iterations):
        sample_logs: list[float] = []
        for _task in tasks:
            picked = rng.choice(tasks)
            sample_logs.extend(by_task[picked])
        if sample_logs:
            estimates.append((math.exp(statistics.mean(sample_logs)) - 1.0) * 100.0)
    return {
        "lower": round(percentile(estimates, 0.025), 2),
        "upper": round(percentile(estimates, 0.975), 2),
    }


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
        "cluster_bootstrap_95ci_percent": cluster_bootstrap_log_ci(rows),
    }


def grouped_effects(rows: list[dict[str, object]], *, group_key: str) -> dict[str, dict[str, object]]:
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        value = row.get(group_key)
        if value in {"", None}:
            value = "unknown"
        groups[str(value)].append(row)
    return {key: summarize_effect(values) for key, values in sorted(groups.items())}


def binomial_cdf(k: int, n: int, p: float = 0.5) -> float:
    if n <= 0:
        return 1.0
    return sum(math.comb(n, i) * (p**i) * ((1.0 - p) ** (n - i)) for i in range(k + 1))


def mcnemar_exact_p(left_only: int, right_only: int) -> float:
    discordant = left_only + right_only
    if discordant == 0:
        return 1.0
    return min(1.0, 2.0 * binomial_cdf(min(left_only, right_only), discordant, 0.5))


def paired_correctness(rows: list[dict[str, object]], *, left: str, right: str, noninferiority_margin: float) -> dict[str, object]:
    by_cell: dict[tuple[str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        key = (str(row.get("agent", "")), str(row.get("task_id", "")), int(row.get("repeat_index", 0)))
        by_cell[key][str(row.get("profile", ""))] = row
    both_pass = left_only = right_only = neither_pass = 0
    for profiles in by_cell.values():
        if left not in profiles or right not in profiles:
            continue
        left_pass = row_passes(profiles[left])
        right_pass = row_passes(profiles[right])
        if left_pass and right_pass:
            both_pass += 1
        elif left_pass and not right_pass:
            left_only += 1
        elif right_pass and not left_pass:
            right_only += 1
        else:
            neither_pass += 1
    total = both_pass + left_only + right_only + neither_pass
    left_passes = both_pass + left_only
    right_passes = both_pass + right_only
    pass_rate_difference = ((right_passes - left_passes) / total) if total else 0.0
    return {
        "pair_count": total,
        "left_profile": left,
        "right_profile": right,
        "both_pass": both_pass,
        "left_only_pass": left_only,
        "right_only_pass": right_only,
        "neither_pass": neither_pass,
        "left_pass_rate": round(left_passes / total, 4) if total else 0.0,
        "right_pass_rate": round(right_passes / total, 4) if total else 0.0,
        "right_minus_left_pass_rate": round(pass_rate_difference, 4),
        "mcnemar_exact_p": round(mcnemar_exact_p(left_only, right_only), 6),
        "noninferiority_margin": noninferiority_margin,
        "noninferiority_passed": pass_rate_difference >= -noninferiority_margin if total else False,
    }


def block_metric_rows(rows: list[dict[str, object]], *, metric: str, pass_all_only: bool = False) -> list[dict[str, object]]:
    by_cell: dict[tuple[str, str, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        key = (str(row.get("agent", "")), str(row.get("task_id", "")), int(row.get("repeat_index", 0)))
        by_cell[key][str(row.get("profile", ""))] = row
    blocks: list[dict[str, object]] = []
    for key, profiles in by_cell.items():
        if any(profile not in profiles for profile in FACTORIAL_ARM_ORDER):
            continue
        if pass_all_only and any(not row_passes(profiles[profile]) for profile in FACTORIAL_ARM_ORDER):
            continue
        values: dict[str, float] = {}
        for profile in FACTORIAL_ARM_ORDER:
            value = numeric(profiles[profile], metric)
            if value is None:
                break
            values[profile] = value
        if len(values) != len(FACTORIAL_ARM_ORDER):
            continue
        exemplar = profiles[FACTORIAL_ARM_ORDER[0]]
        blocks.append(
            {
                "agent": key[0],
                "task_id": key[1],
                "task_family": exemplar.get("task_family", ""),
                "repo": exemplar.get("repo", ""),
                "repeat_index": key[2],
                "values": values,
            }
        )
    return blocks


def factorial_effect_rows(rows: list[dict[str, object]], *, metric: str, pass_all_only: bool = False) -> dict[str, list[dict[str, object]]]:
    blocks = block_metric_rows(rows, metric=metric, pass_all_only=pass_all_only)
    effects: dict[str, list[dict[str, object]]] = {
        "semantic_access_main_effect": [],
        "routing_discipline_main_effect": [],
        "interaction": [],
    }
    for block in blocks:
        values = dict(block["values"])
        logs = {profile: math.log(float(value)) for profile, value in values.items()}
        effect_values = {
            "semantic_access_main_effect": ((logs["C-lsp-naive"] + logs["D-full-router"]) / 2.0)
            - ((logs["A-search-only"] + logs["B-search-summary"]) / 2.0),
            "routing_discipline_main_effect": ((logs["B-search-summary"] + logs["D-full-router"]) / 2.0)
            - ((logs["A-search-only"] + logs["C-lsp-naive"]) / 2.0),
            "interaction": logs["D-full-router"] - logs["C-lsp-naive"] - logs["B-search-summary"] + logs["A-search-only"],
        }
        for name, value in effect_values.items():
            effects[name].append(
                {
                    "task_id": block["task_id"],
                    "task_family": block.get("task_family", ""),
                    "repo": block.get("repo", ""),
                    "log_ratio": value,
                    "percent_change": (math.exp(value) - 1.0) * 100.0,
                }
            )
    return effects


def summarize_factorial_effects(rows: list[dict[str, object]], *, metric: str, pass_all_only: bool = False) -> dict[str, object]:
    effects = factorial_effect_rows(rows, metric=metric, pass_all_only=pass_all_only)
    return {name: summarize_effect(values) for name, values in effects.items()}


def summarize_factorial_effects_by_group(
    rows: list[dict[str, object]],
    *,
    metric: str,
    group_key: str,
    pass_all_only: bool = False,
) -> dict[str, object]:
    effects = factorial_effect_rows(rows, metric=metric, pass_all_only=pass_all_only)
    return {name: grouped_effects(values, group_key=group_key) for name, values in effects.items()}


def holm_correct_pairwise(correctness_pairwise: dict[str, dict[str, object]], *, alpha: float = 0.05) -> dict[str, object]:
    p_values: list[tuple[str, float]] = []
    for name, result in correctness_pairwise.items():
        value = result.get("mcnemar_exact_p")
        if isinstance(value, int | float):
            p_values.append((name, float(value)))
    ordered = sorted(p_values, key=lambda item: item[1])
    adjusted: dict[str, dict[str, object]] = {}
    running_max = 0.0
    total = len(ordered)
    for rank, (name, p_value) in enumerate(ordered, start=1):
        adjusted_p = min(1.0, p_value * (total - rank + 1))
        running_max = max(running_max, adjusted_p)
        adjusted[name] = {
            "raw_p": round(p_value, 6),
            "holm_adjusted_p": round(running_max, 6),
            "reject_alpha": running_max <= alpha,
        }
    return {
        "method": "holm",
        "alpha": alpha,
        "comparisons": adjusted,
    }


def load_pricing(path: str | Path | None) -> dict[str, float]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {str(key): float(value) for key, value in data.items()}


def estimate_row_cost(row: dict[str, object], pricing: dict[str, float]) -> float | None:
    if not pricing:
        return None
    uncached_input = numeric(row, "exact_uncached_input_tokens")
    cached_input = numeric(row, "exact_cached_input_tokens") or 0.0
    output = numeric(row, "exact_output_tokens") or 0.0
    reasoning = numeric(row, "exact_reasoning_output_tokens") or 0.0
    if uncached_input is None:
        return None
    return (
        uncached_input * pricing.get("input_per_1m", 0.0)
        + cached_input * pricing.get("cached_input_per_1m", 0.0)
        + output * pricing.get("output_per_1m", 0.0)
        + reasoning * pricing.get("reasoning_output_per_1m", 0.0)
    ) / 1_000_000.0


def summarize_costs(rows: list[dict[str, object]], pricing: dict[str, float]) -> dict[str, object]:
    if not pricing:
        return {"status": "not_configured"}
    by_arm: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        cost = estimate_row_cost(row, pricing)
        if cost is not None:
            by_arm[str(row.get("profile", ""))].append(cost)
    return {
        "status": "estimated" if by_arm else "missing_exact_token_inputs",
        "pricing_per_1m_tokens": pricing,
        "by_arm": {
            arm: {
                "run_count": len(values),
                "total_estimated_cost": round(sum(values), 6),
                "median_estimated_cost": round(statistics.median(values), 6),
            }
            for arm, values in sorted(by_arm.items())
        },
    }


def analyze(
    root: str | Path,
    *,
    metric: str,
    pricing: dict[str, float] | None = None,
    correctness_noninferiority_margin: float = 0.05,
) -> dict[str, object]:
    base = Path(root).expanduser().resolve()
    rows = load_jsonl(base / "runs.jsonl")
    correctness = Counter(str(row.get("oracle_status") or row.get("correctness_status", "")) for row in rows)
    pairwise = {}
    pass_pass_pairwise = {}
    pairwise_by_task_family = {}
    pairwise_by_repo = {}
    pairwise_by_sequence_position = {}
    correctness_pairwise = {}
    for left, right in [
        ("A-search-only", "B-search-summary"),
        ("A-search-only", "C-lsp-naive"),
        ("C-lsp-naive", "D-full-router"),
        ("A-search-only", "D-full-router"),
    ]:
        effects = paired_log_ratios(rows, metric=metric, left=left, right=right)
        comparison = f"{left}_to_{right}"
        pairwise[comparison] = summarize_effect(effects)
        pairwise_by_task_family[comparison] = grouped_effects(effects, group_key="task_family")
        pairwise_by_repo[comparison] = grouped_effects(effects, group_key="repo")
        pairwise_by_sequence_position[comparison] = grouped_effects(effects, group_key="right_sequence_position")
        pass_pass_effects = paired_log_ratios(rows, metric=metric, left=left, right=right, pass_pass_only=True)
        pass_pass_pairwise[comparison] = summarize_effect(pass_pass_effects)
        correctness_pairwise[comparison] = paired_correctness(
            rows,
            left=left,
            right=right,
            noninferiority_margin=correctness_noninferiority_margin,
        )
    return {
        "analysis_id": "router-effect-v1",
        "metric": metric,
        "run_count": len(rows),
        "arm_counts": dict(Counter(str(row.get("profile", "")) for row in rows)),
        "expected_arms": FACTORIAL_ARM_ORDER,
        "correctness_counts": dict(correctness),
        "correctness_pairwise": correctness_pairwise,
        "correctness_noninferiority_margin": correctness_noninferiority_margin,
        "intention_to_treat_run_count": len(rows),
        "pairwise_effects": pairwise,
        "pairwise_effects_by_task_family": pairwise_by_task_family,
        "pairwise_effects_by_repo": pairwise_by_repo,
        "pairwise_effects_by_sequence_position": pairwise_by_sequence_position,
        "pass_pass_sensitivity_pairwise_effects": pass_pass_pairwise,
        "factorial_effects": summarize_factorial_effects(rows, metric=metric),
        "factorial_effects_by_task_family": summarize_factorial_effects_by_group(rows, metric=metric, group_key="task_family"),
        "factorial_effects_by_repo": summarize_factorial_effects_by_group(rows, metric=metric, group_key="repo"),
        "pass_all_sensitivity_factorial_effects": summarize_factorial_effects(rows, metric=metric, pass_all_only=True),
        "multiple_comparison_correction": holm_correct_pairwise(correctness_pairwise),
        "cost": summarize_costs(rows, pricing or {}),
        "notes": [
            "Percent change is treatment minus baseline over baseline.",
            "Cluster bootstrap intervals resample task ids, not tool calls or token events.",
            "Sequence-position effects group each pair by the treatment arm's Latin-square position.",
            "Repository-stratified effects must be anonymized before public release.",
            "Estimated cost is optional and requires explicit model pricing inputs.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze router-effect-v1 benchmark output.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--metric", default="exact_uncached_input_tokens")
    parser.add_argument("--pricing", help="Optional JSON pricing file with per-1M token prices.")
    parser.add_argument("--correctness-noninferiority-margin", type=float, default=0.05)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    result = analyze(
        args.root,
        metric=args.metric,
        pricing=load_pricing(args.pricing),
        correctness_noninferiority_margin=args.correctness_noninferiority_margin,
    )
    to_json_file(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
