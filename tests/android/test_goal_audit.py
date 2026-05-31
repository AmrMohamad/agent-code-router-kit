from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts" / "benchmarks" / "android" / "goal_audit.py"
spec = importlib.util.spec_from_file_location("android_goal_audit", AUDIT_PATH)
assert spec and spec.loader
audit_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_mod)


class AndroidGoalAuditTests(unittest.TestCase):
    def write_json(self, path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def args(self, root: Path) -> argparse.Namespace:
        return argparse.Namespace(
            results_root=str(root),
            output_json="",
            output_md="",
            minimum_default_cases=8,
            minimum_repeats=3,
            minimum_source_symbol_cases=2,
            minimum_lsp_cases=4,
            minimum_lsp_repeats=3,
            minimum_lsp_boundary_cases=2,
        )

    def seed_artifacts(self, root: Path) -> None:
        default_rows = []
        categories = sorted(audit_mod.REQUIRED_DEFAULT_CATEGORIES)
        for index, category in enumerate(categories):
            default_rows.append(
                {
                    "case_id": f"default_{category}",
                    "category": category,
                    "last_byte_count": 100 + index,
                    "median_wall_seconds": 0.01,
                    "passes": 3,
                    "repo": "sample_b2b_android" if index % 2 else "sample_retail_android",
                }
            )
        self.write_json(root / "default-search" / "summary-1.json", default_rows)
        self.write_json(root / "default-search" / "policy-assertions-1.json", {"summary": {"pass": 10, "warn": 0, "fail": 0}})

        studio_rows = [
            {"case_id": "studio_check_sample_b2b", "command_type": "check", "repo": "sample_b2b_android", "statuses": ["pass"]},
            {"case_id": "studio_check_sample_retail", "command_type": "check", "repo": "sample_retail_android", "statuses": ["pass"]},
            {"case_id": "studio_analyze_sample_b2b", "command_type": "analyze-file", "repo": "sample_b2b_android", "statuses": ["pass"]},
            {"case_id": "studio_analyze_sample_retail", "command_type": "analyze-file", "repo": "sample_retail_android", "statuses": ["pass"]},
            {"case_id": "studio_decl", "command_type": "find-declaration", "repo": "sample_retail_android", "statuses": ["no-result"]},
        ]
        self.write_json(root / "android-studio-semantic" / "android-studio-semantic-summary-1.json", studio_rows)
        self.write_json(root / "android-studio-semantic" / "android-studio-semantic-assertions-1.json", {"summary": {"pass": 4, "warn": 1, "fail": 0}})

        source_rows = [
            {"case_id": "source_sample_b2b", "repo": "sample_b2b_android", "statuses": ["pass"]},
            {"case_id": "source_sample_retail", "repo": "sample_retail_android", "statuses": ["pass"]},
        ]
        self.write_json(root / "serena-source-symbol" / "serena-source-symbol-summary-1.json", source_rows)
        self.write_json(root / "serena-source-symbol" / "serena-source-symbol-assertions-1.json", {"summary": {"pass": 2, "warn": 0, "fail": 0}})

        project_rows = [
            {"case_id": "lsp_find", "repo": "sample_b2b_android", "tool_name": "find_symbol", "statuses": ["pass"], "measured_pass_count": 3},
            {"case_id": "lsp_refs", "repo": "sample_retail_android", "tool_name": "find_referencing_symbols", "statuses": ["pass"], "measured_pass_count": 3},
            {"case_id": "lsp_overview", "repo": "sample_b2b_android", "tool_name": "get_symbols_overview", "statuses": ["pass"], "measured_pass_count": 3},
            {"case_id": "lsp_diagnostics", "repo": "sample_retail_android", "tool_name": "get_diagnostics_for_file", "statuses": ["pass"], "measured_pass_count": 3},
            {"case_id": "lsp_impl_boundary_sample_retail", "repo": "sample_retail_android", "tool_name": "find_implementations", "statuses": ["error"], "measured_pass_count": 3},
            {"case_id": "lsp_impl_boundary_sample_b2b", "repo": "sample_b2b_android", "tool_name": "find_implementations", "statuses": ["error"], "measured_pass_count": 3},
        ]
        self.write_json(root / "serena-project-server" / "serena-project-server-summary-1.json", project_rows)
        self.write_json(root / "serena-project-server" / "serena-project-server-assertions-1.json", {"summary": {"pass": 10, "warn": 0, "fail": 0}})

        self.write_json(root / "process-state" / "android-process-state-summary-1.json", {"status": "clean", "counts": {}})
        self.write_json(root / "process-state" / "android-process-state-assertions-1.json", {"summary": {"pass": 4, "warn": 0, "fail": 0}})

        project_model_rows = [
            {"case_id": "project_model_sample_b2b", "repo": "sample_b2b_android", "missing_local_properties": ["sample_analytics_id"], "ran_gradle": False},
            {"case_id": "project_model_sample_retail", "repo": "sample_retail_android", "missing_local_properties": [], "ran_gradle": False},
        ]
        self.write_json(root / "project-model" / "android-project-model-summary-1.json", project_model_rows)
        self.write_json(root / "project-model" / "android-project-model-assertions-1.json", {"summary": {"pass": 1, "warn": 1, "fail": 0}})

    def test_audit_reports_runtime_boundary_and_partial_studio(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root)

            data = audit_mod.audit(self.args(root))

            self.assertEqual(data["overall_status"], "complete_with_known_boundaries")
            statuses = {item["requirement"]: item["status"] for item in data["items"]}
            self.assertEqual(statuses["Android Studio Preview/Quail semantic bridge is separated from symbol-proof readiness"], "partial")
            self.assertEqual(
                statuses["Gradle/project-model runtime boundary is explicit and no build/runtime parity is claimed"],
                "boundary",
            )

    def test_audit_requires_project_server_tool_spread(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root)
            project_rows = [
                {"case_id": f"lsp_find_{index}", "repo": "sample_retail_android", "tool_name": "find_symbol", "statuses": ["pass"], "measured_pass_count": 3}
                for index in range(4)
            ]
            self.write_json(root / "serena-project-server" / "serena-project-server-summary-2.json", project_rows)

            data = audit_mod.audit(self.args(root))

            lsp_item = next(item for item in data["items"] if item["requirement"].startswith("LSP semantic system"))
            self.assertEqual(lsp_item["status"], "fail")
            self.assertIn("find_referencing_symbols", lsp_item["details"]["missing_tools"])

    def test_render_markdown_includes_remaining_boundaries(self) -> None:
        data = {
            "created_at": "2026-05-24T00:00:00Z",
            "overall_status": "complete_with_known_boundaries",
            "items": [
                {"status": "pass", "requirement": "A", "evidence": "ok", "details": {}},
                {"status": "boundary", "requirement": "B", "evidence": "keys", "details": {"missing": ["x"]}},
            ],
        }
        text = audit_mod.render_markdown(data)
        self.assertIn("Overall status", text)
        self.assertIn("Remaining Boundaries", text)
        self.assertIn("missing", text)


if __name__ == "__main__":
    unittest.main()
