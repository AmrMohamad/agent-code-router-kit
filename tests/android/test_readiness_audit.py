from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "readiness_audit.py"
spec = importlib.util.spec_from_file_location("android_to_readiness_readiness_audit", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidToreadinessReadinessAuditTests(unittest.TestCase):
    def write_json(self, path: Path, data: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def seed_artifacts(self, root: Path, *, other_project_serena: int = 0, observed_cases: int = 40) -> None:
        self.write_json(
            root / "operational" / "android-operational-summary-1.json",
            {
                "overall_status": "pass",
                "summary": {"pass": 12, "warn": 2, "fail": 0},
                "manifest_policy": {"summary": {"pass": 14, "fail": 0}},
                "boundary": "Launch smoke only.",
            },
        )
        self.write_json(
            root / "process-state-stable-project-aware-allowed-other" / "android-process-state-summary-1.json",
            {
                "status": "clean",
                "counts": {"serena_mcp": other_project_serena, "kotlin_lsp": 0, "json_lsp": 0, "java_jdtls": 0},
                "classification_counts": {"other_project_cwd": other_project_serena} if other_project_serena else {},
                "target_serena_mcp_count": 0,
                "other_project_serena_mcp_count": other_project_serena,
                "unknown_serena_mcp_count": 0,
            },
        )
        self.write_json(
            root / "serena-mcp-reference-triage-stdio-expanded" / "android-serena-mcp-reference-triage-summary-1.json",
            {
                "case_count": 8,
                "assertions": {"pass": 37, "warn": 8, "fail": 0},
                "classification_counts": {"serena-reference-empty-boundary": 5, "query-shape issue": 2},
                "process_delta": {"serena_mcp": 0, "kotlin_lsp": 0, "json_lsp": 0, "java_jdtls": 0},
                "transports": ["stdio"],
            },
        )
        self.write_json(
            root / "studio-symbol-matrix" / "android-studio-symbol-matrix-summary-1.json",
            {
                "case_count": 16,
                "trusted_studio_layer": True,
                "declaration_pass_count": 15,
                "usage_pass_count": 16,
                "classification_counts": {"pass": 30, "boundary": 1},
            },
        )
        self.write_json(
            root / "generated-semantic-mapping" / "android-generated-semantic-mapping-summary-1.json",
            {
                "case_count": 5,
                "mapping_pass_count": 5,
                "semantic_pass_count": 2,
                "classification_counts": {"pass": 5},
                "semantic_classification_counts": {"pass": 2, "boundary": 3},
            },
        )
        self.write_json(
            root / "high-fanout-summary-sample_b2b-stable-expanded" / "android-high-fanout-summary-1.json",
            {
                "mode": "summary_only",
                "assertions": {"pass": 10, "warn": 8, "fail": 0},
                "patterns": [
                    {"pattern": "UseCase", "file_count": 262, "total_matches": 1813, "budget": {"status": "warn"}},
                    {"pattern": "ViewModel", "file_count": 101, "total_matches": 330, "budget": {"status": "pass"}},
                    {"pattern": "Repository", "file_count": 175, "total_matches": 676, "budget": {"status": "warn"}},
                    {"pattern": "Mapper", "file_count": 16, "total_matches": 30, "budget": {"status": "pass"}},
                    {"pattern": "Service", "file_count": 156, "total_matches": 1447, "budget": {"status": "warn"}},
                    {"pattern": "Module", "file_count": 40, "total_matches": 93, "budget": {"status": "pass"}},
                ],
            },
        )
        self.write_json(
            root / "serena-mcp-lifecycle" / "android-serena-mcp-lifecycle-summary-1.json",
            {
                "case_count": 8,
                "transports": ["stdio", "streamable-http"],
                "process_delta": {"serena_mcp": 0, "kotlin_lsp": 0, "json_lsp": 0, "java_jdtls": 0},
                "assertions": {"pass": 10, "warn": 0, "fail": 0},
                "transport_performance": {
                    "candidate_transport": "streamable-http",
                    "recommendation_status": "lifecycle_candidate_only",
                    "transports": {
                        "stdio": {"case_count": 4, "pass_count": 4, "fail_count": 0, "avg_wall_seconds": 12.5},
                        "streamable-http": {"case_count": 4, "pass_count": 4, "fail_count": 0, "avg_wall_seconds": 12.3},
                    },
                },
                "cases": [
                    {"case_id": "stdio_a", "transport": "stdio", "status": "pass"},
                    {"case_id": "stdio_b", "transport": "stdio", "status": "pass"},
                    {"case_id": "stdio_c", "transport": "stdio", "status": "pass"},
                    {"case_id": "stdio_d", "transport": "stdio", "status": "pass"},
                    {"case_id": "http_a", "transport": "streamable-http", "status": "pass"},
                    {"case_id": "http_b", "transport": "streamable-http", "status": "pass"},
                    {"case_id": "http_c", "transport": "streamable-http", "status": "pass"},
                    {"case_id": "http_d", "transport": "streamable-http", "status": "pass"},
                ],
            },
        )
        self.write_json(
            root / "transport-recommendation" / "android-transport-recommendation-summary-1.json",
            {
                "candidate_transport": "streamable-http",
                "recommendation_status": "lifecycle_candidate_only",
                "minimum_real_task_observations": 10,
                "real_task_summary": {"case_count": 0, "failure_count": 0},
                "assertions": {"pass": 2, "warn": 1, "fail": 0},
            },
        )
        self.write_json(
            root / "kotlin-lsp-memory-matrix" / "android-kotlin-lsp-memory-matrix-summary-1.json",
            {
                "recommended_jvm_options": "-Xmx2G",
                "values": [
                    {"jvm_options": "-Xmx2G", "assertions": {"pass": 29, "warn": 0, "fail": 0}},
                    {"jvm_options": "-Xmx4G", "assertions": {"pass": 29, "warn": 0, "fail": 0}},
                    {"jvm_options": "-Xmx6G", "assertions": {"pass": 29, "warn": 0, "fail": 0}},
                ],
            },
        )
        self.write_json(
            root / "agent-behavior" / "android-agent-behavior-summary-1.json",
            {
                "case_count": 40,
                "observed_case_count": observed_cases,
                "assertions": {"pass": 200, "warn": 0, "fail": 0},
                "first_tool_counts": {"serena_kotlin_lsp": 6, "rg_fd": 10},
            },
        )
        self.write_json(
            root / "sample_retail-followup" / "android-sample_retail-followup-summary-1.json",
            {
                "status": "followup-operational-equivalent",
                "assertions": {"pass": 8, "warn": 2, "fail": 0},
                "serena_stats": {"find_symbol_pass": 5, "references_empty": 2},
                "process_counts": {"serena_mcp": 7},
                "studio_matrix": {"trusted_studio_layer": True},
                "runtime_smoke": {"build_install_launch_passed": True},
            },
        )

    def test_audit_keeps_stable_achieved_but_readiness_pending_for_acceptance_or_live_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root)

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            self.assertEqual(data["stable_status"], "achieved_with_named_boundaries")
            self.assertEqual(data["readiness_status"], "pending_acceptance_or_live_evidence")
            second_repo = next(item for item in data["gates"] if item["gate_id"] == "second_repo_operational_scope")
            self.assertEqual(second_repo["readiness"], "satisfied")
            references = next(item for item in data["gates"] if item["gate_id"] == "serena_reference_disagreement")
            self.assertEqual(references["readiness"], "satisfied_by_studio_replacement_for_affected_patterns")
            studio = next(item for item in data["gates"] if item["gate_id"] == "android_studio_symbol_matrix")
            self.assertEqual(studio["readiness"], "satisfied_for_sample_b2b_and_sample_retail")
            generated = next(item for item in data["gates"] if item["gate_id"] == "generated_semantic_mapping")
            self.assertEqual(generated["readiness"], "satisfied")
            lifecycle = next(item for item in data["gates"] if item["gate_id"] == "serena_mcp_lifecycle")
            self.assertEqual(lifecycle["details"]["transport_performance"]["candidate_transport"], "streamable-http")
            self.assertEqual(lifecycle["details"]["transport_recommendation"]["recommendation_status"], "lifecycle_candidate_only")

    def test_daily_transport_recommendation_can_satisfy_lifecycle_gate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root)
            self.write_json(
                root / "transport-recommendation" / "android-transport-recommendation-summary-2.json",
                {
                    "candidate_transport": "streamable-http",
                    "recommendation_status": "daily_recommendation",
                    "minimum_real_task_observations": 10,
                    "real_task_summary": {"case_count": 10, "failure_count": 0},
                    "assertions": {"pass": 3, "warn": 0, "fail": 0},
                },
            )

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            lifecycle = next(item for item in data["gates"] if item["gate_id"] == "serena_mcp_lifecycle")
            self.assertEqual(lifecycle["status"], "pass")
            self.assertEqual(lifecycle["readiness"], "satisfied")

    def test_readiness_uses_latest_qualified_lifecycle_not_latest_partial_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root)
            self.write_json(
                root / "serena-mcp-lifecycle" / "android-serena-mcp-lifecycle-summary-2.json",
                {
                    "case_count": 4,
                    "transports": ["streamable-http"],
                    "process_delta": {"serena_mcp": 0, "kotlin_lsp": 0, "json_lsp": 0, "java_jdtls": 0},
                    "assertions": {"pass": 7, "warn": 0, "fail": 0},
                    "transport_performance": {
                        "candidate_transport": "streamable-http",
                        "recommendation_status": "lifecycle_candidate_only",
                    },
                },
            )

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            lifecycle = next(item for item in data["gates"] if item["gate_id"] == "serena_mcp_lifecycle")
            self.assertEqual(lifecycle["details"]["case_count"], 8)
            self.assertEqual(lifecycle["status"], "warn")

    def test_behavior_gate_requires_minimum_live_observations_for_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root, observed_cases=5)
            self.write_json(
                root / "agent-behavior" / "android-agent-behavior-summary-2.json",
                {
                    "case_count": 40,
                    "observed_case_count": 5,
                    "minimum_observed_cases_for_readiness": 10,
                    "assertions": {"pass": 200, "warn": 0, "fail": 0},
                    "first_tool_counts": {"serena_kotlin_lsp": 6, "rg_fd": 10},
                },
            )

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            behavior = next(item for item in data["gates"] if item["gate_id"] == "agent_behavior_policy_gate")
            self.assertEqual(behavior["status"], "warn")
            self.assertEqual(behavior["readiness"], "pending_live_agent_evidence")

    def test_process_gate_distinguishes_project_aware_from_clean_room(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root, other_project_serena=4)

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            process = next(item for item in data["gates"] if item["gate_id"] == "clean_process_state")
            self.assertEqual(process["status"], "warn")
            self.assertEqual(process["stable_gate"], "achieved")
            self.assertEqual(process["readiness"], "pending_clean_room_or_project_aware_acceptance")

    def test_process_gate_accepts_explicit_project_aware_scope(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root, other_project_serena=4)
            self.write_json(
                root / "process-scope-acceptance" / "android-process-scope-acceptance-summary-1.json",
                {
                    "status": "accepted",
                    "accepted_project_aware_strictness": True,
                    "accepted_by": "amr",
                    "reason": "Other Serena sessions are intentionally active for unrelated projects.",
                    "assertions": {"pass": 3, "warn": 0, "fail": 0},
                },
            )

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            process = next(item for item in data["gates"] if item["gate_id"] == "clean_process_state")
            self.assertEqual(process["status"], "pass")
            self.assertEqual(process["stable_gate"], "achieved")
            self.assertEqual(process["readiness"], "satisfied_by_project_aware_acceptance")

    def test_second_repo_gate_can_be_satisfied_by_equivalent_sample_retail_summary(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root, observed_cases=40)
            self.write_json(
                root / "sample_retail-followup" / "android-sample_retail-followup-summary-2.json",
                {
                    "status": "followup-operational-equivalent",
                    "assertions": {"pass": 10, "warn": 0, "fail": 0},
                    "serena_stats": {"find_symbol_pass": 5},
                    "process_counts": {"serena_mcp": 1},
                    "studio_matrix": {"trusted_studio_layer": True},
                    "runtime_smoke": {"build_install_launch_passed": True},
                },
            )

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            second_repo = next(item for item in data["gates"] if item["gate_id"] == "second_repo_operational_scope")
            self.assertEqual(second_repo["status"], "pass")
            self.assertEqual(second_repo["readiness"], "satisfied")

    def test_missing_artifact_blocks_stable_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.seed_artifacts(root)
            for path in (root / "studio-symbol-matrix").glob("*.json"):
                path.unlink()

            data = probe.audit(type("Args", (), {"results_root": str(root)})())

            self.assertEqual(data["stable_status"], "blocked")
            studio = next(item for item in data["gates"] if item["gate_id"] == "android_studio_symbol_matrix")
            self.assertEqual(studio["status"], "missing")

    def test_render_markdown_lists_pending_gates(self) -> None:
        data = {
            "date_utc": "2026-05-30T00:00:00Z",
            "stable_status": "achieved_with_named_boundaries",
            "readiness_status": "not_ready",
            "gates": [
                {
                    "status": "warn",
                    "stable_gate": "achieved",
                    "readiness": "pending_clean_room",
                    "gate_id": "clean_process_state",
                    "next_action": "run strict",
                }
            ],
        }
        text = probe.render_markdown(data)
        self.assertIn("readiness status", text)
        self.assertIn("pending_clean_room", text)


if __name__ == "__main__":
    unittest.main()
