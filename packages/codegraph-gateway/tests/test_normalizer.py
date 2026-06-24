from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_code_router_codegraph_gateway.budgets import ARCHITECTURE_MAX_BYTES
from agent_code_router_codegraph_gateway.contracts import Freshness
from agent_code_router_codegraph_gateway.normalizer import normalize_gateway_result


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "codegraph"


def load(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


class NormalizerTests(unittest.TestCase):
    def test_oversized_fixture_is_capped(self) -> None:
        raw_result = {
            "summary": ["S" * 1500, "T" * 1500, "U" * 1500],
            "anchors": [
                {
                    "path": f"src/very/long/path/{index}/module/file_with_a_very_long_name_{index}.py",
                    "line_start": 1,
                    "line_end": 50,
                    "symbol": "VeryLongSymbolName" * 20,
                    "role": "context",
                    "confidence": "extracted",
                }
                for index in range(5)
            ],
            "relationships": [],
            "uncertainties": ["Z" * 1200, "Y" * 1200],
        }
        result = normalize_gateway_result(
            tool_name="architecture_context",
            intent="architecture",
            scope_id="cg-1",
            freshness=Freshness(status="current", index_present=True),
            raw_result=raw_result,
            child_tool_calls=1,
            duration_ms=10,
            recommended_tool_family="serena_lsp",
            recommended_reason="verify",
        )
        self.assertLessEqual(len(json.dumps(result).encode("utf-8")), ARCHITECTURE_MAX_BYTES)
        self.assertTrue(result["budget"]["truncated"])

    def test_malformed_output_returns_partial(self) -> None:
        result = normalize_gateway_result(
            tool_name="trace_code_flow",
            intent="code_flow",
            scope_id="cg-2",
            freshness=Freshness(status="current", index_present=True),
            raw_result=load("malformed-output.txt"),
            child_tool_calls=1,
            duration_ms=10,
            recommended_tool_family="serena_lsp",
            recommended_reason="verify",
        )
        self.assertEqual(result["status"], "partial")
        self.assertIn("bounded_excerpt", result)

    def test_duplicate_anchors_are_collapsed(self) -> None:
        result = normalize_gateway_result(
            tool_name="architecture_context",
            intent="architecture",
            scope_id="cg-3",
            freshness=Freshness(status="current", index_present=True),
            raw_result=load("duplicate-anchors.txt"),
            child_tool_calls=1,
            duration_ms=10,
            recommended_tool_family="serena_lsp",
            recommended_reason="verify",
        )
        self.assertEqual(len(result["anchors"]), 1)

    def test_relationships_are_preserved_when_provider_ids_exist(self) -> None:
        result = normalize_gateway_result(
            tool_name="architecture_context",
            intent="architecture",
            scope_id="cg-5",
            freshness=Freshness(status="current", index_present=True),
            raw_result=load("explore-architecture.txt"),
            child_tool_calls=1,
            duration_ms=10,
            recommended_tool_family="serena_lsp",
            recommended_reason="verify",
        )
        self.assertEqual(len(result["relationships"]), 2)

    def test_heuristic_mobile_edge_stays_heuristic(self) -> None:
        result = normalize_gateway_result(
            tool_name="architecture_context",
            intent="mobile_bridge",
            scope_id="cg-4",
            freshness=Freshness(status="current", index_present=True),
            raw_result=load("mobile-react-native.txt"),
            child_tool_calls=1,
            duration_ms=10,
            recommended_tool_family="serena_lsp",
            recommended_reason="verify",
        )
        self.assertEqual(result["anchors"][0]["confidence"], "heuristic")
        self.assertEqual(result["relationships"][0]["confidence"], "heuristic")

    def test_absolute_paths_are_normalized_to_repo_relative(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw)
            source = repo / "src" / "checkout.py"
            source.parent.mkdir()
            source.write_text("", encoding="utf-8")
            result = normalize_gateway_result(
                tool_name="architecture_context",
                intent="architecture",
                scope_id="cg-6",
                freshness=Freshness(status="current", index_present=True),
                raw_result={
                    "summary": ["Absolute path anchor."],
                    "anchors": [
                        {
                            "id": "a1",
                            "path": str(source),
                            "line_start": 1,
                            "line_end": 2,
                            "symbol": "checkout",
                            "confidence": "extracted",
                        }
                    ],
                    "relationships": [],
                    "uncertainties": [],
                },
                child_tool_calls=1,
                duration_ms=10,
                recommended_tool_family="serena_lsp",
                recommended_reason="verify",
                repo_root=repo,
            )
            self.assertEqual(result["anchors"][0]["path"], "src/checkout.py")

    def test_paths_outside_repo_are_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            outside = Path(raw) / "outside.py"
            repo.mkdir()
            outside.write_text("", encoding="utf-8")
            result = normalize_gateway_result(
                tool_name="architecture_context",
                intent="architecture",
                scope_id="cg-7",
                freshness=Freshness(status="current", index_present=True),
                raw_result={
                    "summary": ["Outside anchor."],
                    "anchors": [
                        {
                            "id": "outside",
                            "path": str(outside),
                            "line_start": 1,
                            "line_end": 2,
                            "symbol": "outside",
                            "confidence": "extracted",
                        }
                    ],
                    "relationships": [
                        {"from": "outside", "to": "outside", "relation": "calls", "confidence": "extracted", "provenance": "source"}
                    ],
                    "uncertainties": [],
                },
                child_tool_calls=1,
                duration_ms=10,
                recommended_tool_family="serena_lsp",
                recommended_reason="verify",
                repo_root=repo,
            )
            self.assertEqual(result["anchors"], [])
            self.assertEqual(result["relationships"], [])


if __name__ == "__main__":
    unittest.main()
