from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "scripts" / "benchmarks" / "android" / "process_state_probe.py"
spec = importlib.util.spec_from_file_location("android_process_state_probe", PROBE_PATH)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)


class AndroidProcessStateProbeTests(unittest.TestCase):
    def test_status_flags_duplicate_mcp_or_kotlin_lsp_as_stale_risk(self) -> None:
        self.assertEqual(
            probe.status_from_counts(
                {
                    "serena_mcp": 2,
                    "kotlin_lsp": 1,
                    "json_lsp": 1,
                    "java_jdtls": 0,
                }
            ),
            "stale-session-risk",
        )
        self.assertEqual(
            probe.status_from_counts(
                {
                    "serena_mcp": 1,
                    "kotlin_lsp": 2,
                    "json_lsp": 1,
                    "java_jdtls": 0,
                }
            ),
            "stale-session-risk",
        )

    def test_status_flags_jdtls_when_primary_sessions_are_clean(self) -> None:
        self.assertEqual(
            probe.status_from_counts(
                {
                    "serena_mcp": 1,
                    "kotlin_lsp": 1,
                    "json_lsp": 1,
                    "java_jdtls": 1,
                }
            ),
            "jdtls-gradle-risk",
        )

    def test_assertions_warn_on_duplicate_sessions(self) -> None:
        summary = {
            "counts": {
                "serena_mcp": 3,
                "kotlin_lsp": 4,
                "json_lsp": 2,
                "java_jdtls": 1,
            },
            "classification_counts": {},
            "expected_serena_mcp_count": 1,
        }
        assertions = probe.build_assertions(summary)
        self.assertEqual(assertions["summary"]["fail"], 0)
        self.assertGreaterEqual(assertions["summary"]["warn"], 3)

    def test_require_clean_promotes_session_warnings_to_failures(self) -> None:
        summary = {
            "counts": {
                "serena_mcp": 2,
                "kotlin_lsp": 2,
                "json_lsp": 1,
                "java_jdtls": 1,
            },
            "classification_counts": {},
            "expected_serena_mcp_count": 1,
        }
        assertions = probe.build_assertions(summary, require_clean=True)
        self.assertGreaterEqual(assertions["summary"]["fail"], 3)

    def test_classifies_target_project_from_command_path(self) -> None:
        target = "/Users/me/repo"
        row = {
            "kind": "serena_mcp",
            "pid": 1,
            "command": f"serena start-mcp-server --project {target} --context=codex",
        }
        self.assertEqual(probe.classify_process(row, target), "target_project")

    def test_classifies_unknown_project_from_cwd_as_risk(self) -> None:
        row = {
            "kind": "serena_mcp",
            "pid": 1,
            "command": "serena start-mcp-server --project-from-cwd --context=codex",
            "cwd": None,
        }
        self.assertEqual(probe.classify_process(row, "/repo"), "unknown_project_from_cwd")

    def test_expected_serena_count_allows_controlled_server(self) -> None:
        summary = {
            "counts": {
                "serena_mcp": 2,
                "kotlin_lsp": 0,
                "json_lsp": 0,
                "java_jdtls": 0,
            },
            "classification_counts": {"target_project": 1, "target_http_server": 1},
            "expected_serena_mcp_count": 2,
        }
        assertions = probe.build_assertions(summary, require_clean=True)
        self.assertEqual(assertions["summary"]["fail"], 0)

    def test_project_aware_status_uses_target_count_not_total_count(self) -> None:
        counts = {
            "serena_mcp": 3,
            "kotlin_lsp": 0,
            "json_lsp": 0,
            "java_jdtls": 0,
        }
        classifications = {
            "target_project": 1,
            "other_project": 2,
        }
        self.assertEqual(
            probe.status_from_counts(
                counts,
                classifications,
                expected_serena_mcp_count=1,
                allow_other_project_serena=True,
                target_project_path="/repo",
            ),
            "clean",
        )

    def test_other_project_sessions_fail_strict_unless_allowed(self) -> None:
        summary = {
            "counts": {
                "serena_mcp": 2,
                "kotlin_lsp": 0,
                "json_lsp": 0,
                "java_jdtls": 0,
            },
            "classification_counts": {"target_project": 1, "other_project": 1},
            "target_project_path": "/repo",
            "target_serena_mcp_count": 1,
            "other_project_serena_mcp_count": 1,
            "unknown_serena_mcp_count": 0,
            "expected_serena_mcp_count": 1,
            "allow_other_project_serena": False,
        }
        strict = probe.build_assertions(summary, require_clean=True)
        self.assertGreater(strict["summary"]["fail"], 0)
        summary["allow_other_project_serena"] = True
        allowed = probe.build_assertions(summary, require_clean=True)
        self.assertEqual(allowed["summary"]["fail"], 0)


if __name__ == "__main__":
    unittest.main()
