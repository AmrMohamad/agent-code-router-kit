from __future__ import annotations

import unittest
from pathlib import Path

from scripts.lib.agent_session import load_agent_profile, load_route_profile, load_tasks


ROOT = Path(__file__).resolve().parents[2]


class AgentRunSchemaTests(unittest.TestCase):
    def test_load_agent_profile(self) -> None:
        profile = load_agent_profile(ROOT / "benchmarks/real-agent-routing/agents/codex.yaml")
        self.assertEqual(profile.agent_id, "codex")
        self.assertIn("transcript_proxy", profile.telemetry_sources)

    def test_load_route_profile(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/D-full-router.yaml")
        self.assertEqual(profile.profile_id, "D-full-router")
        self.assertEqual(profile.high_fanout_policy, "summary_first_required")
        self.assertIn("Serena", profile.allowed_tools)

    def test_load_tasks(self) -> None:
        tasks = load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.example.tsv")
        self.assertGreaterEqual(len(tasks), 12)
        families = {task.task_family for task in tasks}
        self.assertIn("high_fanout_usecase", families)
        self.assertIn("build_install_launch_smoke_proof", families)


if __name__ == "__main__":
    unittest.main()
