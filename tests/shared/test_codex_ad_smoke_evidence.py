from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "benchmarks" / "real-agent-routing" / "evidence" / "codex-ad-smoke-anonymized"


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CodexAdSmokeEvidenceTests(unittest.TestCase):
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
                pair["exact_uncached_token_delta"],
                baseline["exact_uncached_total_tokens"] - treatment["exact_uncached_total_tokens"],
            )

    def test_tradeoff_fields_show_total_token_and_latency_cost(self) -> None:
        summary = json.loads((EVIDENCE / "summary.sanitized.json").read_text(encoding="utf-8"))
        combined = summary["trade_off"]["combined"]

        self.assertGreater(combined["treatment_exact_total_tokens"], combined["baseline_exact_total_tokens"])
        self.assertGreater(combined["wall_time_ratio_treatment_over_baseline"], 2.0)
        self.assertGreater(combined["tool_output_byte_reduction_percent"], 0)

    def test_public_readme_uses_uncached_metric_wording_without_pooled_headline(self) -> None:
        root_readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Uncached tokens avoided", root_readme)
        self.assertIn("Uncached-token reduction", root_readme)
        self.assertIn("context-efficiency result", root_readme)
        self.assertIn("benchmarks/real-agent-routing/evidence/codex-ad-smoke-anonymized", root_readme)
        self.assertNotIn("| Descriptive total |", root_readme)

    def test_evidence_manifest_publishes_hashes_and_not_captured_versions(self) -> None:
        manifest = json.loads((EVIDENCE / "evidence-manifest.sanitized.json").read_text(encoding="utf-8"))

        self.assertTrue(manifest["privacy_policy"]["one_way_hashes_used_for_private_task_and_repo_fingerprints"])
        for target in manifest["targets"].values():
            self.assertRegex(target["task_prompt_hash"], r"^[a-f0-9]{24}$")
            self.assertRegex(target["target_symbol_hash"], r"^[a-f0-9]{24}$")
            self.assertRegex(target["repository_snapshot_fingerprint"], r"^[a-f0-9]{24}$")
            self.assertEqual(target["run_order_profiles"], ["A-search-only", "D-full-router"])
        self.assertEqual(manifest["version_capture"]["model_identifier"], "not_captured_in_smoke")


if __name__ == "__main__":
    unittest.main()
