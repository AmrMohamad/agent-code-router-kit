from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.benchmarks.audit_real_agent_study import audit
from scripts.benchmarks.analyze_real_agent_study import analyze
from scripts.benchmarks.build_public_study_evidence import build_public_bundle
from scripts.benchmarks.run_real_agent_benchmark import main
from scripts.lib.agent_session import AgentProfile, load_route_profile
from scripts.lib.experiment_design import balanced_latin_square
from scripts.lib.hermetic_agent_environment import materialize_hermetic_agent_environment
from scripts.lib.route_isolation import materialize_route_isolation
from scripts.lib.treatment_config import diff_effective_agent_configs


ROOT = Path(__file__).resolve().parents[2]


def codex_profile() -> AgentProfile:
    return AgentProfile(
        agent_id="codex",
        display_name="Codex CLI",
        command="codex",
        fallback_commands=[],
        args=["exec", "--sandbox", "read-only", "--ephemeral", "--json", "-"],
        env={},
        prompt_mode="stdin",
        telemetry_sources=["codex_otel_if_enabled", "transcript_proxy"],
        supports_live=True,
        default_timeout_seconds=900,
        terminal_mode="pty",
    )


def make_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("sample\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def write_study_task(path: Path) -> None:
    path.write_text(
        "task_id\ttask_family\trepo\tprompt\troute_profiles\tedit_allowed\tbuild_allowed\texpected_proof_layer\texpected_success_signal\tforbidden_claims\ttimeout_seconds\n"
        "study_task\tknown_symbol_definition\tsample\tFind the sample declaration and report route-appropriate evidence.\tA-search-only,B-search-summary,C-lsp-naive,D-full-router\tfalse\tfalse\tsemantic_identity_or_search_labeled\tdeclaration reported\tDo not claim runtime behavior.\t900\n",
        encoding="utf-8",
    )


def write_permissive_oracle(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "oracles": [
                    {
                        "task_id": "study_task",
                        "oracle_id": "study-task-smoke",
                        "type": "text_checks",
                        "required_terms": [],
                        "requires_policy_pass": False,
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def fake_codex_home(path: Path) -> Path:
    home = path / "fake-codex-home"
    home.mkdir()
    (home / "auth.json").write_text('{"mode":"test"}\n', encoding="utf-8")
    return home


class RouterEffectStudyTests(unittest.TestCase):
    def test_balanced_latin_square_places_each_arm_once_per_position(self) -> None:
        arms = ["A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"]
        square = balanced_latin_square(arms)

        self.assertEqual(len(square), 4)
        for sequence in square:
            self.assertEqual(sorted(sequence), sorted(arms))
        for arm in arms:
            positions = [sequence.index(arm) + 1 for sequence in square]
            self.assertEqual(sorted(positions), [1, 2, 3, 4])

    def test_hermetic_codex_config_diff_limits_a_to_d_to_treatment_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            run_a = root / "run-a"
            run_d = root / "run-d"
            profile_a = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/A-search-only.yaml")
            profile_d = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/D-full-router.yaml")

            env_a = materialize_hermetic_agent_environment(
                agent_profile=codex_profile(),
                route_profile=profile_a,
                run_dir=run_a,
                repo_path=repo,
                model_id="codex-test-model",
                reasoning_effort="low",
                sandbox="read-only",
                timeout_seconds=900,
                response_contract="contract-hash",
            )
            env_d = materialize_hermetic_agent_environment(
                agent_profile=codex_profile(),
                route_profile=profile_d,
                run_dir=run_d,
                repo_path=repo,
                model_id="codex-test-model",
                reasoning_effort="low",
                sandbox="read-only",
                timeout_seconds=900,
                response_contract="contract-hash",
            )

            self.assertFalse(env_a.semantic_access_enabled)
            self.assertTrue(env_d.semantic_access_enabled)
            diff = diff_effective_agent_configs(
                env_a.effective_config,
                env_d.effective_config,
                left_profile_id="A-search-only",
                right_profile_id="D-full-router",
            )
            self.assertTrue(diff["valid"], diff)

    def test_hermetic_route_isolation_applies_codex_hard_controls_to_all_arms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            profile = load_route_profile(ROOT / "benchmarks/real-agent-routing/profiles/D-full-router.yaml")
            with patch.dict("os.environ", {"CODEX_HOME": str(fake_codex_home(root))}):
                hermetic = materialize_hermetic_agent_environment(
                    agent_profile=codex_profile(),
                    route_profile=profile,
                    run_dir=root / "run",
                    repo_path=repo,
                    model_id="codex-test-model",
                    reasoning_effort="low",
                    sandbox="read-only",
                    timeout_seconds=900,
                    response_contract="contract-hash",
                )
            with patch("scripts.lib.route_isolation.shutil.which", return_value="/bin/codex"):
                isolation = materialize_route_isolation(
                    agent_profile=codex_profile(),
                    route_profile=profile,
                    run_dir=root / "run",
                    workspace_cwd=repo,
                    hermetic_environment=hermetic,
                )

            self.assertIn("--ignore-user-config", isolation.args)
            self.assertIn("--ignore-rules", isolation.args)
            self.assertIn("plugins", isolation.args)
            self.assertIn("codex_fresh_home", isolation.hard_controls)
            self.assertIn("codex_controlled_mcp_servers", isolation.hard_controls)
            self.assertIn("effective_agent_config_sha256", isolation.observations)
            self.assertEqual(isolation.weak_controls, [])

    def test_study_dry_run_creates_balanced_snapshot_matrix_and_passes_study_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            make_git_repo(repo)
            tasks = root / "tasks.tsv"
            oracles = root / "oracles.json"
            out = root / "out"
            write_study_task(tasks)
            write_permissive_oracle(oracles)

            stdout = io.StringIO()
            env = {
                "CODEX_HOME": str(fake_codex_home(root)),
                "RARB_PRIVATE_HMAC_KEY": "test-hmac-key",
            }
            with contextlib.redirect_stdout(stdout), patch.dict("os.environ", env):
                code = main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(repo),
                        "--repo-map",
                        f"sample={repo}",
                        "--tasks",
                        str(tasks),
                        "--task-oracles",
                        str(oracles),
                        "--study-plan",
                        str(ROOT / "benchmarks/real-agent-routing/studies/router-effect-v1/study.yaml"),
                        "--arms",
                        "A-search-only,B-search-summary,C-lsp-naive,D-full-router",
                        "--repeats",
                        "4",
                        "--snapshot-repos",
                        "--model-id",
                        "codex-test-model",
                        "--reasoning-effort",
                        "low",
                        "--out",
                        str(out),
                    ]
                )

            self.assertEqual(code, 0, stdout.getvalue())
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 16)
            self.assertEqual({row["profile"] for row in rows}, {"A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"})
            for profile in {"A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"}:
                positions = sorted(row["sequence_position"] for row in rows if row["profile"] == profile)
                self.assertEqual(positions, [1, 2, 3, 4])
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["snapshot_repos"])
            self.assertTrue(manifest["isolated_agent_home"])
            self.assertEqual(manifest["order_design"], "balanced-latin-square")
            self.assertEqual(audit(out)["status"], "pass")

            manifest["live"] = True
            (out / "run-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            failed_audit = audit(out)
            self.assertEqual(failed_audit["status"], "fail")
            self.assertIn("exact_uncached_input_tokens", {issue["code"] for issue in failed_audit["issues"]})

    def test_study_analysis_and_public_bundle_are_anonymized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            make_git_repo(repo)
            tasks = root / "tasks.tsv"
            oracles = root / "oracles.json"
            out = root / "out"
            public = root / "public"
            write_study_task(tasks)
            write_permissive_oracle(oracles)

            env = {
                "CODEX_HOME": str(fake_codex_home(root)),
                "RARB_PRIVATE_HMAC_KEY": "test-hmac-key",
            }
            with contextlib.redirect_stdout(io.StringIO()), patch.dict("os.environ", env):
                main(
                    [
                        "--dry-run",
                        "--agent",
                        "codex",
                        "--repo",
                        str(repo),
                        "--repo-map",
                        f"sample={repo}",
                        "--tasks",
                        str(tasks),
                        "--task-oracles",
                        str(oracles),
                        "--study-plan",
                        str(ROOT / "benchmarks/real-agent-routing/studies/router-effect-v1/study.yaml"),
                        "--arms",
                        "A-search-only,B-search-summary,C-lsp-naive,D-full-router",
                        "--repeats",
                        "4",
                        "--snapshot-repos",
                        "--model-id",
                        "codex-test-model",
                        "--reasoning-effort",
                        "low",
                        "--out",
                        str(out),
                    ]
                )

            analysis = analyze(out, metric="model_visible_proxy_tokens")
            self.assertIn("factorial_effects", analysis)
            self.assertIn("cluster_bootstrap_95ci_percent", analysis["pairwise_effects"]["A-search-only_to_D-full-router"])
            (out / "study-analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = build_public_bundle(root=out, out=public)
            self.assertTrue((public / "analysis.sanitized.json").exists())
            self.assertTrue((public / "audit.sanitized.json").exists())
            public_text = (public / "runs.sanitized.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("study_task", public_text)
            self.assertNotIn("sample", public_text)
            self.assertNotIn(str(repo), public_text)
            public_rows = [json.loads(line) for line in public_text.splitlines()]
            self.assertEqual(public_rows[0]["task_public_id"], "task_001")
            self.assertEqual(public_rows[0]["repo_public_id"], "repo_001")
            self.assertNotIn("task_id", public_rows[0])
            self.assertNotIn("repo", public_rows[0])
            manifest = json.loads((public / "manifest.sanitized.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["privacy"]["private_task_ids_removed"])
            self.assertTrue(manifest["privacy"]["private_repo_ids_removed"])
            self.assertIn("manifest.sanitized.json", result["artifact_hashes"])

    def test_study_mode_requires_private_hmac_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            make_git_repo(repo)
            tasks = root / "tasks.tsv"
            write_study_task(tasks)

            with patch.dict("os.environ", {"RARB_PRIVATE_HMAC_KEY": ""}):
                with self.assertRaises(SystemExit) as caught:
                    main(
                        [
                            "--dry-run",
                            "--agent",
                            "codex",
                            "--repo",
                            str(repo),
                            "--repo-map",
                            f"sample={repo}",
                            "--tasks",
                            str(tasks),
                            "--study-plan",
                            str(ROOT / "benchmarks/real-agent-routing/studies/router-effect-v1/study.yaml"),
                            "--arms",
                            "A-search-only,B-search-summary,C-lsp-naive,D-full-router",
                            "--repeats",
                            "4",
                            "--snapshot-repos",
                            "--model-id",
                            "codex-test-model",
                            "--reasoning-effort",
                            "low",
                            "--out",
                            str(root / "out"),
                        ]
                    )

            self.assertIn("requires $RARB_PRIVATE_HMAC_KEY", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
