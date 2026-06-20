from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
import shutil
from pathlib import Path
import sys
from unittest.mock import patch

from scripts.agents.generic_terminal_agent_bridge import (
    TerminalAgentBridge,
    budget_relevant_output_bytes,
    format_stream_delta_for_operator,
    parseable_benchmark_answer_delta,
)
from scripts.lib.agent_session import AgentProfile, load_agent_profile
from scripts.lib.serena_readiness import SerenaProcess


ROOT = Path(__file__).resolve().parents[2]


def telemetry_events(path: str | Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


class TerminalAgentBridgeTests(unittest.TestCase):
    def test_operator_stream_formats_json_events_without_dumping_payloads(self) -> None:
        stream = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "/bin/zsh -lc 'sed -n 1,120p VeryLargeFile.kt'",
                            "aggregated_output": "x" * 2000,
                            "exit_code": 0,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "agent_message",
                            "text": "BENCHMARK_RESULT\nstatus: pass\nfinal_answer:\n  definition found\nBENCHMARK_DONE_run",
                        },
                    }
                ),
            ]
        )

        rendered = format_stream_delta_for_operator(stream)

        self.assertIn("codex thread started thread-123", rendered)
        self.assertIn("command completed exit=0 output_bytes=2000", rendered)
        self.assertIn("benchmark result pass: definition found", rendered)
        self.assertNotIn("x" * 100, rendered)

    def test_budget_relevant_output_ignores_json_prompt_without_tool_output(self) -> None:
        transcript = '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"large prompt"}]}}\n'
        self.assertEqual(budget_relevant_output_bytes(transcript, fallback_to_raw=False), 0)
        self.assertGreater(budget_relevant_output_bytes("raw terminal output", fallback_to_raw=True), 0)

    def test_parseable_benchmark_answer_delta_uses_last_contract_block(self) -> None:
        text = (
            "echoed prompt says BENCHMARK_RESULT\n"
            "status: pass|fail\n"
            "BENCHMARK_DONE_run-x\n"
            "assistant prose\n"
            "BENCHMARK_RESULT\n"
            "status: pass\n"
            "final_answer:\n"
            "  real answer\n"
            "BENCHMARK_DONE_run-x\n"
            "input placeholder"
        )

        parsed = parseable_benchmark_answer_delta(text, sentinel="BENCHMARK_DONE_run-x")

        self.assertEqual(
            parsed,
            "BENCHMARK_RESULT\nstatus: pass\nfinal_answer:\n  real answer\nBENCHMARK_DONE_run-x",
        )

    def test_budget_relevant_output_counts_json_tool_results(self) -> None:
        transcript = (
            '{"type":"item.completed","item":{"id":"item_1","type":"command_execution",'
            '"command":"rg Foo","aggregated_output":"tool output","exit_code":0}}\n'
        )
        self.assertGreaterEqual(
            budget_relevant_output_bytes(transcript, fallback_to_raw=False),
            len("tool output"),
        )

    def test_codex_json_stream_budget_ignores_provider_event_bytes(self) -> None:
        script = (
            "import sys\n"
            "sys.stdin.read()\n"
            "import json\n"
            "print(json.dumps({'type':'thread.started','thread_id':'t'}), flush=True)\n"
            "print(json.dumps({'type':'user_message','message':{'role':'user','content':[{'type':'text','text':'tool_outputs:\\\\n' + ('prompt text ' * 200)}]}}), flush=True)\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'"
            "BENCHMARK_RESULT\\nstatus: pass\\ntools_used:\\n  - rg\\n"
            "proof_layers:\\n  semantic_identity: search-only evidence\\n  references: not used\\n  runtime: not run\\n"
            "files_opened:\\n  count: 0\\n  paths:\\n"
            "raw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  ok\\nBENCHMARK_DONE_codex-budget"
            "'}}), flush=True)\n"
            "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':7,'output_tokens':3}}), flush=True)\n"
        )
        profile = AgentProfile(
            agent_id="codex",
            display_name="Codex",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["codex_json"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="subprocess",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = bridge.run_prompt(
                    run_id="codex-budget",
                    prompt="hello",
                    out_dir=tmp,
                    timeout_seconds=5,
                    sentinel="BENCHMARK_DONE_codex-budget",
                    profile_id="A-search-only",
                    task_id="known_symbol_definition",
                    max_output_bytes=10,
                )

            self.assertEqual(result.completion_reason, "sentinel")
            self.assertEqual(stdout.getvalue(), "")
            metrics = json.loads((Path(tmp) / "metrics.normalized.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["token_source"], "exact")
            self.assertEqual(metrics["exact_total_tokens"], 10)
            self.assertNotIn("output_budget_exceeded", [event["event"] for event in telemetry_events(result.telemetry_path)])

    def test_codex_pty_budget_ignores_bootstrap_tool_output_but_records_it(self) -> None:
        bootstrap_output = "x" * 60000
        script = (
            "import json, sys\n"
            "sys.stdin.read()\n"
            f"bootstrap_output = {bootstrap_output!r}\n"
            "print(json.dumps({'type':'item.completed','item':{'id':'item_boot','type':'command_execution',"
            "'command':'sed -n 1,260p /Users/example/.codex/skills/agent-policy-guard/SKILL.md',"
            "'aggregated_output':bootstrap_output,'exit_code':0}}), flush=True)\n"
            "print(json.dumps({'type':'item.completed','item':{'id':'item_task','type':'command_execution',"
            "'command':'rg -l StoreLocatorFragment --glob *.kt','aggregated_output':'path\\n','exit_code':0}}), flush=True)\n"
            "print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'"
            "BENCHMARK_RESULT\\nstatus: pass\\ntools_used:\\n  - rg\\n"
            "proof_layers:\\n  semantic_identity: search evidence\\n  references: not used\\n  runtime: not run\\n"
            "files_opened:\\n  count: 0\\n  paths:\\n"
            "raw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  ok\\nBENCHMARK_DONE_codex-pty-bootstrap"
            "'}}), flush=True)\n"
            "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':11,'output_tokens':5}}), flush=True)\n"
        )
        profile = AgentProfile(
            agent_id="codex",
            display_name="Codex",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["codex_json"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="pty",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False, terminal_mode="pty")
            result = bridge.run_prompt(
                run_id="codex-pty-bootstrap",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_codex-pty-bootstrap",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
                max_output_bytes=10,
            )

            self.assertEqual(result.completion_reason, "sentinel")
            metrics = json.loads((Path(tmp) / "metrics.normalized.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["raw_task_output_bytes"], len("path\n"))
            self.assertGreaterEqual(metrics["raw_bootstrap_output_bytes"], len(bootstrap_output))
            self.assertEqual(metrics["token_source"], "exact")
            self.assertNotIn("output_budget_exceeded", [event["event"] for event in telemetry_events(result.telemetry_path)])

    def test_dry_run_writes_artifacts(self) -> None:
        profile = load_agent_profile(ROOT / "benchmarks/real-agent-routing/agents/codex.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=True)
            result = bridge.run_prompt(
                run_id="run-1",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=1,
                sentinel="BENCHMARK_DONE_run-1",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertTrue(Path(result.transcript_path).exists())
            self.assertTrue((Path(tmp) / "metrics.normalized.json").exists())
            self.assertTrue((Path(tmp) / "telemetry.jsonl").exists())

    def test_launch_plan_is_stable(self) -> None:
        profile = load_agent_profile(ROOT / "benchmarks/real-agent-routing/agents/cursor-agent.yaml")
        bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=True)
        plan = bridge.launch_plan()
        self.assertEqual(plan.agent_id, "cursor-agent")
        self.assertIn("--sandbox", plan.command)
        self.assertNotIn("--stream-partial-output", plan.command)

    def test_live_bridge_runs_supported_command(self) -> None:
        script = (
            "import sys; sys.stdin.read(); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\ntools_used:\\n  - rg\\n"
            "tool_outputs:\\n  hello tool output\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  definition location reported\\nBENCHMARK_DONE_run-2')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="subprocess",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-2",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-2",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")
            metrics = (Path(tmp) / "metrics.normalized.json").read_text(encoding="utf-8")
            self.assertIn('"tool_output_bytes"', metrics)
            events = telemetry_events(result.telemetry_path)
            event_names = [event["event"] for event in events]
            self.assertIn("process_started", event_names)
            self.assertIn("process_exited", event_names)
            process_exit = next(event for event in events if event["event"] == "process_exited")
            self.assertEqual(process_exit["returncode"], 0)
            self.assertGreater(process_exit["stdout_bytes"], 0)

    def test_live_bridge_can_stream_supported_command(self) -> None:
        script = (
            "import sys; sys.stdin.read(); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\ntools_used:\\n  - rg\\n"
            "raw_dump_incidents:\\n  count: 0\\npolicy_adherence: pass\\n"
            "final_answer:\\n  definition location reported\\nBENCHMARK_DONE_run-3')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="subprocess",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False, stream_agent_output=True)
            with contextlib.redirect_stdout(io.StringIO()):
                result = bridge.run_prompt(
                    run_id="run-3",
                    prompt="hello",
                    out_dir=tmp,
                    timeout_seconds=5,
                    sentinel="BENCHMARK_DONE_run-3",
                    profile_id="A-search-only",
                    task_id="known_symbol_definition",
                )
            self.assertEqual(result.completion_reason, "sentinel")

    def test_live_bridge_marks_output_budget_exceeded(self) -> None:
        script = "import sys; sys.stdin.read(); print('x' * 200)"
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="subprocess",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-budget",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-budget",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
                max_output_bytes=50,
            )
            self.assertEqual(result.completion_reason, "output_budget_exceeded")
            event_names = [event["event"] for event in telemetry_events(result.telemetry_path)]
            self.assertIn("output_budget_exceeded", event_names)

    def test_live_bridge_monitor_prints_lifecycle_events(self) -> None:
        script = (
            "import sys; sys.stdin.read(); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\ntools_used:\\n  - rg\\n"
            "raw_dump_incidents:\\n  count: 0\\npolicy_adherence: pass\\n"
            "final_answer:\\n  definition location reported\\nBENCHMARK_DONE_run-monitor')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="subprocess",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(
                profile,
                cwd=str(ROOT),
                dry_run=False,
                stream_agent_output=True,
                monitor_live_events=True,
            )
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = bridge.run_prompt(
                    run_id="run-monitor",
                    prompt="hello",
                    out_dir=tmp,
                    timeout_seconds=5,
                    sentinel="BENCHMARK_DONE_run-monitor",
                    profile_id="A-search-only",
                    task_id="known_symbol_definition",
                )
            output = stdout.getvalue()
            self.assertEqual(result.completion_reason, "sentinel")
            self.assertIn("live fake-agent process_spawned", output)
            self.assertIn("live fake-agent prompt_sent", output)
            self.assertIn("live fake-agent process_output_chunk", output)
            self.assertIn("live fake-agent process_exited", output)

    def test_live_bridge_can_run_through_pty(self) -> None:
        script = (
            "import sys; sys.stdin.read(); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\ntools_used:\\n  - rg\\n"
            "raw_dump_incidents:\\n  count: 0\\npolicy_adherence: pass\\n"
            "final_answer:\\n  definition location reported\\nBENCHMARK_DONE_run-4')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="pty",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-4",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-4",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")
            events = telemetry_events(result.telemetry_path)
            event_names = [event["event"] for event in events]
            self.assertIn("process_spawned", event_names)
            self.assertIn("prompt_sent", event_names)
            self.assertIn("process_output_chunk", event_names)
            self.assertIn("process_exited", event_names)

    def test_pty_does_not_count_prompt_sentinel_echo(self) -> None:
        script = (
            "import sys; sys.stdin.read(); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  no sentinel here')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="pty",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-5",
                prompt="prompt includes BENCHMARK_DONE_run-5",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-5",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "missing_sentinel")

    def test_argument_prompt_mode_passes_prompt_as_argv(self) -> None:
        script = (
            "import sys; prompt = sys.argv[1]; "
            "print('BENCHMARK_RESULT\\nstatus: pass\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  argv prompt seen\\n' + prompt.split()[-1])"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="argument",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="pty",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-6",
                prompt="hello BENCHMARK_DONE_run-6",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-6",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_live_bridge_can_run_through_tmux(self) -> None:
        script = (
            "import sys; sys.stdin.read(); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\ntools_used:\\n  - rg\\n"
            "raw_dump_incidents:\\n  count: 0\\npolicy_adherence: pass\\n"
            "final_answer:\\n  definition location reported\\nBENCHMARK_DONE_run-7')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="tmux",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-7",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-7",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")
            transcript = Path(result.transcript_path).read_text(encoding="utf-8")
            self.assertIn("definition location reported", transcript)
            events = telemetry_events(result.telemetry_path)
            event_names = [event["event"] for event in events]
            self.assertIn("tmux_session_started", event_names)
            self.assertIn("terminal_capture_changed", event_names)
            self.assertIn("sentinel_observed", event_names)
            self.assertIn("tmux_session_closed", event_names)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_stdin_prompt_is_piped_not_tty(self) -> None:
        script = (
            "import sys; "
            "assert not sys.stdin.isatty(), 'stdin must be piped'; "
            "prompt = sys.stdin.read(); "
            "assert 'hello from stdin' in prompt; "
            "print('BENCHMARK_RESULT\\nstatus: pass\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  piped stdin prompt seen\\nBENCHMARK_DONE_run-7b')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="tmux",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-7b",
                prompt="hello from stdin",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-7b",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")
            events = telemetry_events(result.telemetry_path)
            prompt_events = [event for event in events if event["event"] == "prompt_sent"]
            self.assertEqual(prompt_events[-1]["prompt_transport"], "tmux-stdin-pipe")

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_argument_prompt_mode_keeps_multiline_prompt_as_single_argument(self) -> None:
        script = (
            "import sys; prompt = sys.argv[1]; "
            "assert 'line one\\nline two' in prompt; "
            "print('BENCHMARK_RESULT\\nstatus: pass\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  multiline argv prompt seen\\nBENCHMARK_DONE_run-8')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="argument",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="tmux",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-8",
                prompt="line one\nline two\nBENCHMARK_DONE_run-8",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-8",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_argument_prompt_mode_ignores_echoed_prompt_sentinel(self) -> None:
        script = (
            "import json, sys, time; prompt = sys.argv[1]; "
            "print(json.dumps({'type':'user','message':{'role':'user','content':[{'type':'text','text':prompt}]}}), flush=True); "
            "time.sleep(0.2); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  real answer sentinel\\nBENCHMARK_DONE_run-9')"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="argument",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="tmux",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-9",
                prompt="user echo contains BENCHMARK_DONE_run-9",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-9",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")
            transcript = Path(result.transcript_path).read_text(encoding="utf-8")
            self.assertIn("real answer sentinel", transcript)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_keeps_post_sentinel_usage_event(self) -> None:
        script = (
            "import json, sys, time; sys.stdin.read(); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  answer\\nBENCHMARK_DONE_run-10', flush=True); "
            "time.sleep(0.3); "
            "print(json.dumps({'type':'turn.completed','usage':{'input_tokens':11,'output_tokens':7}}), flush=True)"
        )
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="tmux",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-10",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-10",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")
            metrics = json.loads((Path(tmp) / "metrics.normalized.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["token_source"], "exact")
            self.assertEqual(metrics["exact_total_tokens"], 18)
            event_names = [event["event"] for event in telemetry_events(result.telemetry_path)]
            self.assertIn("post_sentinel_capture_complete", event_names)

    @unittest.skipUnless(shutil.which("tmux"), "tmux is not installed")
    def test_tmux_codex_stderr_is_captured_as_diagnostics(self) -> None:
        script = (
            "import sys; sys.stdin.read(); "
            "print('local warning from cli', file=sys.stderr); "
            "print('BENCHMARK_RESULT\\nstatus: pass\\nraw_dump_incidents:\\n  count: 0\\n"
            "policy_adherence: pass\\nfinal_answer:\\n  answer\\nBENCHMARK_DONE_run-11')"
        )
        profile = AgentProfile(
            agent_id="codex",
            display_name="Codex CLI",
            command=sys.executable,
            fallback_commands=[],
            args=["-c", script],
            env={},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="tmux",
        )
        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False)
            result = bridge.run_prompt(
                run_id="run-11",
                prompt="hello",
                out_dir=tmp,
                timeout_seconds=5,
                sentinel="BENCHMARK_DONE_run-11",
                profile_id="A-search-only",
                task_id="known_symbol_definition",
            )
            self.assertEqual(result.completion_reason, "sentinel")
            transcript = Path(result.transcript_path).read_text(encoding="utf-8")
            self.assertNotIn("local warning from cli", transcript)
            self.assertIn("local warning from cli", (Path(tmp) / "agent.stderr.txt").read_text(encoding="utf-8"))
            event_names = [event["event"] for event in telemetry_events(result.telemetry_path)]
            self.assertIn("stderr_captured", event_names)

    def test_codex_tui_mode_uses_visible_bridge_and_parseable_answer_delta(self) -> None:
        profile = AgentProfile(
            agent_id="codex",
            display_name="Codex CLI",
            command="codex",
            fallback_commands=[],
            args=["exec", "--json", "-"],
            env={"RARB_CODEX_TUI_NO_TERMINAL_ATTACH": "1"},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="codex-tui",
        )
        answer = (
            "BENCHMARK_RESULT\n"
            "status: pass\n"
            "tools_used:\n"
            "  - Serena\n"
            "raw_dump_incidents:\n"
            "  count: 0\n"
            "policy_adherence: pass\n"
            "final_answer:\n"
            "  definition location reported\n"
            "BENCHMARK_DONE_run-tui"
        )
        payload = {
            "complete": True,
            "completion_reason": "sentinel",
            "transcript": "OpenAI Codex TUI\n" + answer,
            "answer_delta": answer,
        }
        completed = [
            subprocess.CompletedProcess(args=["run-once"], returncode=0, stdout=json.dumps(payload), stderr=""),
            subprocess.CompletedProcess(args=["close"], returncode=0, stdout="{}\n", stderr=""),
        ]

        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False, terminal_mode="codex-tui")
            with (
                patch("scripts.agents.generic_terminal_agent_bridge.shutil.which", return_value="/opt/homebrew/bin/tmux"),
                patch("scripts.agents.generic_terminal_agent_bridge.serena_related_processes", return_value=[]),
                patch.object(bridge, "_run_codex_tui_bridge_command", side_effect=completed) as bridge_command,
            ):
                result = bridge.run_prompt(
                    run_id="run-tui",
                    prompt="hello",
                    out_dir=tmp,
                    timeout_seconds=10,
                    sentinel="BENCHMARK_DONE_run-tui",
                    profile_id="D-full-router",
                    task_id="known_symbol_definition",
                )

            self.assertEqual(result.completion_reason, "sentinel")
            transcript = Path(result.transcript_path).read_text(encoding="utf-8")
            self.assertEqual(transcript.strip(), answer)
            self.assertIn("OpenAI Codex TUI", (Path(tmp) / "visible-terminal-transcript.txt").read_text(encoding="utf-8"))
            event_names = [event["event"] for event in telemetry_events(result.telemetry_path)]
            self.assertIn("codex_tui_opened", event_names)
            self.assertIn("prompt_sent", event_names)
            self.assertIn("sentinel_observed", event_names)
            self.assertIn("tmux_session_closed", event_names)
            self.assertEqual(bridge_command.call_args_list[0].args[0][0], "run-once")
            self.assertIn("--prompt-file", bridge_command.call_args_list[0].args[0])
            self.assertEqual(bridge_command.call_args_list[1].args[0][0], "close")

    def test_codex_tui_mode_cleans_only_new_serena_processes(self) -> None:
        profile = AgentProfile(
            agent_id="codex",
            display_name="Codex CLI",
            command="codex",
            fallback_commands=[],
            args=["exec", "--json", "-"],
            env={"RARB_CODEX_TUI_NO_TERMINAL_ATTACH": "1"},
            prompt_mode="stdin",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="codex-tui",
        )
        answer = "BENCHMARK_RESULT\nstatus: pass\npolicy_adherence: pass\nBENCHMARK_DONE_run-clean"
        payload = {"complete": True, "completion_reason": "sentinel", "transcript": answer, "answer_delta": answer}
        before = [SerenaProcess(pid=100, command="serena start-mcp-server --context=codex")]
        after = [
            SerenaProcess(pid=100, command="serena start-mcp-server --context=codex"),
            SerenaProcess(pid=200, command="serena start-mcp-server --context=codex"),
            SerenaProcess(pid=300, command="KotlinLspServerKt --stdio"),
        ]
        terminated = [
            {"pid": 200, "command": after[1].command, "terminated": True, "signal": "TERM"},
            {"pid": 300, "command": after[2].command, "terminated": True, "signal": "TERM"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False, terminal_mode="codex-tui")
            with (
                patch("scripts.agents.generic_terminal_agent_bridge.shutil.which", return_value="/opt/homebrew/bin/tmux"),
                patch.object(
                    bridge,
                    "_run_codex_tui_bridge_command",
                    side_effect=[
                        subprocess.CompletedProcess(args=["run-once"], returncode=0, stdout=json.dumps(payload), stderr=""),
                        subprocess.CompletedProcess(args=["close"], returncode=0, stdout="{}\n", stderr=""),
                    ],
                ),
                patch("scripts.agents.generic_terminal_agent_bridge.serena_related_processes", side_effect=[before, after]),
                patch("scripts.agents.generic_terminal_agent_bridge.terminate_processes", return_value=terminated) as terminate,
            ):
                result = bridge.run_prompt(
                    run_id="run-clean",
                    prompt="hello",
                    out_dir=tmp,
                    timeout_seconds=10,
                    sentinel="BENCHMARK_DONE_run-clean",
                    profile_id="D-full-router",
                    task_id="known_symbol_definition",
                )

            terminate.assert_called_once()
            self.assertEqual([process.pid for process in terminate.call_args.args[0]], [200, 300])
            cleanup = json.loads((Path(tmp) / "codex-tui-process-cleanup.json").read_text(encoding="utf-8"))
            self.assertEqual(cleanup["before_pids"], [100])
            self.assertEqual(cleanup["spawned_pids"], [200, 300])
            self.assertEqual([item["pid"] for item in cleanup["terminated"]], [200, 300])
            event_names = [event["event"] for event in telemetry_events(result.telemetry_path)]
            self.assertIn("codex_tui_process_cleanup", event_names)

    def test_argument_prompt_inserted_before_variadic_agent_options(self) -> None:
        profile = AgentProfile(
            agent_id="fake-agent",
            display_name="Fake Agent",
            command="agent",
            fallback_commands=[],
            args=["-p", "--tools", "Read,Grep,Glob,Bash"],
            env={},
            prompt_mode="argument",
            telemetry_sources=["transcript_proxy"],
            supports_live=True,
            default_timeout_seconds=10,
            terminal_mode="subprocess",
        )
        bridge = TerminalAgentBridge(profile, cwd=str(ROOT), dry_run=False, command="agent")
        self.assertEqual(
            bridge._command_with_prompt_argument("hello"),
            ["agent", "-p", "hello", "--tools", "Read,Grep,Glob,Bash"],
        )


if __name__ == "__main__":
    unittest.main()
