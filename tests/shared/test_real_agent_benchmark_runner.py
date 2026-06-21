from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.benchmarks.build_real_agent_report import write_report
from scripts.benchmarks.run_real_agent_benchmark import (
    dynamic_prompt_rng,
    effective_route_profile,
    main,
    render_task_packet,
    route_uses_serena,
    task_supports_dynamic_code_prompt,
    task_needs_serena_source_readiness,
)
from scripts.agents.generic_terminal_agent_bridge import BridgeRunResult
from scripts.lib.agent_session import LaunchPlan, TaskSpec, load_route_profile, load_tasks
from scripts.lib.route_isolation import RouteIsolation
from scripts.lib.serena_readiness import SerenaProcessState, SerenaReadiness


ROOT = Path(__file__).resolve().parents[2]
IOS_FIXTURE = ROOT / "benchmarks/ios/fixtures/sample"
IOS_HIGH_FANOUT_PROMPT = (
    "Determine where Resolver appears and provide evidence appropriate to the assigned route profile."
)


def make_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("clean\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def fake_codex_home(path: Path) -> Path:
    home = path / "fake-codex-home"
    home.mkdir()
    (home / "auth.json").write_text('{"mode":"test"}\n', encoding="utf-8")
    return home


def write_one_task(path: Path) -> None:
    path.write_text(
        "task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds\n"
        "sample_task\tknown_kotlin_symbol_definition\tsample\tFind SampleFeatureViewModel\tA-search-only\tfalse\tfalse\tsemantic_identity_or_search_labeled\tdefinition location reported\tDo not claim runtime behavior.\t900\n",
        encoding="utf-8",
    )


def write_full_router_task(path: Path) -> None:
    path.write_text(
        "task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds\n"
        "sample_task\tknown_kotlin_symbol_definition\tsample\tFind SampleFeatureViewModel\tD-full-router\tfalse\tfalse\tsemantic_identity_or_search_labeled\tdefinition location reported\tDo not claim runtime behavior.\t900\n",
        encoding="utf-8",
    )


def write_symbol_task(path: Path, *, profile: str = "A-search-only") -> None:
    path.write_text(
        "task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds\n"
        f"sample_task\tknown_kotlin_symbol_definition\tsample\tFind SampleFeatureViewModel and report its definition file.\t{profile}\tfalse\tfalse\tsemantic_identity_or_search_labeled\tSampleFeatureViewModel definition reported\tDo not claim runtime behavior.\t900\n",
        encoding="utf-8",
    )


def ios_high_fanout_task(*, route_profiles: list[str] | None = None) -> TaskSpec:
    return TaskSpec(
        task_id="ios_resolver_fanout",
        task_family="high_fanout_swift_symbol",
        repo="sample_ios",
        prompt=IOS_HIGH_FANOUT_PROMPT,
        route_profiles=route_profiles
        or ["A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"],
        edit_allowed=False,
        build_allowed=False,
        expected_proof_layer="high_fanout_summary",
        expected_success_signal="Resolver summary counts reported",
        forbidden_claims="Do not claim runtime behavior.",
        timeout_seconds=900,
    )


def write_ios_high_fanout_task(path: Path) -> None:
    task = ios_high_fanout_task()
    path.write_text(
        "task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds\n"
        f"{task.task_id}\t{task.task_family}\t{task.repo}\t{task.prompt}\t{','.join(task.route_profiles)}\tfalse\tfalse\t{task.expected_proof_layer}\t{task.expected_success_signal}\t{task.forbidden_claims}\t{task.timeout_seconds}\n",
        encoding="utf-8",
    )


def write_minimal_run_artifacts(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "task-packet.md",
        "transcript.txt",
        "telemetry.jsonl",
        "metrics.normalized.json",
        "judge.json",
        "route-isolation.json",
    ):
        (run_dir / name).write_text("{}\n", encoding="utf-8")


class RealAgentBenchmarkRunnerTests(unittest.TestCase):
    def test_dynamic_prompt_rng_is_profile_invariant_for_paired_route_cells(self) -> None:
        left = dynamic_prompt_rng(
            seed=123,
            repeat_index=0,
            agent_id="codex",
            task_id="known_symbol_definition",
            repo="/repo",
        )
        right = dynamic_prompt_rng(
            seed=123,
            repeat_index=0,
            agent_id="codex",
            task_id="known_symbol_definition",
            repo="/repo",
        )

        self.assertEqual([left.random() for _ in range(3)], [right.random() for _ in range(3)])

    def test_high_fanout_arm_packets_keep_all_profile_behaviors_distinct(self) -> None:
        task = ios_high_fanout_task()
        cases = [
            ("A-search-only", "raw_search_allowed", 50000, False),
            ("B-search-summary", "summary_first", 12000, True),
            ("C-lsp-naive", "weak", 50000, False),
            ("D-full-router", "summary_first_required", 12000, True),
        ]

        for profile_id, expected_policy, expected_budget, requires_summary_first in cases:
            with self.subTest(profile_id=profile_id):
                profile = load_route_profile(ROOT / f"benchmarks/real-agent-routing/profiles/{profile_id}.yaml")
                effective = effective_route_profile(profile, task=task)
                packet = render_task_packet(
                    run_id=f"rarb-{profile_id}",
                    agent="codex",
                    repo=str(ROOT),
                    task=task,
                    profile=effective,
                    sentinel="DONE",
                )

                self.assertEqual(profile.high_fanout_policy, expected_policy)
                self.assertEqual(effective.max_raw_output_bytes, expected_budget)
                self.assertIn(f"Maximum raw output bytes: {expected_budget}", packet)
                if requires_summary_first:
                    self.assertIn("First produce grouped counts only", packet)
                    self.assertIn("A file read before grouped evidence is a benchmark failure", packet)
                    self.assertNotIn("controlled high-fanout baseline", packet)
                    self.assertNotIn("A summary-first command is not required in this arm", packet)
                else:
                    self.assertIn("controlled high-fanout baseline", packet)
                    self.assertIn("A summary-first command is not required in this arm", packet)
                    self.assertNotIn("First produce grouped counts only", packet)
                    self.assertNotIn("A file read before grouped evidence is a benchmark failure", packet)

    def test_full_router_known_kotlin_task_requires_serena_readiness(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/D-full-router.yaml")
        task = next(
            task
            for task in load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv")
            if task.task_id == "known_symbol_definition"
        )

        self.assertTrue(route_uses_serena(profile))
        self.assertTrue(task_needs_serena_source_readiness(task))

    def test_swift_and_web_symbol_tasks_require_serena_readiness(self) -> None:
        swift_task = TaskSpec(
            task_id="known_swift_symbol",
            task_family="known_swift_symbol_definition",
            repo="sample",
            prompt="Find CheckoutCoordinator in the Swift iOS source and report semantic identity.",
            route_profiles=["D-full-router"],
            edit_allowed=False,
            build_allowed=False,
            expected_proof_layer="semantic_identity_or_search_labeled",
            expected_success_signal="CheckoutCoordinator definition reported",
            forbidden_claims="Do not claim runtime behavior.",
            timeout_seconds=900,
        )
        web_task = TaskSpec(
            task_id="known_web_symbol",
            task_family="known_typescript_symbol_definition",
            repo="sample",
            prompt="Find AccountPanel in the React web source and report semantic identity.",
            route_profiles=["D-full-router"],
            edit_allowed=False,
            build_allowed=False,
            expected_proof_layer="semantic_identity_or_search_labeled",
            expected_success_signal="AccountPanel definition reported",
            forbidden_claims="Do not claim runtime behavior.",
            timeout_seconds=900,
        )

        self.assertTrue(task_needs_serena_source_readiness(swift_task))
        self.assertTrue(task_needs_serena_source_readiness(web_task))
        self.assertTrue(task_supports_dynamic_code_prompt(swift_task))

        high_fanout_task = TaskSpec(
            task_id="high_fanout_swift_symbol",
            task_family="high_fanout_swift_symbol",
            repo="sample",
            prompt=IOS_HIGH_FANOUT_PROMPT,
            route_profiles=["D-full-router"],
            edit_allowed=False,
            build_allowed=False,
            expected_proof_layer="high_fanout_summary",
            expected_success_signal="summary counts reported",
            forbidden_claims="Do not claim runtime behavior.",
            timeout_seconds=900,
        )
        self.assertTrue(task_needs_serena_source_readiness(high_fanout_task))
        self.assertFalse(task_supports_dynamic_code_prompt(high_fanout_task))

    def test_search_only_profile_does_not_trigger_serena_readiness(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")

        self.assertFalse(route_uses_serena(profile))

    def test_task_packet_embeds_failed_serena_preflight_without_claiming_semantic_readiness(self) -> None:
        profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/D-full-router.yaml")
        task = next(
            task
            for task in load_tasks(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv")
            if task.task_id == "known_symbol_definition"
        )
        packet = render_task_packet(
            run_id="rarb-test",
            agent="codex",
            repo=str(ROOT),
            task=task,
            profile=profile,
            sentinel="DONE",
            serena_readiness={
                "status": "fail",
                "ready": False,
                "symbol": "SampleFeatureViewModel",
                "source_file": "",
                "reason": "language_server_manager_not_initialized",
                "next_action": "restart stale Serena sessions",
                "process_state": {"serena_mcp": 3, "kotlin_lsp": 2, "json_lsp": 0},
                "warnings": ["multiple_serena_mcp_processes"],
            },
        )

        self.assertIn("## Serena Semantic Preflight", packet)
        self.assertIn("Ready: false", packet)
        self.assertIn("do not claim semantic proof from Serena", packet)
        self.assertIn("language_server_manager_not_initialized", packet)

    def test_dry_run_creates_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(ROOT),
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only,D-full-router",
                        "--task-limit",
                        "2",
                        "--repeats",
                        "1",
                        "--out",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("Updated Plan", stdout.getvalue())
            out = Path(tmp)
            self.assertTrue((out / "run-manifest.json").exists())
            self.assertTrue((out / "runs.jsonl").exists())
            self.assertTrue((out / "monitor.jsonl").exists())
            self.assertTrue((out / "metrics-summary.json").exists())
            self.assertTrue((out / "policy-violations.json").exists())
            self.assertTrue((out / "correctness-summary.json").exists())
            self.assertTrue((out / "route-comparisons.json").exists())
            self.assertTrue((out / "route-claim-readiness.json").exists())
            self.assertTrue((out / "token-savings-report.md").exists())
            self.assertTrue((out / "codex-tui-summary.md").exists())
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text().splitlines()]
            self.assertEqual(len(rows), 4)
            monitor_rows = [json.loads(line) for line in (out / "monitor.jsonl").read_text().splitlines()]
            self.assertEqual(len(monitor_rows), 8)
            self.assertEqual(monitor_rows[0]["event"], "run_started")
            self.assertIn("token_source", rows[0])
            self.assertIn("policy_violations", rows[0])
            self.assertIn("expected_proof_layer_seen", rows[0])
            self.assertIn("tool_evidence_source", rows[0])
            self.assertIn("route_isolation_mode", rows[0])
            run_dirs = [Path(row["run_dir"]) for row in rows]
            self.assertTrue(all((run_dir / "route-isolation.json").exists() for run_dir in run_dirs))
            tui_summary = (out / "codex-tui-summary.md").read_text(encoding="utf-8")
            self.assertIn("Updated Plan", tui_summary)
            self.assertIn("Evidence:", tui_summary)
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertIn("repo_states", manifest)
            self.assertEqual(
                manifest["task_manifest"],
                str((ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv").resolve()),
            )
            self.assertEqual(len(manifest["task_ids"]), 2)
            self.assertTrue(manifest["fresh_session_per_run"])
            route_comparisons = json.loads((out / "route-comparisons.json").read_text(encoding="utf-8"))
            self.assertEqual(len(route_comparisons), 2)
            self.assertEqual(route_comparisons[0]["baseline_profile"], "A-search-only")
            self.assertEqual(route_comparisons[0]["treatment_profile"], "D-full-router")
            claim_readiness = json.loads((out / "route-claim-readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(claim_readiness["paired_comparisons"], 2)
            filtered = write_report(
                runs_jsonl=out / "runs.jsonl",
                out_dir=out / "filtered",
                filters={"profile": "D-full-router"},
                dry_run=True,
            )
            self.assertEqual(filtered["runs"], 2)
            repeat_filtered = write_report(
                runs_jsonl=out / "runs.jsonl",
                out_dir=out / "repeat-filtered",
                filters={"repeat_index": "0", "tool_evidence_source": "self_report"},
                dry_run=True,
            )
            self.assertEqual(repeat_filtered["runs"], 4)

    def test_dry_run_schedules_ios_high_fanout_task_for_all_four_arms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "ios-tasks.tsv"
            write_ios_high_fanout_task(tasks)
            out = root / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(IOS_FIXTURE),
                        "--repo-map",
                        f"sample_ios={IOS_FIXTURE}",
                        "--tasks",
                        str(tasks),
                        "--arms",
                        "A-search-only,B-search-summary,C-lsp-naive,D-full-router",
                        "--repeats",
                        "1",
                        "--no-randomize-order",
                        "--out",
                        str(out),
                    ]
                )

            self.assertEqual(code, 0)
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["task_ids"], ["ios_resolver_fanout"])
            self.assertEqual(manifest["planned_new_runs"], 4)
            self.assertEqual(
                manifest["arms"],
                ["A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"],
            )
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({row["profile"] for row in rows}, set(manifest["arms"]))
            self.assertTrue(all(Path(row["repo_path"]).resolve() == IOS_FIXTURE.resolve() for row in rows))

            expected = {
                "A-search-only": (50000, False, True),
                "B-search-summary": (12000, True, True),
                "C-lsp-naive": (50000, False, False),
                "D-full-router": (12000, True, False),
            }
            for row in rows:
                with self.subTest(profile=row["profile"]):
                    budget, requires_summary_first, search_only_isolated = expected[row["profile"]]
                    run_dir = Path(row["run_dir"])
                    packet = (run_dir / "task-packet.md").read_text(encoding="utf-8")
                    isolation = json.loads((run_dir / "route-isolation.json").read_text(encoding="utf-8"))
                    self.assertIn(f"Maximum raw output bytes: {budget}", packet)
                    self.assertIn(IOS_HIGH_FANOUT_PROMPT, packet)
                    if requires_summary_first:
                        self.assertIn("First produce grouped counts only", packet)
                        self.assertIn("A file read before grouped evidence is a benchmark failure", packet)
                        self.assertNotIn("controlled high-fanout baseline", packet)
                    else:
                        self.assertIn("controlled high-fanout baseline", packet)
                        self.assertIn("A summary-first command is not required in this arm", packet)
                        self.assertNotIn("First produce grouped counts only", packet)
                    if search_only_isolated:
                        self.assertEqual(isolation["mode"], "config")
                        self.assertEqual(isolation["env"].get("RARB_SEMANTIC_TOOLS_DISABLED"), "1")
                        self.assertIn("codex_empty_mcp_servers_config", isolation["hard_controls"])
                        self.assertIn("mcp_servers={}", isolation["args"])
                    else:
                        self.assertEqual(isolation["mode"], "prompt-plus-env")
                        self.assertNotIn("RARB_SEMANTIC_TOOLS_DISABLED", isolation["env"])
                        self.assertNotIn("codex_empty_mcp_servers_config", isolation["hard_controls"])
                        self.assertNotIn("mcp_servers={}", isolation["args"])

    def test_requires_explicit_mode(self) -> None:
        with self.assertRaises(SystemExit) as context:
            main(["--agent", "codex", "--repo", str(ROOT)])
        self.assertIn("choose exactly one", str(context.exception))

    def test_dry_run_accepts_multiple_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agents",
                        "codex,claude-code,cursor-agent",
                        "--repo",
                        str(ROOT),
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--out",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in (Path(tmp) / "runs.jsonl").read_text().splitlines()]
            self.assertEqual({row["agent"] for row in rows}, {"codex", "claude-code", "cursor-agent"})

    def test_repo_map_drives_task_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(ROOT),
                        "--repo-map",
                        f"sample_b2b_android={ROOT}",
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--out",
                        tmp,
                    ]
                )
            self.assertEqual(code, 0)
            row = json.loads((Path(tmp) / "runs.jsonl").read_text().splitlines()[0])
            self.assertEqual(row["repo_path"], str(ROOT.resolve()))

    def test_live_requires_explicit_mapping_for_named_task_repos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = Path(tmp) / "tasks.tsv"
            write_one_task(tasks)
            with self.assertRaises(SystemExit) as context:
                main(
                    [
                        "--live",
                        "--agent",
                        "codex",
                        "--repo",
                        str(ROOT),
                        "--tasks",
                        str(tasks),
                        "--arms",
                        "A-search-only",
                        "--out",
                        str(Path(tmp) / "out"),
                    ]
                )
        self.assertIn("explicit --repo-map entries", str(context.exception))
        self.assertIn("sample", str(context.exception))

    def test_live_repo_map_validation_happens_before_command_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tasks = Path(tmp) / "tasks.tsv"
            write_one_task(tasks)
            with mock.patch("scripts.benchmarks.run_real_agent_benchmark.shutil.which", return_value=None):
                with self.assertRaises(SystemExit) as context:
                    main(
                        [
                            "--live",
                            "--agent",
                            "codex",
                            "--repo",
                            str(ROOT),
                            "--tasks",
                            str(tasks),
                            "--arms",
                            "A-search-only",
                            "--out",
                            str(Path(tmp) / "out"),
                        ]
                    )
        self.assertIn("explicit --repo-map entries", str(context.exception))
        self.assertNotIn("installed command", str(context.exception))

    def test_live_full_router_records_serena_readiness(self) -> None:
        class FakeBridge:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def launch_plan(self):
                return LaunchPlan(
                    agent_id="codex",
                    command=["codex", "exec"],
                    cwd=str(ROOT),
                    prompt_mode="stdin",
                    telemetry_sources=[],
                    supports_live=True,
                    terminal_mode="subprocess",
                    env={},
                )

            def run_prompt(self, *, run_id, prompt, out_dir, timeout_seconds, sentinel, **kwargs):
                transcript = (
                    "BENCHMARK_RESULT\n"
                    "status: blocked\n"
                    "confidence: high\n"
                    "tools_used:\n"
                    "  - Serena preflight\n"
                    "proof_layers:\n"
                    "  semantic_identity: not used\n"
                    "  references: not used\n"
                    "  runtime: not run\n"
                    "files_opened:\n"
                    "  count: 0\n"
                    "  paths:\n"
                    "raw_dump_incidents:\n"
                    "  count: 0\n"
                    "tool_outputs:\n"
                    "  Serena readiness failed.\n"
                    "policy_adherence: pass\n"
                    "final_answer:\n"
                    "  blocked by Serena readiness\n"
                    f"{sentinel}\n"
                )
                (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
                (out_dir / "telemetry.jsonl").write_text("", encoding="utf-8")
                (out_dir / "final-answer.txt").write_text(transcript, encoding="utf-8")
                (out_dir / "metrics.normalized.json").write_text(
                    json.dumps(
                        {
                            "token_source": "proxy",
                            "model_visible_proxy_tokens": 10,
                            "model_visible_bytes": 40,
                            "raw_dump_incidents": 0,
                            "raw_output_bytes": 0,
                            "tool_output_bytes": 0,
                            "tool_evidence_source": "observed",
                            "observed_tools": ["serena/readiness"],
                            "observed_task_tools": ["serena/readiness"],
                            "observed_tool_events": [],
                        }
                    ),
                    encoding="utf-8",
                )
                return BridgeRunResult(
                    run_id=run_id,
                    completion_reason="sentinel_seen",
                    wall_seconds=0.1,
                    transcript_path=str(out_dir / "transcript.txt"),
                    telemetry_path=str(out_dir / "telemetry.jsonl"),
                    metrics_path=str(out_dir / "metrics.normalized.json"),
                    final_answer_path=str(out_dir / "final-answer.txt"),
                )

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            make_git_repo(repo)
            source = repo / "app/src/main/java/com/example/RandomRealViewModel.kt"
            source.parent.mkdir(parents=True)
            source.write_text("package com.example\n\nclass RandomRealViewModel\n", encoding="utf-8")
            tasks = Path(tmp) / "tasks.tsv"
            write_full_router_task(tasks)
            def readiness_side_effect(**kwargs):
                return SerenaReadiness(
                    status="fail",
                    ready=False,
                    created_at="2026-06-01T00:00:00Z",
                    repo=str(repo),
                    symbol="SampleFeatureViewModel",
                    source_file="",
                    command=["serena", "project", "index-file"],
                    returncode=1,
                    stdout_tail="",
                    stderr_tail="language server manager is not initialized",
                    process_state=SerenaProcessState(serena_mcp=3, kotlin_lsp=2, json_lsp=0),
                    warnings=["multiple_serena_mcp_processes", "multiple_kotlin_lsp_processes"],
                    reason="language_server_manager_not_initialized",
                    next_action="restart stale Serena sessions",
                    semantic_session_home=str(Path(kwargs["semantic_session_home"]).resolve()),
                    isolated_env_keys=sorted(kwargs["env"]),
                    process_state_after=SerenaProcessState(serena_mcp=0, kotlin_lsp=0, json_lsp=0),
                )

            isolation = RouteIsolation(
                agent_id="codex",
                profile_id="D-full-router",
                command="codex",
                args=[],
                env={},
                mode="prompt-plus-env",
                hard_controls=[],
                weak_controls=[],
                config_files=[],
                observations={},
            )

            with (
                mock.patch.dict("os.environ", {"CODEX_HOME": str(fake_codex_home(Path(tmp)))}),
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.shutil.which", return_value="/usr/bin/codex"),
                mock.patch(
                    "scripts.benchmarks.run_real_agent_benchmark.run_serena_source_symbol_readiness",
                    side_effect=readiness_side_effect,
                ) as readiness_mock,
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.materialize_route_isolation", return_value=isolation),
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.TerminalAgentBridge", FakeBridge),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = main(
                    [
                        "--live",
                        "--agent",
                        "codex",
                        "--repo",
                        str(repo),
                        "--repo-map",
                        f"sample={repo}",
                        "--tasks",
                        str(tasks),
                        "--arms",
                        "D-full-router",
                        "--task-limit",
                        "1",
                        "--allow-dirty",
                        "--isolated-agent-home",
                        "--out",
                        str(Path(tmp) / "out"),
                    ]
                )

            self.assertEqual(code, 0)
            readiness_mock.assert_called_once()
            self.assertEqual(readiness_mock.call_args.kwargs["source_symbol"], "RandomRealViewModel")
            readiness_env = readiness_mock.call_args.kwargs["env"]
            self.assertIsInstance(readiness_env, dict)
            for key in ("RARB_SERENA_SESSION_HOME", "SERENA_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
                self.assertIn(key, readiness_env)
            readiness_session_home = readiness_mock.call_args.kwargs["semantic_session_home"]
            self.assertTrue(Path(readiness_session_home).resolve().is_relative_to((Path(tmp) / "out").resolve()))
            out = Path(tmp) / "out"
            row = json.loads((out / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])
            run_dir = Path(row["run_dir"])
            self.assertEqual(row["dynamic_target_symbol"], "RandomRealViewModel")
            self.assertEqual(row["dynamic_target_source_file"], "./app/src/main/java/com/example/RandomRealViewModel.kt")
            self.assertEqual(row["serena_readiness_status"], "fail")
            self.assertFalse(row["serena_readiness_ready"])
            self.assertEqual(row["serena_readiness_reason"], "language_server_manager_not_initialized")
            self.assertIn("multiple_serena_mcp_processes", row["serena_readiness_warnings"])
            readiness_payload = json.loads((run_dir / "serena-readiness.json").read_text(encoding="utf-8"))
            self.assertEqual(readiness_payload["semantic_session_home"], str(Path(readiness_session_home).resolve()))
            self.assertEqual(readiness_payload["isolated_env_keys"], sorted(readiness_env))
            self.assertEqual(readiness_payload["process_state_after"]["serena_mcp"], 0)
            self.assertEqual(row["serena_process_state_after_readiness"], readiness_payload["process_state_after"])
            self.assertTrue((run_dir / "dynamic-task-target.json").exists())
            self.assertIn("Ready: false", (run_dir / "task-packet.md").read_text(encoding="utf-8"))
            self.assertIn("Find RandomRealViewModel", (run_dir / "task-packet.md").read_text(encoding="utf-8"))

    def test_dynamic_task_uses_materialized_expected_success_signal_for_judging(self) -> None:
        class FakeBridge:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def launch_plan(self):
                return LaunchPlan(
                    agent_id="codex",
                    command=["codex", "exec"],
                    cwd=str(ROOT),
                    prompt_mode="stdin",
                    telemetry_sources=[],
                    supports_live=True,
                    terminal_mode="subprocess",
                    env={},
                )

            def run_prompt(self, *, run_id, prompt, out_dir, timeout_seconds, sentinel, **kwargs):
                symbol = "RandomRealViewModel" if "RandomRealViewModel" in prompt else "SampleFeatureViewModel"
                transcript = (
                    "BENCHMARK_RESULT\n"
                    "status: pass\n"
                    "confidence: high\n"
                    "tools_used:\n"
                    "  - rg\n"
                    "proof_layers:\n"
                    "  semantic_identity: search-only evidence\n"
                    "  references: not used\n"
                    "  runtime: not run\n"
                    "files_opened:\n"
                    "  count: 1\n"
                    "  paths:\n"
                    "  - app/src/main/java/com/example/RandomRealViewModel.kt\n"
                    "raw_dump_incidents:\n"
                    "  count: 0\n"
                    "tool_outputs:\n"
                    "  short declaration lookup only\n"
                    "policy_adherence: pass\n"
                    "final_answer:\n"
                    f"  {symbol} definition reported in app/src/main/java/com/example/RandomRealViewModel.kt using search-only evidence.\n"
                    f"{sentinel}\n"
                )
                (out_dir / "transcript.txt").write_text(transcript, encoding="utf-8")
                (out_dir / "telemetry.jsonl").write_text("", encoding="utf-8")
                (out_dir / "agent_final_answer.md").write_text(transcript, encoding="utf-8")
                (out_dir / "metrics.normalized.json").write_text(
                    json.dumps(
                        {
                            "token_source": "proxy",
                            "model_visible_proxy_tokens": 10,
                            "model_visible_bytes": 40,
                            "raw_dump_incidents": 0,
                            "raw_output_bytes": 0,
                            "tool_output_bytes": 0,
                            "tool_evidence_source": "observed",
                            "observed_tools": ["rg"],
                            "observed_task_tools": ["rg"],
                            "observed_tool_events": [],
                            "search_count": 1,
                        }
                    ),
                    encoding="utf-8",
                )
                return BridgeRunResult(
                    run_id=run_id,
                    completion_reason="sentinel_seen",
                    wall_seconds=0.1,
                    transcript_path=str(out_dir / "transcript.txt"),
                    telemetry_path=str(out_dir / "telemetry.jsonl"),
                    metrics_path=str(out_dir / "metrics.normalized.json"),
                    final_answer_path=str(out_dir / "agent_final_answer.md"),
                )

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            make_git_repo(repo)
            source = repo / "app/src/main/java/com/example/RandomRealViewModel.kt"
            source.parent.mkdir(parents=True)
            source.write_text("package com.example\n\nclass RandomRealViewModel\n", encoding="utf-8")
            tasks = Path(tmp) / "tasks.tsv"
            write_symbol_task(tasks, profile="A-search-only")
            isolation = RouteIsolation(
                agent_id="codex",
                profile_id="A-search-only",
                command="codex",
                args=[],
                env={},
                mode="config",
                hard_controls=["test"],
                weak_controls=[],
                config_files=[],
                observations={},
            )

            with (
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.shutil.which", return_value="/usr/bin/codex"),
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.materialize_route_isolation", return_value=isolation),
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.TerminalAgentBridge", FakeBridge),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code = main(
                    [
                        "--live",
                        "--agent",
                        "codex",
                        "--repo",
                        str(repo),
                        "--repo-map",
                        f"sample={repo}",
                        "--tasks",
                        str(tasks),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--allow-dirty",
                        "--out",
                        str(Path(tmp) / "out"),
                    ]
                )

            self.assertEqual(code, 0)
            out = Path(tmp) / "out"
            row = json.loads((out / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["dynamic_target_symbol"], "RandomRealViewModel")
            self.assertEqual(row["expected_success_signal"], "RandomRealViewModel definition reported")
            self.assertEqual(row["correctness_status"], "pass")
            self.assertEqual(row["serena_readiness_status"], "")

    def test_live_full_router_can_require_clean_serena_process_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            make_git_repo(repo)
            source = repo / "app/src/main/java/com/example/AnotherRealViewModel.kt"
            source.parent.mkdir(parents=True)
            source.write_text("package com.example\n\nclass AnotherRealViewModel\n", encoding="utf-8")
            tasks = Path(tmp) / "tasks.tsv"
            write_full_router_task(tasks)
            readiness = SerenaReadiness(
                status="pass",
                ready=True,
                created_at="2026-06-01T00:00:00Z",
                repo=str(repo),
                symbol="AnotherRealViewModel",
                source_file="./app/src/main/java/com/example/AnotherRealViewModel.kt",
                command=["serena", "project", "index-file"],
                returncode=0,
                stdout_tail="- AnotherRealViewModel at line 3 of kind 5",
                stderr_tail="",
                process_state=SerenaProcessState(serena_mcp=2, kotlin_lsp=2, json_lsp=0),
                warnings=["multiple_serena_mcp_processes", "multiple_kotlin_lsp_processes"],
                reason="",
                next_action="ready",
            )

            out = Path(tmp) / "out"
            with (
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.shutil.which", return_value="/usr/bin/codex"),
                mock.patch(
                    "scripts.benchmarks.run_real_agent_benchmark.run_serena_source_symbol_readiness",
                    return_value=readiness,
                ),
                mock.patch(
                    "scripts.benchmarks.run_real_agent_benchmark.capture_serena_process_state",
                    return_value=SerenaProcessState(serena_mcp=0, kotlin_lsp=0, json_lsp=0),
                ),
                mock.patch("scripts.benchmarks.run_real_agent_benchmark.TerminalAgentBridge") as bridge_mock,
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaises(SystemExit) as context,
            ):
                main(
                    [
                        "--live",
                        "--agent",
                        "codex",
                        "--repo",
                        str(repo),
                        "--repo-map",
                        f"sample={repo}",
                        "--tasks",
                        str(tasks),
                        "--arms",
                        "D-full-router",
                        "--task-limit",
                        "1",
                        "--allow-dirty",
                        "--require-clean-serena-process-state",
                        "--out",
                        str(out),
                    ]
                )

            self.assertIn("Serena process state is not clean", str(context.exception))
            self.assertIn("multiple_serena_mcp_processes", str(context.exception))
            bridge_mock.assert_not_called()
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["require_clean_serena_process_state"])
            run_dirs = [path for path in out.iterdir() if path.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            self.assertTrue((run_dirs[0] / "serena-readiness.json").exists())
            self.assertFalse((out / "runs.jsonl").exists())

    def test_clean_out_rejects_repo_root(self) -> None:
        with self.assertRaises(SystemExit) as context:
            main(
                [
                    "--dry-run",
                    "--agent",
                    "codex",
                    "--repo",
                    str(ROOT),
                    "--tasks",
                    str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                    "--arms",
                    "A-search-only",
                    "--task-limit",
                    "1",
                    "--out",
                    str(ROOT),
                    "--clean-out",
                ]
            )
        self.assertIn("--clean-out is only allowed", str(context.exception))

    def test_clean_out_allows_temp_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "benchmark-output"
            out.mkdir()
            (out / "stale.txt").write_text("old", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(ROOT),
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--out",
                        str(out),
                        "--clean-out",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertFalse((out / "stale.txt").exists())

    def test_snapshot_repos_uses_clean_detached_worktree_for_dirty_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            make_git_repo(source)
            (source / "README.md").write_text("dirty\n", encoding="utf-8")
            tasks = root / "tasks.tsv"
            write_one_task(tasks)
            out = root / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(source),
                        "--repo-map",
                        f"sample={source}",
                        "--tasks",
                        str(tasks),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--snapshot-repos",
                        "--out",
                        str(out),
                    ]
                )
            self.assertEqual(code, 0)
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["source_repo_states"]["default"]["dirty"])
            self.assertFalse(manifest["repo_states"]["default"]["dirty"])
            self.assertTrue(manifest["snapshot_repos"])
            row = json.loads((out / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("_repo-snapshots", row["repo_path"])

    def test_resume_from_carries_existing_cells_and_runs_only_missing_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous"
            previous.mkdir()
            existing_row = {
                "run_id": "previous-codex",
                "repeat_index": 0,
                "agent": "codex",
                "profile": "A-search-only",
                "task_id": "known_symbol_definition",
                "task_family": "known_kotlin_symbol_definition",
                "repo": "sample_b2b_android",
                "repo_path": str(ROOT),
                "run_dir": str(previous / "previous-codex"),
                "completion_reason": "sentinel",
                "wall_seconds": 1,
                "correctness_status": "pass",
                "policy_adherence": "pass",
                "policy_violations": [],
                "token_source": "exact",
                "tool_evidence_source": "observed",
                "route_isolation_mode": "config",
                "route_hard_controls": ["test"],
                "route_weak_controls": [],
                "model_visible_proxy_tokens": 10,
            }
            write_minimal_run_artifacts(previous / "previous-codex")
            (previous / "runs.jsonl").write_text(json.dumps(existing_row) + "\n", encoding="utf-8")
            out = root / "resumed"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agents",
                        "codex,cursor-agent",
                        "--repo",
                        str(ROOT),
                        "--repo-map",
                        f"sample_b2b_android={ROOT}",
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--repeats",
                        "1",
                        "--resume-from",
                        str(previous),
                        "--out",
                        str(out),
                    ]
                )

            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["run_id"], "previous-codex")
            self.assertEqual(Path(rows[0]["run_dir"]).resolve(), (out / "previous-codex").resolve())
            self.assertEqual(Path(rows[0]["repo_path"]).resolve(), ROOT.resolve())
            self.assertEqual(rows[0]["carried_forward_from_run_dir"], str((previous / "previous-codex").resolve()))
            self.assertTrue(rows[0]["carried_forward_artifacts_imported"])
            self.assertTrue((out / "previous-codex" / "telemetry.jsonl").exists())
            self.assertEqual({(row["agent"], row["profile"]) for row in rows}, {("codex", "A-search-only"), ("cursor-agent", "A-search-only")})
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["carried_forward_runs"], 1)
            self.assertEqual(manifest["planned_new_runs"], 1)
            self.assertEqual(manifest["resumed_from"], str(previous.resolve()))
            self.assertEqual(manifest["missing_artifact_carried_forward_runs"], 0)

    def test_resume_from_reruns_passed_rows_when_carried_artifacts_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous"
            previous.mkdir()
            (previous / "run-manifest.json").write_text(
                json.dumps({"repo_map": {"sample_b2b_android": str(ROOT)}}),
                encoding="utf-8",
            )
            existing_row = {
                "run_id": "previous-missing-artifacts",
                "repeat_index": 0,
                "agent": "codex",
                "profile": "A-search-only",
                "task_id": "known_symbol_definition",
                "task_family": "known_kotlin_symbol_definition",
                "repo": "sample_b2b_android",
                "repo_path": str(ROOT),
                "run_dir": str(previous / "previous-missing-artifacts"),
                "completion_reason": "sentinel",
                "wall_seconds": 1,
                "correctness_status": "pass",
                "policy_adherence": "pass",
                "policy_violations": [],
                "token_source": "exact",
                "tool_evidence_source": "observed",
                "route_isolation_mode": "config",
                "route_hard_controls": ["test"],
                "route_weak_controls": [],
                "model_visible_proxy_tokens": 10,
            }
            (previous / "runs.jsonl").write_text(json.dumps(existing_row) + "\n", encoding="utf-8")
            out = root / "resumed"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(ROOT),
                        "--repo-map",
                        f"sample_b2b_android={ROOT}",
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--repeats",
                        "1",
                        "--resume-from",
                        str(previous),
                        "--out",
                        str(out),
                    ]
                )

            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertNotEqual(rows[0]["run_id"], "previous-missing-artifacts")
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["carried_forward_runs"], 0)
            self.assertEqual(manifest["missing_artifact_carried_forward_runs"], 1)
            self.assertEqual(manifest["planned_new_runs"], 1)

    def test_resume_from_drops_rows_with_unmapped_named_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous"
            previous.mkdir()
            to_manifest = {
                "repo_map": {"sample_b2b_android": str(ROOT)},
            }
            (previous / "run-manifest.json").write_text(json.dumps(to_manifest), encoding="utf-8")
            existing_row = {
                "run_id": "previous-invalid-retail",
                "repeat_index": 0,
                "agent": "cursor-agent",
                "profile": "A-search-only",
                "task_id": "sample_task",
                "task_family": "known_kotlin_symbol_definition",
                "repo": "sample_retail_android",
                "repo_path": str(ROOT),
                "run_dir": str(previous / "previous-invalid-retail"),
                "completion_reason": "sentinel",
                "wall_seconds": 1,
                "correctness_status": "pass",
                "policy_adherence": "pass",
                "policy_violations": [],
                "token_source": "exact",
                "tool_evidence_source": "observed",
                "route_isolation_mode": "config",
                "route_hard_controls": ["test"],
                "route_weak_controls": [],
                "model_visible_proxy_tokens": 10,
            }
            (previous / "runs.jsonl").write_text(json.dumps(existing_row) + "\n", encoding="utf-8")
            tasks = root / "tasks.tsv"
            tasks.write_text(
                "task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds\n"
                "sample_task\tknown_kotlin_symbol_definition\tsample_retail_android\tFind CartViewModel\tA-search-only\tfalse\tfalse\tsemantic_identity_or_search_labeled\tCartViewModel definition reported\tDo not claim runtime behavior.\t900\n",
                encoding="utf-8",
            )
            out = root / "resumed"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "cursor-agent",
                        "--repo",
                        str(ROOT),
                        "--repo-map",
                        f"sample_retail_android={ROOT}",
                        "--tasks",
                        str(tasks),
                        "--arms",
                        "A-search-only",
                        "--repeats",
                        "1",
                        "--resume-from",
                        str(previous),
                        "--out",
                        str(out),
                    ]
                )

            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertNotEqual(rows[0]["run_id"], "previous-invalid-retail")
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["invalid_carried_forward_runs"], 1)
            self.assertEqual(manifest["planned_new_runs"], 1)

    def test_resume_from_can_rerun_failed_or_policy_violating_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = root / "previous"
            previous.mkdir()
            (previous / "run-manifest.json").write_text(
                json.dumps({"repo_map": {"sample_b2b_android": str(ROOT)}}),
                encoding="utf-8",
            )
            existing_row = {
                "run_id": "previous-failed",
                "repeat_index": 0,
                "agent": "codex",
                "profile": "A-search-only",
                "task_id": "known_symbol_definition",
                "task_family": "known_kotlin_symbol_definition",
                "repo": "sample_b2b_android",
                "repo_path": str(ROOT),
                "run_dir": str(previous / "previous-failed"),
                "completion_reason": "sentinel",
                "wall_seconds": 1,
                "correctness_status": "fail",
                "policy_adherence": "pass",
                "policy_violations": ["raw_dump_incident"],
                "token_source": "exact",
                "tool_evidence_source": "observed",
                "route_isolation_mode": "config",
                "route_hard_controls": ["test"],
                "route_weak_controls": [],
                "model_visible_proxy_tokens": 10,
            }
            (previous / "runs.jsonl").write_text(json.dumps(existing_row) + "\n", encoding="utf-8")
            out = root / "resumed"
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(ROOT),
                        "--repo-map",
                        f"sample_b2b_android={ROOT}",
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--repeats",
                        "1",
                        "--resume-from",
                        str(previous),
                        "--rerun-failed",
                        "--out",
                        str(out),
                    ]
                )

            self.assertEqual(code, 0)
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertNotEqual(rows[0]["run_id"], "previous-failed")
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["rerun_failed"])
            self.assertEqual(manifest["rerun_carried_forward_runs"], 1)
            self.assertEqual(manifest["planned_new_runs"], 1)

    def test_resume_from_rejects_same_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "runs.jsonl").write_text("", encoding="utf-8")
            with self.assertRaises(SystemExit) as context:
                main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(ROOT),
                        "--tasks",
                        str(ROOT / "benchmarks/real-agent-routing/tasks/android-realworld.sample.tsv"),
                        "--arms",
                        "A-search-only",
                        "--task-limit",
                        "1",
                        "--resume-from",
                        str(out),
                        "--out",
                        str(out),
                    ]
                )
            self.assertIn("different directory", str(context.exception))


if __name__ == "__main__":
    unittest.main()
