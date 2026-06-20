#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_DIR = ROOT / "benchmarks" / "real-agent-routing" / "evidence" / "codex-ad-smoke-anonymized"
DEFAULT_SOURCE = DEFAULT_EVIDENCE_DIR / "source.sanitized.json"
DEFAULT_ASSET = ROOT / "docs" / "assets" / "codex-ad-smoke-results.svg"
PROFILE_DIR = ROOT / "benchmarks" / "real-agent-routing" / "profiles"


EVIDENCE_FILES = [
    "source.sanitized.json",
    "README.md",
    "summary.sanitized.json",
    "runs.sanitized.jsonl",
    "route-isolation.sanitized.jsonl",
    "claim-readiness.sanitized.json",
    "audit.sanitized.json",
    "evidence-manifest.sanitized.json",
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_sha256_short(path: Path) -> str:
    return file_sha256(path)[:24]


def fmt_int(value: int | float) -> str:
    return f"{int(value):,}"


def fmt_float(value: int | float) -> str:
    return f"{float(value):.2f}"


def percent_reduction(baseline: int | float, treatment: int | float) -> float:
    return round(((baseline - treatment) / baseline) * 100, 2) if baseline else 0.0


def percent_increase(baseline: int | float, treatment: int | float) -> float:
    return round(((treatment - baseline) / baseline) * 100, 2) if baseline else 0.0


def rows_by_target_profile(source: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["target_id"], row["profile"]): row for row in source["runs"]}


def paired_results(source: dict[str, Any]) -> list[dict[str, Any]]:
    by_key = rows_by_target_profile(source)
    rows: list[dict[str, Any]] = []
    for target_id, target in source["targets"].items():
        baseline = by_key[(target_id, "A-search-only")]
        treatment = by_key[(target_id, "D-full-router")]
        avoided = baseline["exact_uncached_total_tokens"] - treatment["exact_uncached_total_tokens"]
        rows.append(
            {
                "baseline_exact_uncached_total_tokens": baseline["exact_uncached_total_tokens"],
                "baseline_hard_isolated_search_only": baseline["mcp_servers_hard_disabled"],
                "baseline_profile": "A-search-only",
                "correctness_ok": baseline["correctness_status"] == "pass"
                and treatment["correctness_status"] == "pass",
                "target_id": target_id,
                "target_label": target["label"],
                "tool_evidence_observed": baseline["tool_evidence_source"] == "observed"
                and treatment["tool_evidence_source"] == "observed",
                "treatment_exact_uncached_total_tokens": treatment["exact_uncached_total_tokens"],
                "treatment_profile": "D-full-router",
                "treatment_semantic_tools_observed": treatment["semantic_tool_count"] > 0,
                "uncached_token_reduction_percent": percent_reduction(
                    baseline["exact_uncached_total_tokens"],
                    treatment["exact_uncached_total_tokens"],
                ),
                "uncached_tokens_avoided": avoided,
            }
        )
    return rows


def tradeoff_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    by_key = rows_by_target_profile(source)
    rows: list[dict[str, Any]] = []
    for target_id, target in source["targets"].items():
        baseline = by_key[(target_id, "A-search-only")]
        treatment = by_key[(target_id, "D-full-router")]
        rows.append(
            {
                "baseline_exact_total_tokens": baseline["exact_total_tokens"],
                "baseline_model_visible_proxy_tokens": baseline["model_visible_proxy_tokens"],
                "baseline_tool_output_bytes": baseline["tool_output_bytes"],
                "baseline_wall_seconds": baseline["wall_seconds"],
                "model_visible_proxy_token_reduction_percent": percent_reduction(
                    baseline["model_visible_proxy_tokens"],
                    treatment["model_visible_proxy_tokens"],
                ),
                "target_id": target_id,
                "target_label": target["label"],
                "tool_output_byte_reduction_percent": percent_reduction(
                    baseline["tool_output_bytes"],
                    treatment["tool_output_bytes"],
                ),
                "treatment_exact_total_token_increase_percent": percent_increase(
                    baseline["exact_total_tokens"],
                    treatment["exact_total_tokens"],
                ),
                "treatment_exact_total_tokens": treatment["exact_total_tokens"],
                "treatment_extra_exact_total_tokens": treatment["exact_total_tokens"]
                - baseline["exact_total_tokens"],
                "treatment_model_visible_proxy_tokens": treatment["model_visible_proxy_tokens"],
                "treatment_tool_output_bytes": treatment["tool_output_bytes"],
                "treatment_wall_seconds": treatment["wall_seconds"],
                "wall_time_ratio_treatment_over_baseline": round(
                    treatment["wall_seconds"] / baseline["wall_seconds"],
                    2,
                ),
            }
        )
    return rows


def combined_tradeoff(pairs: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_uncached = sum(row["baseline_exact_uncached_total_tokens"] for row in pairs)
    treatment_uncached = sum(row["treatment_exact_uncached_total_tokens"] for row in pairs)
    baseline_total = sum(row["baseline_exact_total_tokens"] for row in trades)
    treatment_total = sum(row["treatment_exact_total_tokens"] for row in trades)
    baseline_wall = round(sum(row["baseline_wall_seconds"] for row in trades), 3)
    treatment_wall = round(sum(row["treatment_wall_seconds"] for row in trades), 3)
    baseline_tool_output = sum(row["baseline_tool_output_bytes"] for row in trades)
    treatment_tool_output = sum(row["treatment_tool_output_bytes"] for row in trades)
    return {
        "baseline_exact_total_tokens": baseline_total,
        "baseline_exact_uncached_total_tokens": baseline_uncached,
        "baseline_tool_output_bytes": baseline_tool_output,
        "baseline_wall_seconds": baseline_wall,
        "tool_output_byte_reduction_percent": percent_reduction(
            baseline_tool_output,
            treatment_tool_output,
        ),
        "treatment_exact_total_token_increase_percent": percent_increase(
            baseline_total,
            treatment_total,
        ),
        "treatment_exact_total_tokens": treatment_total,
        "treatment_exact_uncached_total_tokens": treatment_uncached,
        "treatment_extra_exact_total_tokens": treatment_total - baseline_total,
        "treatment_tool_output_bytes": treatment_tool_output,
        "treatment_wall_seconds": treatment_wall,
        "uncached_token_reduction_percent": percent_reduction(baseline_uncached, treatment_uncached),
        "uncached_tokens_avoided": baseline_uncached - treatment_uncached,
        "wall_time_ratio_treatment_over_baseline": round(treatment_wall / baseline_wall, 2),
    }


def build_summary(source: dict[str, Any]) -> dict[str, Any]:
    pairs = paired_results(source)
    trades = tradeoff_rows(source)
    combined = combined_tradeoff(pairs, trades)
    return {
        "created_at": source["created_at"],
        "evidence_files": EVIDENCE_FILES,
        "paired_results": pairs,
        "pooled_descriptive_total": {
            "baseline_exact_uncached_total_tokens": combined["baseline_exact_uncached_total_tokens"],
            "interpretation": "Descriptive total across two smoke cells only; do not publish as a universal effect size.",
            "treatment_exact_uncached_total_tokens": combined["treatment_exact_uncached_total_tokens"],
            "uncached_token_reduction_percent": combined["uncached_token_reduction_percent"],
            "uncached_tokens_avoided": combined["uncached_tokens_avoided"],
        },
        "privacy_note": source["privacy_note"],
        "scope": source["scope"],
        "target_nature": {
            target_id: {
                "description": target["description"],
                "label": target["label"],
                "language_surface": target["language_surface"],
            }
            for target_id, target in source["targets"].items()
        },
        "title": source["title"],
        "trade_off": {
            "combined": combined,
            "interpretation": (
                "D-full-router reduced exact uncached token use and model-visible tool output in these "
                "smoke cells, while processing more exact total cached context and taking longer wall-clock time."
            ),
            "targets": trades,
        },
    }


def build_claim_readiness(source: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in source["claim_readiness"]["rows"]:
        treatment_minus_baseline = (
            row["treatment_exact_uncached_total_tokens"] - row["baseline_exact_uncached_total_tokens"]
        )
        rows.append(
            {
                **row,
                "treatment_minus_baseline_exact_uncached_tokens": treatment_minus_baseline,
                "uncached_tokens_avoided": -treatment_minus_baseline,
            }
        )
    return {
        "agent_reported_token_savings_claims_supported": sum(
            1 for row in rows if row["agent_reported_token_savings_claim_supported"]
        ),
        "exact_token_savings_claims_supported": sum(
            1 for row in rows if row["exact_token_savings_claim_supported"]
        ),
        "exact_uncached_token_savings_claims_supported": sum(
            1 for row in rows if row["exact_uncached_token_savings_claim_supported"]
        ),
        "model_visible_proxy_savings_claims_supported": sum(
            1 for row in rows if row["model_visible_proxy_savings_claim_supported"]
        ),
        "paired_comparisons": len(rows),
        "rows": rows,
        "scope": source["claim_readiness"]["scope"],
    }


def build_manifest(source: dict[str, Any], out_dir: Path, asset_path: Path) -> dict[str, Any]:
    route_profile_hashes = {
        "A-search-only": file_sha256_short(PROFILE_DIR / "A-search-only.yaml"),
        "D-full-router": file_sha256_short(PROFILE_DIR / "D-full-router.yaml"),
    }
    targets = {}
    for target_id, target in source["targets"].items():
        targets[target_id] = {
            "exact_uncached_claim_supported": target["exact_uncached_claim_supported"],
            "language_surface": target["language_surface"],
            "opaque_pairing_ids": {
                "source_state_opaque_id": target["source_state_opaque_id"],
                "target_symbol_opaque_id": target["target_symbol_opaque_id"],
                "task_prompt_opaque_id": target["task_prompt_opaque_id"],
            },
            "order_randomized": target["order_randomized"],
            "random_seed": target["random_seed"],
            "route_profile_hashes": route_profile_hashes,
            "run_order_profiles": target["run_order_profiles"],
            "scoped_smoke_audit_status": target["scoped_smoke_audit_status"],
            "snapshot_repos": target["snapshot_repos"],
            "source_repo_dirty_at_smoke": target["source_repo_dirty_at_smoke"],
            "source_state_opaque_id": target["source_state_opaque_id"],
            "target_label": target["label"],
            "task_family": target["task_family"],
        }
    canonical_output = out_dir == DEFAULT_EVIDENCE_DIR and asset_path == DEFAULT_ASSET
    if canonical_output:
        artifact_path_mode = "canonical_repo_relative"
        evidence_directory = "benchmarks/real-agent-routing/evidence/codex-ad-smoke-anonymized"
        artifact_paths = {
            "docs/assets/codex-ad-smoke-results.svg": asset_path,
            **{
                f"benchmarks/real-agent-routing/evidence/codex-ad-smoke-anonymized/{name}": out_dir / name
                for name in EVIDENCE_FILES
                if name != "evidence-manifest.sanitized.json"
            },
        }
    else:
        artifact_path_mode = "custom_output_relative"
        evidence_directory = "custom-output"
        artifact_paths = {
            f"asset/{asset_path.name}": asset_path,
            **{f"evidence/{name}": out_dir / name for name in EVIDENCE_FILES if name != "evidence-manifest.sanitized.json"},
        }
    artifact_hashes = {rel: file_sha256(path) for rel, path in artifact_paths.items()}
    return {
        "artifact_hashes_sha256": artifact_hashes,
        "artifact_hashes_sha256_note": "The manifest file is excluded to avoid a self-referential hash.",
        "artifact_path_mode": artifact_path_mode,
        "evidence_directory": evidence_directory,
        "limitations": source["limitations"],
        "privacy_policy": {
            "hmac_required_for_future_private_value_fingerprints": True,
            "local_paths_published": False,
            "opaque_public_ids_used_for_private_pairing": True,
            "plain_private_value_hashes_published": False,
            "private_repo_commits_published": False,
            "private_repo_names_published": False,
            "raw_final_answers_published": False,
            "raw_prompts_published": False,
            "raw_transcripts_published": False,
        },
        "schema_version": 2,
        "targets": targets,
        "title": "Sanitized evidence manifest for Codex A/D smoke results",
        "version_capture": source["version_capture"],
    }


def build_readme(source: dict[str, Any], summary: dict[str, Any]) -> str:
    pairs = summary["paired_results"]
    trades = summary["trade_off"]["targets"]
    combined = summary["trade_off"]["combined"]
    text = """# Anonymized Codex A/D Live Smoke Results

This bundle publishes private live smoke numbers without company names, repository names, local paths, raw prompts, transcripts, final answers, or exact private repository commits.

## Scope

- Agent: Codex live subject-agent path.
- Compared arms: `A-search-only` versus `D-full-router`.
- Task family: known-symbol definition lookup.
- Cells: 2 private targets x 2 arms x 1 repeat = 4 live cells.
- Claim boundary: full router system effect smoke evidence only, not LSP-only attribution and not a publishable general benchmark conclusion.

## Target Nature

"""
    for target in source["targets"].values():
        text += f"- **{target['label']}**: {target['description']} Surface: {target['language_surface']}.\n"

    text += """
## Exact Uncached Token Results

| Anonymous Target | A exact uncached | D exact uncached | Uncached tokens avoided | Uncached-token reduction |
|---|---:|---:|---:|---:|
"""
    for row in pairs:
        text += (
            f"| {row['target_label']} | {fmt_int(row['baseline_exact_uncached_total_tokens'])} | "
            f"{fmt_int(row['treatment_exact_uncached_total_tokens'])} | "
            f"{fmt_int(row['uncached_tokens_avoided'])} | "
            f"{fmt_float(row['uncached_token_reduction_percent'])}% |\n"
        )
    text += (
        f"| Descriptive total | {fmt_int(combined['baseline_exact_uncached_total_tokens'])} | "
        f"{fmt_int(combined['treatment_exact_uncached_total_tokens'])} | "
        f"{fmt_int(combined['uncached_tokens_avoided'])} | "
        f"{fmt_float(combined['uncached_token_reduction_percent'])}% |\n"
    )
    text += """
The descriptive total is only a compact description of these two smoke cells. It should not be reported as a universal token-saving estimate.

## Trade-Offs

In these smoke runs, `D-full-router` reduced uncached token use and model-visible tool output, but processed more total cached context and took roughly 2.6x as long. This is a context-efficiency result, not an overall compute or latency reduction.

| Anonymous Target | A exact total | D exact total | D total-token change | A wall_s | D wall_s | D/A wall time | Tool output reduction |
|---|---:|---:|---:|---:|---:|---:|---:|
"""
    for row in trades:
        text += (
            f"| {row['target_label']} | {fmt_int(row['baseline_exact_total_tokens'])} | "
            f"{fmt_int(row['treatment_exact_total_tokens'])} | "
            f"+{fmt_float(row['treatment_exact_total_token_increase_percent'])}% | "
            f"{row['baseline_wall_seconds']:.3f} | {row['treatment_wall_seconds']:.3f} | "
            f"{row['wall_time_ratio_treatment_over_baseline']:.2f}x | "
            f"{fmt_float(row['tool_output_byte_reduction_percent'])}% |\n"
        )
    text += (
        f"| Descriptive total | {fmt_int(combined['baseline_exact_total_tokens'])} | "
        f"{fmt_int(combined['treatment_exact_total_tokens'])} | "
        f"+{fmt_float(combined['treatment_exact_total_token_increase_percent'])}% | "
        f"{combined['baseline_wall_seconds']:.3f} | {combined['treatment_wall_seconds']:.3f} | "
        f"{combined['wall_time_ratio_treatment_over_baseline']:.2f}x | "
        f"{fmt_float(combined['tool_output_byte_reduction_percent'])}% |\n"
    )
    text += """
## Tool And Isolation Evidence

| Anonymous Target | Arm | Tool evidence | Observed task tools | Search count | Semantic tool count | Hard search-only isolation | Policy violations |
|---|---|---|---|---:|---:|---|---|
"""
    for row in source["runs"]:
        hard = "yes" if row["mcp_servers_hard_disabled"] else "no"
        tools = ", ".join(row["observed_task_tools"])
        violations = "none" if not row["policy_violations"] else str(len(row["policy_violations"]))
        text += (
            f"| {row['target_label']} | {row['profile']} | {row['tool_evidence_source']} | "
            f"{tools} | {row['search_count']} | {row['semantic_tool_count']} | {hard} | {violations} |\n"
        )
    text += """
## Full Metric Table

| Anonymous Target | Arm | exact_input | cached_input | uncached_input | exact_output | reasoning_output | exact_total | exact_uncached_total | usage_events | wall_s | tool_calls | files_opened | tool_output_bytes | proxy_tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
"""
    for row in source["runs"]:
        text += (
            f"| {row['target_label']} | {row['profile']} | {fmt_int(row['exact_input_tokens'])} | "
            f"{fmt_int(row['exact_cached_input_tokens'])} | {fmt_int(row['exact_uncached_input_tokens'])} | "
            f"{fmt_int(row['exact_output_tokens'])} | {fmt_int(row['exact_reasoning_output_tokens'])} | "
            f"{fmt_int(row['exact_total_tokens'])} | {fmt_int(row['exact_uncached_total_tokens'])} | "
            f"{row['usage_event_count']} | {row['wall_seconds']:.3f} | {row['tool_call_count']} | "
            f"{row['files_opened_count']} | {fmt_int(row['tool_output_bytes'])} | "
            f"{fmt_int(row['model_visible_proxy_tokens'])} |\n"
        )
    text += """
## Sanitized Evidence Files

- `source.sanitized.json`: single source artifact for the generated public evidence.
- `summary.sanitized.json`: headline metrics, target nature, scope, and trade-off fields.
- `runs.sanitized.jsonl`: one sanitized row per live cell.
- `route-isolation.sanitized.jsonl`: command shape and route-isolation controls with local paths removed.
- `claim-readiness.sanitized.json`: supported and blocked token-savings claim types.
- `audit.sanitized.json`: scoped smoke audit result and requirement statuses.
- `evidence-manifest.sanitized.json`: artifact hashes, opaque pairing IDs, route-profile hashes, and not-captured version fields.

## Interpretation

These four live cells show that the benchmark can hard-isolate the search-only baseline, run a Serena-enabled full-router treatment, capture exact uncached token telemetry, and observe tool evidence. In both private smoke cells, the full-router arm consumed fewer exact uncached tokens than the hard-isolated search-only baseline.

This does not establish LSP-only causality, generalize across task families, or estimate run-to-run variance. A publishable study still needs more task families, more repeats, counterbalanced order, clean snapshots, tool/model version capture, and a larger sanitized evidence bundle.
"""
    return text


def svg_text(x: int, y: int, value: str, *, size: int = 28, weight: int = 400, fill: str = "#172033") -> str:
    return f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}">{html.escape(value)}</text>'


def build_svg(source: dict[str, Any], summary: dict[str, Any]) -> str:
    pairs = summary["paired_results"]
    trades = {row["target_id"]: row for row in summary["trade_off"]["targets"]}
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000" role="img" aria-labelledby="title desc">',
        '<title id="title">Anonymized Codex A/D Smoke Results</title>',
        '<desc id="desc">Exact uncached token telemetry for two anonymized live smoke comparisons.</desc>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;}</style>',
        '<rect width="1600" height="1000" fill="#f6f9fc"/>',
        '<rect x="70" y="70" width="1460" height="845" rx="28" fill="#ffffff" stroke="#b8c8dd" stroke-width="2"/>',
        svg_text(125, 175, "Codex A/D Smoke Results", size=56, weight=800),
        svg_text(128, 220, "Privacy-safe exact uncached token telemetry from live smoke cells", size=30, fill="#506076"),
    ]
    chips = [
        ("2 targets", "#2866b8"),
        ("A/D comparison", "#1d9c99"),
        ("1 repeat smoke", "#aa690f"),
        ("system effect", "#314155"),
    ]
    chip_x = 128
    for label, fill in chips:
        width = 18 + len(label) * 13
        parts.append(f'<rect x="{chip_x}" y="242" width="{width}" height="38" rx="19" fill="{fill}"/>')
        parts.append(svg_text(chip_x + 17, 268, label, size=20, weight=700, fill="#ffffff"))
        chip_x += width + 16
    y = 330
    for pair in pairs:
        target = source["targets"][pair["target_id"]]
        trade = trades[pair["target_id"]]
        baseline = pair["baseline_exact_uncached_total_tokens"]
        treatment = pair["treatment_exact_uncached_total_tokens"]
        parts.extend(
            [
                f'<rect x="110" y="{y}" width="1380" height="220" rx="22" fill="#f8fbfe" stroke="#d2dde9"/>',
                svg_text(150, y + 58, target["label"], size=30, weight=800),
                svg_text(150, y + 90, target["language_surface"], size=22, fill="#536276"),
                svg_text(150, y + 150, f"D used {fmt_float(pair['uncached_token_reduction_percent'])}% fewer", size=34, weight=800, fill="#13766f"),
                svg_text(
                    150,
                    y + 180,
                    f"A {fmt_int(baseline)} -> D {fmt_int(treatment)} | avoided {fmt_int(pair['uncached_tokens_avoided'])} uncached tokens",
                    size=23,
                    fill="#00776d",
                ),
                svg_text(
                    150,
                    y + 200,
                    f"Trade-off: exact total +{fmt_float(trade['treatment_exact_total_token_increase_percent'])}%, wall time {trade['wall_time_ratio_treatment_over_baseline']:.2f}x",
                    size=18,
                    fill="#536276",
                ),
            ]
        )
        y += 245
    parts.extend(
        [
            '<rect x="110" y="806" width="1380" height="70" rx="16" fill="#ffffff" stroke="#d4deeb"/>',
            '<rect x="150" y="831" width="34" height="22" rx="6" fill="#2866b8"/>',
            svg_text(200, 850, "A-search-only baseline", size=22),
            '<rect x="720" y="831" width="34" height="22" rx="6" fill="#1d9c99"/>',
            svg_text(770, 850, "D-full-router", size=22),
            svg_text(150, 898, "Smoke evidence only: not LSP-only attribution, not a general benchmark conclusion.", size=20, fill="#a66000"),
            svg_text(1180, 948, "sanitized generated public artifact", size=20, fill="#738296"),
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def build_outputs(source: dict[str, Any], out_dir: Path, asset_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(source)
    claim = build_claim_readiness(source)

    write_json(out_dir / "source.sanitized.json", source)
    write_jsonl(out_dir / "runs.sanitized.jsonl", source["runs"])
    write_jsonl(out_dir / "route-isolation.sanitized.jsonl", source["route_isolation"])
    write_json(out_dir / "claim-readiness.sanitized.json", claim)
    write_json(out_dir / "audit.sanitized.json", source["audit"])
    write_json(out_dir / "summary.sanitized.json", summary)
    (out_dir / "README.md").write_text(build_readme(source, summary), encoding="utf-8")
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_text(build_svg(source, summary), encoding="utf-8")
    manifest = build_manifest(source, out_dir, asset_path)
    write_json(out_dir / "evidence-manifest.sanitized.json", manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build generated public smoke evidence from one sanitized source file.")
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", default=DEFAULT_EVIDENCE_DIR)
    parser.add_argument("--asset", default=DEFAULT_ASSET)
    args = parser.parse_args(argv)

    source = load_json(Path(args.source).expanduser().resolve())
    build_outputs(source, Path(args.out_dir).expanduser().resolve(), Path(args.asset).expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
