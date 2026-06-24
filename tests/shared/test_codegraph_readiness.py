from __future__ import annotations

import unittest
from pathlib import Path

from scripts.lib.codegraph_readiness import codegraph_readiness


ROOT = Path(__file__).resolve().parents[2]


class CodeGraphReadinessTests(unittest.TestCase):
    def test_readiness_reports_compat_manifest(self) -> None:
        report = codegraph_readiness(ROOT)
        check_names = {item["name"] for item in report["checks"]}
        self.assertIn("compat_manifest", check_names)
        self.assertIn("live_provider_capture", check_names)


if __name__ == "__main__":
    unittest.main()
