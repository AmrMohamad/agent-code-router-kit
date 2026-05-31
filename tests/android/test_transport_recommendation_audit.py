from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "transport_recommendation_audit.py"
spec = importlib.util.spec_from_file_location("android_transport_recommendation_audit", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidTransportRecommendationAuditTests(unittest.TestCase):
    def write_lifecycle(self, root: Path, name: str, *, candidate: str = "streamable-http") -> None:
        path = root / "serena-mcp-lifecycle" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "case_count": 8,
                    "transports": ["stdio", "streamable-http"],
                    "process_delta": {"serena_mcp": 0, "kotlin_lsp": 0, "json_lsp": 0, "java_jdtls": 0},
                    "assertions": {"pass": 10, "warn": 0, "fail": 0},
                    "transport_performance": {
                        "candidate_transport": candidate,
                        "recommendation_status": "lifecycle_candidate_only",
                    },
                }
            )
        )

    def test_lifecycle_candidate_without_real_tasks_is_warning_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_lifecycle(root, "android-serena-mcp-lifecycle-summary-1.json")

            data = probe.build_audit(root, None, 10)

            self.assertEqual(data["candidate_transport"], "streamable-http")
            self.assertEqual(data["recommendation_status"], "lifecycle_candidate_only")
            self.assertEqual(data["assertions"]["warn"], 1)

    def test_real_task_threshold_promotes_daily_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_lifecycle(root, "android-serena-mcp-lifecycle-summary-1.json")
            log = root / "observed.json"
            log.write_text(
                json.dumps(
                    {
                        "observations": [
                            {
                                "task_id": f"task-{index}",
                                "transport": "streamable-http",
                                "status": "pass",
                                "process_growth": "0",
                                "evidence": f"summary-{index}.json",
                            }
                            for index in range(10)
                        ]
                    }
                )
            )

            data = probe.build_audit(root, log, 10)

            self.assertEqual(data["recommendation_status"], "daily_recommendation")
            self.assertEqual(data["assertions"]["warn"], 0)

    def test_real_tasks_need_evidence_before_daily_recommendation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_lifecycle(root, "android-serena-mcp-lifecycle-summary-1.json")
            log = root / "observed.json"
            log.write_text(
                json.dumps(
                    {
                        "observations": [
                            {"task_id": f"task-{index}", "transport": "streamable-http", "status": "pass", "process_growth": "0"}
                            for index in range(10)
                        ]
                    }
                )
            )

            data = probe.build_audit(root, log, 10)

            self.assertEqual(data["recommendation_status"], "lifecycle_candidate_only")
            self.assertEqual(data["real_task_summary"]["failure_count"], 10)

    def test_missing_lifecycle_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            data = probe.build_audit(Path(raw), None, 10)

            self.assertEqual(data["recommendation_status"], "insufficient_lifecycle_evidence")
            self.assertGreater(data["assertions"]["fail"], 0)


if __name__ == "__main__":
    unittest.main()
