from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.benchmarks import build_public_smoke_evidence as generator
from scripts.benchmarks.shared.check_public_sanitization import png_metadata_chunks


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "benchmarks" / "real-agent-routing" / "evidence" / "codex-ad-smoke-anonymized"
ASSET = ROOT / "docs" / "assets" / "codex-ad-smoke-results.svg"


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CodexAdSmokeEvidenceTests(unittest.TestCase):
    def source(self) -> dict[str, object]:
        return json.loads((EVIDENCE / "source.sanitized.json").read_text(encoding="utf-8"))

    def test_summary_pairs_match_sanitized_rows(self) -> None:
        summary = json.loads((EVIDENCE / "summary.sanitized.json").read_text(encoding="utf-8"))
        rows = load_jsonl(EVIDENCE / "runs.sanitized.jsonl")
        by_target_profile = {(row["target_id"], row["profile"]): row for row in rows}

        for pair in summary["paired_results"]:
            baseline = by_target_profile[(pair["target_id"], pair["baseline_profile"])]
            treatment = by_target_profile[(pair["target_id"], pair["treatment_profile"])]

            self.assertEqual(
                pair["baseline_exact_uncached_total_tokens"],
                baseline["exact_uncached_total_tokens"],
            )
            self.assertEqual(
                pair["treatment_exact_uncached_total_tokens"],
                treatment["exact_uncached_total_tokens"],
            )
            self.assertEqual(
                pair["uncached_tokens_avoided"],
                baseline["exact_uncached_total_tokens"] - treatment["exact_uncached_total_tokens"],
            )

    def test_tradeoff_fields_show_total_token_and_latency_cost(self) -> None:
        summary = json.loads((EVIDENCE / "summary.sanitized.json").read_text(encoding="utf-8"))
        combined = summary["trade_off"]["combined"]

        self.assertGreater(combined["treatment_exact_total_tokens"], combined["baseline_exact_total_tokens"])
        self.assertGreater(combined["wall_time_ratio_treatment_over_baseline"], 2.0)
        self.assertGreater(combined["tool_output_byte_reduction_percent"], 0)
        self.assertAlmostEqual(
            combined["treatment_exact_total_token_increase_percent"],
            round(
                (
                    (combined["treatment_exact_total_tokens"] - combined["baseline_exact_total_tokens"])
                    / combined["baseline_exact_total_tokens"]
                )
                * 100,
                2,
            ),
        )

    def test_public_readme_uses_uncached_metric_wording_without_pooled_headline(self) -> None:
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Uncached tokens avoided", root_readme)
        self.assertIn("Uncached-token reduction", root_readme)
        self.assertIn("context-efficiency result", root_readme)
        self.assertIn("benchmarks/real-agent-routing/evidence/codex-ad-smoke-anonymized", root_readme)
        self.assertNotIn("| Descriptive total |", root_readme)
        self.assertIn("docs/assets/codex-ad-smoke-results.svg", root_readme)

    def test_evidence_manifest_publishes_opaque_ids_and_not_captured_versions(self) -> None:
        manifest = json.loads((EVIDENCE / "evidence-manifest.sanitized.json").read_text(encoding="utf-8"))

        self.assertTrue(manifest["privacy_policy"]["opaque_public_ids_used_for_private_pairing"])
        self.assertFalse(manifest["privacy_policy"]["plain_private_value_hashes_published"])
        self.assertTrue(manifest["privacy_policy"]["hmac_required_for_future_private_value_fingerprints"])
        for target in manifest["targets"].values():
            self.assertIn("source_state_opaque_id", target)
            self.assertIn("task_prompt_opaque_id", target["opaque_pairing_ids"])
            self.assertIn("target_symbol_opaque_id", target["opaque_pairing_ids"])
            self.assertNotIn("repository_snapshot_fingerprint", target)
            self.assertNotIn("task_prompt_hash", target)
            self.assertNotIn("target_symbol_hash", target)
            self.assertEqual(target["scoped_smoke_audit_status"], "pass")
            self.assertNotIn("strict_smoke_audit_status", target)
            self.assertEqual(target["run_order_profiles"], ["A-search-only", "D-full-router"])
        self.assertEqual(manifest["version_capture"]["model_identifier"], "not_captured_in_smoke")

    def test_claim_readiness_values_match_run_rows_without_ambiguous_delta(self) -> None:
        claim = json.loads((EVIDENCE / "claim-readiness.sanitized.json").read_text(encoding="utf-8"))
        rows = load_jsonl(EVIDENCE / "runs.sanitized.jsonl")
        by_target_profile = {(row["target_id"], row["profile"]): row for row in rows}

        for row in claim["rows"]:
            baseline = by_target_profile[(row["target_id"], "A-search-only")]
            treatment = by_target_profile[(row["target_id"], "D-full-router")]
            self.assertEqual(row["baseline_exact_uncached_total_tokens"], baseline["exact_uncached_total_tokens"])
            self.assertEqual(row["treatment_exact_uncached_total_tokens"], treatment["exact_uncached_total_tokens"])
            self.assertEqual(
                row["treatment_minus_baseline_exact_uncached_tokens"],
                treatment["exact_uncached_total_tokens"] - baseline["exact_uncached_total_tokens"],
            )
            self.assertEqual(
                row["uncached_tokens_avoided"],
                baseline["exact_uncached_total_tokens"] - treatment["exact_uncached_total_tokens"],
            )
            self.assertNotIn("exact_uncached_total_token_delta", row)

    def test_route_isolation_rows_match_run_rows(self) -> None:
        route_rows = load_jsonl(EVIDENCE / "route-isolation.sanitized.jsonl")
        run_rows = load_jsonl(EVIDENCE / "runs.sanitized.jsonl")
        by_target_profile = {(row["target_id"], row["profile"]): row for row in run_rows}

        self.assertEqual(len(route_rows), len(run_rows))
        for route in route_rows:
            run = by_target_profile[(route["target_id"], route["profile"])]
            self.assertEqual(route["observed_task_tools"], run["observed_task_tools"])
            self.assertEqual(route["semantic_tools_disabled"], run["semantic_tools_disabled"])
            self.assertEqual(route["mcp_servers_hard_disabled"], run["mcp_servers_hard_disabled"])

    def test_manifest_lists_existing_artifacts_with_matching_hashes(self) -> None:
        manifest = json.loads((EVIDENCE / "evidence-manifest.sanitized.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["artifact_path_mode"], "canonical_repo_relative")
        for rel, expected_hash in manifest["artifact_hashes_sha256"].items():
            path = ROOT / rel
            self.assertTrue(path.exists(), rel)
            self.assertEqual(generator.file_sha256(path), expected_hash)

    def test_generated_outputs_match_single_sanitized_source(self) -> None:
        source = self.source()

        self.assertEqual(
            generator.build_summary(source),
            json.loads((EVIDENCE / "summary.sanitized.json").read_text(encoding="utf-8")),
        )
        self.assertEqual(
            generator.build_claim_readiness(source),
            json.loads((EVIDENCE / "claim-readiness.sanitized.json").read_text(encoding="utf-8")),
        )
        self.assertEqual(
            generator.build_readme(source, generator.build_summary(source)),
            (EVIDENCE / "README.md").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            generator.build_svg(source, generator.build_summary(source)),
            ASSET.read_text(encoding="utf-8"),
        )

    def test_generator_can_rebuild_evidence_without_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "evidence"
            asset = Path(raw) / "asset.svg"
            generator.build_outputs(self.source(), out, asset)

            for name in [
                "source.sanitized.json",
                "README.md",
                "summary.sanitized.json",
                "runs.sanitized.jsonl",
                "route-isolation.sanitized.jsonl",
                "claim-readiness.sanitized.json",
                "audit.sanitized.json",
            ]:
                self.assertEqual((out / name).read_text(encoding="utf-8"), (EVIDENCE / name).read_text(encoding="utf-8"))
            self.assertEqual(asset.read_text(encoding="utf-8"), ASSET.read_text(encoding="utf-8"))

            manifest = json.loads((out / "evidence-manifest.sanitized.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["artifact_path_mode"], "custom_output_relative")
            self.assertEqual(manifest["evidence_directory"], "custom-output")
            expected_paths = {"asset/asset.svg"} | {
                f"evidence/{name}"
                for name in [
                    "source.sanitized.json",
                    "README.md",
                    "summary.sanitized.json",
                    "runs.sanitized.jsonl",
                    "route-isolation.sanitized.jsonl",
                    "claim-readiness.sanitized.json",
                    "audit.sanitized.json",
                ]
            }
            self.assertEqual(set(manifest["artifact_hashes_sha256"]), expected_paths)
            self.assertEqual(manifest["artifact_hashes_sha256"]["asset/asset.svg"], generator.file_sha256(asset))
            self.assertEqual(
                manifest["artifact_hashes_sha256"]["evidence/source.sanitized.json"],
                generator.file_sha256(out / "source.sanitized.json"),
            )

    def test_svg_chart_values_are_generated_from_summary(self) -> None:
        summary = json.loads((EVIDENCE / "summary.sanitized.json").read_text(encoding="utf-8"))
        svg = ASSET.read_text(encoding="utf-8")

        for row in summary["paired_results"]:
            self.assertIn(f"{row['uncached_token_reduction_percent']:.2f}% fewer", svg)
            self.assertIn(f"{row['baseline_exact_uncached_total_tokens']:,}", svg)
            self.assertIn(f"{row['treatment_exact_uncached_total_tokens']:,}", svg)

    def test_no_committed_png_metadata_chunks(self) -> None:
        for path in (ROOT / "docs" / "assets").glob("*.png"):
            self.assertEqual(png_metadata_chunks(path), [], str(path))


if __name__ == "__main__":
    unittest.main()
