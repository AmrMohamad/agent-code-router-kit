from __future__ import annotations

import unittest

from scripts.lib.codegraph_treatment_config import codegraph_treatment_for_arm, validate_codegraph_arm_set


class CodeGraphTreatmentConfigTests(unittest.TestCase):
    def test_validate_core_arm_set(self) -> None:
        validate_codegraph_arm_set(
            ["CG-A-control", "CG-B-policy-only", "CG-C-capability-only", "CG-D-bounded-router"]
        )

    def test_optional_raw_arm_is_rejected_without_flag(self) -> None:
        with self.assertRaises(ValueError):
            validate_codegraph_arm_set(
                [
                    "CG-A-control",
                    "CG-B-policy-only",
                    "CG-C-capability-only",
                    "CG-D-bounded-router",
                    "CG-X-raw-codegraph",
                ]
            )

    def test_lookup_returns_expected_budget(self) -> None:
        treatment = codegraph_treatment_for_arm("CG-D-bounded-router")
        self.assertTrue(treatment.gateway_access_enabled)
        self.assertEqual(treatment.max_graph_output_bytes, 6000)


if __name__ == "__main__":
    unittest.main()
