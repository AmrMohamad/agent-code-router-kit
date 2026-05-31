from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "serena_transport_benchmark.py"
spec = importlib.util.spec_from_file_location("android_serena_transport_benchmark", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidSerenaTransportBenchmarkTests(unittest.TestCase):
    def test_manifest_validates_without_repos(self) -> None:
        rows = probe.serena_probe.load_cases(ROOT / "benchmarks" / "android" / "serena-transport.sample-b2b.tsv")
        self.assertEqual(probe.serena_probe.validate(rows, {}, require_repos=False), [])

    def test_process_delta_compares_counts(self) -> None:
        before = {"counts": {"serena_mcp": 1, "kotlin_lsp": 0}}
        after = {"counts": {"serena_mcp": 1, "kotlin_lsp": 1}}
        self.assertEqual(probe.process_delta(before, after), {"kotlin_lsp": 1, "serena_mcp": 0})

    def test_transport_error_seen_detects_closed_transport(self) -> None:
        self.assertTrue(probe.transport_error_seen([{"stdout": "", "stderr": "Transport closed"}]))
        self.assertFalse(probe.transport_error_seen([{"stdout": "ok", "stderr": ""}]))

    def test_build_transport_assertions_fails_process_growth(self) -> None:
        rows = [
            {
                "repo": "sample_b2b",
                "case_id": "case",
                "pass_index": 1,
                "expected_status": "pass",
                "status": "pass",
                "estimated_tokens": 1,
                "stdout": "ok",
                "stderr": "",
            }
        ]
        before = {"counts": {"serena_mcp": 0, "kotlin_lsp": 0}}
        after = {"counts": {"serena_mcp": 2, "kotlin_lsp": 0}}
        payload = probe.build_transport_assertions(rows, before, after, expected_repeats=1, max_serena_growth=0)
        self.assertGreater(payload["summary"]["fail"], 0)


if __name__ == "__main__":
    unittest.main()
