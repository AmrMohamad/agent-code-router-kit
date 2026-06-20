from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.benchmarks.doctor_live_agent_adapters import (
    classify_next_action,
    parse_claude_auth_status,
    parse_cursor_about,
    redact_diagnostic_text,
    main,
    run_doctor,
)
from scripts.lib.serena_readiness import SerenaProcessState


@contextlib.contextmanager
def installed_codex_cli():
    def fake_which(command: str) -> str | None:
        return "/usr/bin/true" if command == "codex" else None

    with mock.patch("scripts.benchmarks.doctor_live_agent_adapters.shutil.which", side_effect=fake_which):
        yield


class LiveAgentAdapterDoctorTests(unittest.TestCase):
    def test_classifies_known_blocker_next_actions(self) -> None:
        self.assertIn("authenticate", classify_next_action("authentication_failed"))
        self.assertIn("organization", classify_next_action("model_access_denied"))
        self.assertIn("quota", classify_next_action("quota_exceeded"))
        self.assertIn("sentinel without the benchmark contract", classify_next_action("missing_contract"))
        self.assertEqual(classify_next_action(""), "ready")

    def test_redacts_cli_diagnostic_identity_and_secret_values(self) -> None:
        text = "User a@example.com token=abc 032cf879-3676-4a2b-b9f3-ee53db593624"
        redacted = redact_diagnostic_text(text)
        self.assertNotIn("a@example.com", redacted)
        self.assertNotIn("abc", redacted)
        self.assertNotIn("032cf879", redacted)

    def test_parses_claude_auth_status_without_identity_fields(self) -> None:
        parsed = parse_claude_auth_status(
            {
                "stdout": json.dumps(
                    {
                        "loggedIn": True,
                        "authMethod": "claude.ai",
                        "apiProvider": "firstParty",
                        "email": "a@example.com",
                        "orgId": "org",
                        "subscriptionType": "pro",
                    }
                )
            }
        )
        self.assertEqual(parsed["loggedIn"], True)
        self.assertEqual(parsed["subscriptionType"], "pro")
        self.assertNotIn("email", parsed)
        self.assertNotIn("orgId", parsed)

    def test_parses_cursor_about_fields(self) -> None:
        parsed = parse_cursor_about(
            {
                "stdout": "\n".join(
                    [
                        "CLI Version         2026.05.16-0338208",
                        "Model               Composer 2.5 Fast",
                        "Subscription Tier   Team",
                        "OS                  darwin (arm64)",
                    ]
                )
            }
        )
        self.assertEqual(parsed["version"], "2026.05.16-0338208")
        self.assertEqual(parsed["model"], "Composer 2.5 Fast")
        self.assertEqual(parsed["subscription_tier"], "Team")

    def test_no_probe_reports_installed_metadata_without_claiming_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with installed_codex_cli():
                summary = run_doctor(
                    agents=["codex"],
                    repo=Path(tmp),
                    out_root=Path(tmp) / "doctor",
                    timeout_seconds=1,
                    terminal_mode="subprocess",
                    run_probe=False,
                )
            self.assertEqual(summary["status"], "fail")
            self.assertEqual(summary["rows"][0]["reason"], "probe_skipped")
            self.assertFalse(summary["rows"][0]["ready_for_live_benchmark"])
            self.assertIn("cli_diagnostics", summary["rows"][0])
            self.assertTrue((Path(tmp) / "doctor" / "adapter-doctor-summary.json").exists())

    def test_probe_results_are_promoted_to_doctor_blockers(self) -> None:
        fake_probe = {
            "agent": "codex",
            "status": "fail",
            "reason": "quota_exceeded",
            "completion_reason": "sentinel",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                installed_codex_cli(),
                mock.patch("scripts.benchmarks.doctor_live_agent_adapters.probe_agent", return_value=fake_probe),
            ):
                summary = run_doctor(
                    agents=["codex"],
                    repo=Path(tmp),
                    out_root=Path(tmp) / "doctor",
                    timeout_seconds=1,
                    terminal_mode="subprocess",
                    run_probe=True,
                )
            self.assertEqual(summary["status"], "fail")
            self.assertEqual(summary["blockers"][0]["reason"], "quota_exceeded")
            self.assertIn("quota", summary["blockers"][0]["next_action"])

    def test_probe_weak_route_controls_block_readiness_even_when_launch_passes(self) -> None:
        fake_probe = {
            "agent": "codex",
            "status": "pass",
            "reason": "",
            "completion_reason": "sentinel",
            "route_weak_controls": ["weak_control"],
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                installed_codex_cli(),
                mock.patch("scripts.benchmarks.doctor_live_agent_adapters.probe_agent", return_value=fake_probe),
            ):
                summary = run_doctor(
                    agents=["codex"],
                    repo=Path(tmp),
                    out_root=Path(tmp) / "doctor",
                    timeout_seconds=1,
                    terminal_mode="subprocess",
                    run_probe=True,
                )
        self.assertEqual(summary["status"], "fail")
        self.assertFalse(summary["rows"][0]["ready_for_live_benchmark"])
        self.assertFalse(summary["rows"][0]["route_isolation_ready"])
        self.assertIn("route-isolation", summary["blockers"][0]["next_action"])

    def test_probe_token_source_promotes_token_telemetry_readiness(self) -> None:
        fake_probe = {
            "agent": "codex",
            "status": "pass",
            "reason": "",
            "completion_reason": "sentinel",
            "token_source": "exact",
            "exact_total_tokens": 42,
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                installed_codex_cli(),
                mock.patch("scripts.benchmarks.doctor_live_agent_adapters.probe_agent", return_value=fake_probe),
            ):
                summary = run_doctor(
                    agents=["codex"],
                    repo=Path(tmp),
                    out_root=Path(tmp) / "doctor",
                    timeout_seconds=1,
                    terminal_mode="subprocess",
                    run_probe=True,
                )

        self.assertEqual(summary["status"], "pass")
        self.assertTrue(summary["rows"][0]["token_telemetry_ready"])
        self.assertEqual(summary["rows"][0]["token_telemetry_next_action"], "ready")

    def test_clean_serena_process_state_requirement_blocks_ready_probe(self) -> None:
        fake_probe = {
            "agent": "codex",
            "status": "pass",
            "reason": "",
            "completion_reason": "sentinel",
            "token_source": "exact",
            "exact_total_tokens": 42,
        }
        dirty_state = SerenaProcessState(serena_mcp=2, kotlin_lsp=3, json_lsp=1)
        with tempfile.TemporaryDirectory() as tmp:
            with (
                installed_codex_cli(),
                mock.patch("scripts.benchmarks.doctor_live_agent_adapters.probe_agent", return_value=fake_probe),
                mock.patch("scripts.benchmarks.doctor_live_agent_adapters.serena_process_state", return_value=dirty_state),
            ):
                summary = run_doctor(
                    agents=["codex"],
                    repo=Path(tmp),
                    out_root=Path(tmp) / "doctor",
                    timeout_seconds=1,
                    terminal_mode="subprocess",
                    run_probe=True,
                    require_clean_serena_process_state=True,
                )

        self.assertEqual(summary["status"], "fail")
        self.assertEqual(summary["serena_process_state"]["serena_mcp"], 2)
        self.assertIn("multiple_serena_mcp_processes", summary["serena_process_state_warnings"])
        self.assertFalse(summary["rows"][0]["ready_for_live_benchmark"])
        self.assertFalse(summary["rows"][0]["serena_process_state_ready"])
        self.assertIn("Serena", summary["blockers"][0]["next_action"])

    def test_exact_usage_without_total_does_not_promote_token_telemetry_readiness(self) -> None:
        fake_probe = {
            "agent": "codex",
            "status": "pass",
            "reason": "",
            "completion_reason": "sentinel",
            "token_source": "exact",
            "exact_usage_event_count": 2,
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                installed_codex_cli(),
                mock.patch("scripts.benchmarks.doctor_live_agent_adapters.probe_agent", return_value=fake_probe),
            ):
                summary = run_doctor(
                    agents=["codex"],
                    repo=Path(tmp),
                    out_root=Path(tmp) / "doctor",
                    timeout_seconds=1,
                    terminal_mode="subprocess",
                    run_probe=True,
                )

        self.assertEqual(summary["status"], "pass")
        self.assertFalse(summary["rows"][0]["token_telemetry_ready"])
        self.assertIn("token telemetry", summary["rows"][0]["token_telemetry_next_action"])

    def test_proxy_only_probe_keeps_real_token_readiness_false_without_blocking_launch(self) -> None:
        fake_probe = {
            "agent": "codex",
            "status": "pass",
            "reason": "",
            "completion_reason": "sentinel",
            "token_source": "proxy",
        }
        with tempfile.TemporaryDirectory() as tmp:
            with (
                installed_codex_cli(),
                mock.patch("scripts.benchmarks.doctor_live_agent_adapters.probe_agent", return_value=fake_probe),
            ):
                summary = run_doctor(
                    agents=["codex"],
                    repo=Path(tmp),
                    out_root=Path(tmp) / "doctor",
                    timeout_seconds=1,
                    terminal_mode="subprocess",
                    run_probe=True,
                )

        self.assertEqual(summary["status"], "pass")
        self.assertTrue(summary["rows"][0]["ready_for_live_benchmark"])
        self.assertFalse(summary["rows"][0]["token_telemetry_ready"])
        self.assertIn("token telemetry", summary["rows"][0]["token_telemetry_next_action"])

    def test_cli_writes_json_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                with installed_codex_cli():
                    code = main(
                        [
                            "--agents",
                            "codex",
                            "--repo",
                            tmp,
                            "--out",
                            str(Path(tmp) / "doctor"),
                            "--no-probe",
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stdout.getvalue())["rows"][0]["reason"], "probe_skipped")


if __name__ == "__main__":
    unittest.main()
