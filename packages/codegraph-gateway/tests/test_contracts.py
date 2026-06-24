from __future__ import annotations

import json
import unittest
from importlib.resources import files
from pathlib import Path

from agent_code_router_codegraph_gateway.config import default_compat_manifest_path
from agent_code_router_codegraph_gateway.contracts import OUTPUT_SCHEMA, validate_minimal_schema


class ContractsTests(unittest.TestCase):
    def test_output_schema_requires_expected_keys(self) -> None:
        payload = {
            "schema_version": 1,
            "status": "ok",
            "provider": "codegraph",
            "intent": "architecture",
            "scope_id": "cg-test",
            "proof_level": "discovery",
            "freshness": {},
            "summary": [],
            "anchors": [],
            "relationships": [],
            "uncertainties": [],
            "recommended_next_step": {},
            "budget": {},
            "telemetry": {},
        }
        self.assertEqual(validate_minimal_schema(payload, OUTPUT_SCHEMA), [])

    def test_compat_manifest_is_available_as_package_data(self) -> None:
        source_manifest = Path(__file__).resolve().parents[1] / "compat" / "codegraph-tools-v1.json"
        packaged_manifest = files("agent_code_router_codegraph_gateway").joinpath("compat", "codegraph-tools-v1.json")
        self.assertTrue(packaged_manifest.is_file())
        self.assertEqual(
            json.loads(source_manifest.read_text(encoding="utf-8")),
            json.loads(packaged_manifest.read_text(encoding="utf-8")),
        )
        self.assertTrue(default_compat_manifest_path().exists())


if __name__ == "__main__":
    unittest.main()
