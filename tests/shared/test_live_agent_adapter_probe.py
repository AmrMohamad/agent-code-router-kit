from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.benchmarks.probe_live_agent_adapters import adapter_probe_prompt, probe_agent
from scripts.lib.agent_session import AgentProfile, LaunchPlan, RouteProfile
from scripts.lib.route_isolation import RouteIsolation
from scripts.lib.transcript_parser import parse_benchmark_response


class LiveAgentAdapterProbeTests(unittest.TestCase):
    def test_probe_prompt_contains_contract_and_unique_sentinel(self) -> None:
        prompt = adapter_probe_prompt(agent_id="codex", sentinel="BENCHMARK_DONE_probe")
        parsed = parse_benchmark_response(prompt, sentinel="BENCHMARK_DONE_probe")
        self.assertTrue(parsed.contract_present)
        self.assertTrue(parsed.done)
        self.assertEqual(parsed.status, "pass")
        self.assertIn("live adapter process responded", parsed.final_answer)

    def test_probe_row_exposes_route_isolation_controls(self) -> None:
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command="fake-agent",
            fallback_commands=[],
            args=[],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=False,
            default_timeout_seconds=1,
            terminal_mode="subprocess",
        )
        route_profile = RouteProfile(
            profile_id="A-search-only",
            display_name="Search-only baseline",
            allowed_tools=[],
            blocked_tools=["Serena"],
            required_first_tool="rg_or_fd",
            high_fanout_policy="raw_search_allowed",
            max_raw_output_bytes=12000,
            instructions="search only",
        )
        isolation = RouteIsolation(
            agent_id="fake-agent",
            profile_id="A-search-only",
            command="fake-agent",
            args=[],
            env={},
            mode="config",
            hard_controls=["fake_hard_control"],
            weak_controls=[],
            config_files=[],
            observations={"probe": "ok"},
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.load_agent_profile", return_value=profile
        ), mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.load_route_profile", return_value=route_profile
        ), mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.materialize_route_isolation", return_value=isolation
        ):
            row = probe_agent(
                agent_id="fake-agent",
                repo=Path(tmp),
                out_root=Path(tmp) / "out",
                timeout_seconds=1,
            )

        self.assertEqual(row["route_profile"], "A-search-only")
        self.assertEqual(row["route_isolation_mode"], "config")
        self.assertEqual(row["route_hard_controls"], ["fake_hard_control"])
        self.assertEqual(row["route_weak_controls"], [])
        self.assertEqual(row["route_isolation_observations"], {"probe": "ok"})

    def test_probe_row_promotes_token_metrics_from_bridge_result(self) -> None:
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command="fake-agent",
            fallback_commands=[],
            args=[],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=1,
            terminal_mode="subprocess",
        )
        route_profile = RouteProfile(
            profile_id="A-search-only",
            display_name="Search-only baseline",
            allowed_tools=[],
            blocked_tools=["Serena"],
            required_first_tool="rg_or_fd",
            high_fanout_policy="raw_search_allowed",
            max_raw_output_bytes=12000,
            instructions="search only",
        )
        isolation = RouteIsolation(
            agent_id="fake-agent",
            profile_id="A-search-only",
            command="fake-agent",
            args=[],
            env={},
            mode="config",
            hard_controls=["fake_hard_control"],
            weak_controls=[],
            config_files=[],
            observations={},
        )

        class FakeBridge:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def launch_plan(self):
                return LaunchPlan(
                    agent_id="fake-agent",
                    command=["fake-agent"],
                    cwd=".",
                    prompt_mode="stdin",
                    telemetry_sources=["transcript_proxy"],
                    supports_live=True,
                    terminal_mode="subprocess",
                    env={},
                )

            def run_prompt(self, *, run_id: str, out_dir: Path, sentinel: str, **kwargs: object):
                out = Path(out_dir)
                transcript = out / "transcript.txt"
                transcript.write_text(f"BENCHMARK_RESULT\nstatus: pass\npolicy_adherence: pass\n{sentinel}\n", encoding="utf-8")
                metrics = out / "metrics.normalized.json"
                metrics.write_text(
                    '{"token_source":"exact","exact_total_tokens":42,"exact_uncached_total_tokens":30,"exact_usage_event_count":1}\n',
                    encoding="utf-8",
                )
                return type(
                    "Result",
                    (),
                    {
                        "completion_reason": "sentinel",
                        "transcript_path": str(transcript),
                        "metrics_path": str(metrics),
                        "wall_seconds": 0.1,
                    },
                )()

        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.load_agent_profile", return_value=profile
        ), mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.load_route_profile", return_value=route_profile
        ), mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.materialize_route_isolation", return_value=isolation
        ), mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.shutil.which", return_value="/bin/fake-agent"
        ), mock.patch(
            "scripts.benchmarks.probe_live_agent_adapters.TerminalAgentBridge", FakeBridge
        ):
            row = probe_agent(
                agent_id="fake-agent",
                repo=Path(tmp),
                out_root=Path(tmp) / "out",
                timeout_seconds=1,
            )

        self.assertEqual(row["token_source"], "exact")
        self.assertEqual(row["exact_total_tokens"], 42)
        self.assertEqual(row["exact_uncached_total_tokens"], 30)
        self.assertTrue(row["non_proxy_token_telemetry_ready"])


if __name__ == "__main__":
    unittest.main()
