from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "transport_observations_from_lifecycle.py"
spec = importlib.util.spec_from_file_location("android_transport_observations_from_lifecycle", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidTransportObservationsFromLifecycleTests(unittest.TestCase):
    def write_summary(self, root: Path, name: str, *, status: str = "pass", process_delta: int = 0) -> None:
        path = root / name
        path.write_text(
            json.dumps(
                {
                    "process_delta": {"serena_mcp": process_delta},
                    "cases": [
                        {
                            "case_id": "http_symbol",
                            "transport": "streamable-http",
                            "status": status,
                            "checks": {"transport_error_absent": True},
                        },
                        {
                            "case_id": "stdio_symbol",
                            "transport": "stdio",
                            "status": "pass",
                            "checks": {"transport_error_absent": True},
                        },
                    ],
                }
            )
        )

    def test_build_log_extracts_only_selected_transport(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_summary(root, "android-serena-mcp-lifecycle-summary-1.json")

            data = probe.build_log(root, "streamable-http", 1)

            self.assertEqual(len(data["observations"]), 1)
            self.assertEqual(data["observations"][0]["transport"], "streamable-http")
            self.assertEqual(data["observations"][0]["process_growth"], "0")
            self.assertIn("#http_symbol", data["observations"][0]["evidence"])

    def test_validation_requires_enough_clean_pass_observations(self) -> None:
        data = {
            "observations": [
                {
                    "status": "pass",
                    "transport_error": "false",
                    "process_growth": "0",
                    "evidence": "summary.json#case",
                }
            ]
        }

        self.assertFalse(probe.validate_log(data, 2)["ok"])
        self.assertTrue(probe.validate_log(data, 1)["ok"])

    def test_validation_rejects_process_growth(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.write_summary(root, "android-serena-mcp-lifecycle-summary-1.json", process_delta=1)

            data = probe.build_log(root, "streamable-http", 1)
            result = probe.validate_log(data, 1)

            self.assertFalse(result["ok"])
            self.assertGreater(len(result["errors"]), 0)


if __name__ == "__main__":
    unittest.main()
