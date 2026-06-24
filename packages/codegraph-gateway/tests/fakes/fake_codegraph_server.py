from __future__ import annotations

import argparse
import json
from pathlib import Path

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "codegraph"
ALL_TOOLS = [
    "codegraph_status",
    "codegraph_explore",
    "codegraph_search",
    "codegraph_node",
    "codegraph_callers",
    "codegraph_callees",
    "codegraph_impact",
]


def tool_schema(tool_name: str) -> dict[str, object]:
    properties: dict[str, object] = {}
    if tool_name == "codegraph_search":
        properties["query"] = {"type": "string"}
    elif tool_name == "codegraph_node":
        properties["path"] = {"type": "string"}
        properties["symbol"] = {"type": "string"}
    elif tool_name == "codegraph_impact":
        properties["target"] = {"type": "string"}
    return {"type": "object", "properties": properties}


def load_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def scenario_fixture(tool_name: str, scenario: str) -> str:
    if tool_name == "codegraph_status":
        mapping = {
            "missing_index": "status-missing-index.txt",
            "stale_index": "status-missing-index.txt",
            "pending_file": "status-pending.txt",
            "pending_unrelated_file": "status-pending-unrelated.txt",
        }
        return load_text(mapping.get(scenario, "status-current.txt"))
    if tool_name == "codegraph_explore":
        mapping = {
            "large_output": "explore-large.txt",
            "malformed_text": "malformed-output.txt",
            "duplicate_anchors": "duplicate-anchors.txt",
            "heuristic_mobile": "mobile-react-native.txt",
            "malicious_label": "malicious-instruction-like.txt",
        }
        return load_text(mapping.get(scenario, "explore-architecture.txt"))
    if tool_name == "codegraph_search":
        return json.dumps({"summary": ["Resolved start symbol."], "anchors": [], "relationships": [], "uncertainties": []})
    if tool_name == "codegraph_node":
        return json.dumps(
            {
                "summary": ["Expanded node context."],
                "anchors": [],
                "relationships": [],
                "uncertainties": [],
                "bounded_excerpt": "Expanded node source excerpt.",
            }
        )
    if tool_name == "codegraph_callers":
        return load_text("trace-forward.txt")
    if tool_name == "codegraph_callees":
        return load_text("trace-forward.txt")
    if tool_name == "codegraph_impact":
        return load_text("impact-symbol.txt")
    return "{}"


def build_server(*, scenario: str) -> Server:
    tools = list(ALL_TOOLS)
    if scenario == "missing_tool":
        tools.remove("codegraph_impact")
    server = Server("fake-codegraph")

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        listed: list[types.Tool] = []
        for tool_name in tools:
            schema = tool_schema(tool_name)
            if scenario == "schema_drift" and tool_name == "codegraph_search":
                schema = {"type": "array"}
            listed.append(types.Tool(name=tool_name, description=tool_name, inputSchema=schema))
        return listed

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, object]) -> dict[str, object]:
        if scenario == "child_crash":
            raise RuntimeError("simulated crash")
        if scenario == "slow_response":
            await anyio.sleep(2)
        payload = scenario_fixture(name, scenario)
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return {"text": payload}

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="normal")
    args = parser.parse_args(argv)
    server = build_server(scenario=args.scenario)

    async def runner() -> None:
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    anyio.run(runner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
