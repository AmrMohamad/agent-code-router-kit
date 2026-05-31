from __future__ import annotations

import argparse
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "live_observation_recorder.py"
spec = importlib.util.spec_from_file_location("android_live_observation_recorder", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidLiveObservationRecorderTests(unittest.TestCase):
    def test_add_behavior_observation_requires_evidence_and_valid_tool(self) -> None:
        args = argparse.Namespace(
            log="unused.json",
            case_id="known-symbol",
            observed_first_tool="serena_kotlin_lsp",
            notes="Started with Serena find_symbol.",
            evidence="transcript:turn-1",
        )

        data = probe.add_behavior(args)
        result = probe.validate_behavior(data, 1)

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["valid_observations"], 1)

    def test_behavior_validation_rejects_missing_evidence(self) -> None:
        data = {
            "observations": [
                {"case_id": "known-symbol", "observed_first_tool": "serena_kotlin_lsp", "evidence": ""}
            ]
        }

        result = probe.validate_behavior(data, 1)

        self.assertGreater(len(result["errors"]), 0)
        self.assertEqual(result["valid_observations"], 0)

    def test_add_transport_observation_normalizes_boolean_and_process_growth(self) -> None:
        args = argparse.Namespace(
            log="unused.json",
            task_id="transport-task-01",
            transport="streamable-http",
            status="pass",
            transport_error="false",
            process_growth="0",
            notes="No transport failure.",
            evidence="results/android/example-summary.json",
        )

        data = probe.add_transport(args)
        result = probe.validate_transport(data, 1)

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["valid_observations"], 1)
        self.assertEqual(data["observations"][0]["transport_error"], "false")

    def test_transport_validation_rejects_blank_template_rows(self) -> None:
        data = {
            "observations": [
                {
                    "task_id": "transport-task-01",
                    "transport": "streamable-http",
                    "status": "",
                    "transport_error": "",
                    "process_growth": "",
                    "evidence": "",
                }
            ]
        }

        result = probe.validate_transport(data, 1)

        self.assertGreaterEqual(len(result["errors"]), 3)
        self.assertEqual(result["valid_observations"], 0)


if __name__ == "__main__":
    unittest.main()
