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
from scripts.benchmarks.estimate_study_power import estimate
from scripts.benchmarks.run_real_agent_benchmark import main
from scripts.benchmarks.verify_task_oracles import main as verify_task_oracles_main
from scripts.lib.agent_session import AgentProfile, load_route_profile, load_tasks
from scripts.lib.experiment_design import balanced_latin_square
from scripts.lib.hermetic_agent_environment import materialize_hermetic_agent_environment
from scripts.lib.route_isolation import materialize_route_isolation
from scripts.lib.task_oracles import load_task_oracles, validate_task_oracle_plan
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
                        "type": "semantic_identity",
                        "required_terms": [],
                        "required_row_values": {
                            "expected_proof_layer": "semantic_identity_or_search_labeled"
                        },
                        "requires_policy_pass": True,
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


def promote_dry_run_to_synthetic_live_study(out: Path) -> None:
    manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
    manifest["dry_run"] = False
    manifest["live"] = True
    package = dict(manifest.get("study_package", {}))
    package["task_split"] = "confirmatory"
    package["task_oracles_source"] = "study_plan"
    manifest["study_package"] = package
    (out / "run-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    token_values = {
        "A-search-only": 1000,
        "B-search-summary": 850,
        "C-lsp-naive": 900,
        "D-full-router": 700,
    }
    rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    with (out / "runs.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            value = token_values[row["profile"]]
            row.update(
                {
                    "token_source": "exact",
                    "exact_input_tokens": value + 100,
                    "exact_cached_input_tokens": 100,
                    "exact_uncached_input_tokens": value,
                    "exact_output_tokens": 50,
                    "exact_total_tokens": value + 150,
                    "codex_version": "codex-test 1.0",
                    "serena_version": "serena-test 1.0",
                    "os_version": "test-os",
                }
            )
            handle.write(json.dumps(row, sort_keys=True) + "\n")


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
            for row in rows:
                run_dir = Path(row["run_dir"])
                self.assertTrue((run_dir / "semantic-session.json").exists())
                self.assertEqual(row["semantic_session_artifact"], "semantic-session.json")
                self.assertIn("codex_version", row)
                self.assertRegex(row["source_commit"], r"^[0-9a-f]{40,64}$")
                self.assertEqual(row["source_commit"], row["snapshot_commit"])
                self.assertEqual(row["source_tree_hash"], row["snapshot_tree_hash"])
                self.assertEqual(row["source_lockfile_hash"], row["lockfile_hash"])
                self.assertRegex(row["snapshot_state_hmac"], r"^[0-9a-f]{24}$")
                semantic_session = json.loads((run_dir / "semantic-session.json").read_text(encoding="utf-8"))
                if row["semantic_access_enabled"]:
                    self.assertEqual(semantic_session["session_id"], row["run_id"])
                    self.assertEqual(semantic_session["mode"], "codex_mcp_stdio_per_run")
                    self.assertTrue(semantic_session["isolated"])
                    self.assertEqual(semantic_session["transport"], "stdio")
                    self.assertTrue(Path(semantic_session["semantic_session_home"]).is_relative_to(run_dir))
                    self.assertTrue(Path(semantic_session["serena_home"]).is_relative_to(Path(semantic_session["semantic_session_home"])))
                    self.assertTrue(Path(semantic_session["xdg_config_home"]).is_relative_to(Path(semantic_session["semantic_session_home"])))
                    self.assertTrue(Path(semantic_session["xdg_cache_home"]).is_relative_to(Path(semantic_session["semantic_session_home"])))
                    self.assertTrue(Path(semantic_session["xdg_data_home"]).is_relative_to(Path(semantic_session["semantic_session_home"])))
                    self.assertIn("RARB_SERENA_SESSION_HOME", semantic_session["mcp_env_keys"])
                    self.assertIn("SERENA_HOME", semantic_session["mcp_env_keys"])
                    self.assertIn("XDG_CONFIG_HOME", semantic_session["mcp_env_keys"])
                    self.assertIn("XDG_CACHE_HOME", semantic_session["mcp_env_keys"])
                    self.assertIn("XDG_DATA_HOME", semantic_session["mcp_env_keys"])
                    self.assertRegex(row["semantic_session_id_hmac"], r"^[0-9a-f]{24}$")
                    self.assertRegex(row["semantic_project_path_hmac"], r"^[0-9a-f]{24}$")
                else:
                    self.assertEqual(semantic_session["session_id"], "")
                    self.assertEqual(semantic_session["mode"], "disabled")
                    self.assertFalse(semantic_session["mcp_server_configured"])
                    self.assertEqual(row["semantic_session_id_hmac"], "")
            manifest = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["snapshot_repos"])
            self.assertTrue(manifest["isolated_agent_home"])
            self.assertEqual(manifest["order_design"], "balanced-latin-square")
            self.assertEqual(manifest["study_package"]["task_split"], "custom")
            self.assertEqual(manifest["study_package"]["task_oracles_source"], "custom")
            self.assertRegex(manifest["study_package"]["task_manifest_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(manifest["study_package"]["task_manifest_hmac"], r"^[0-9a-f]{24}$")
            self.assertEqual({row["task_manifest_hash"] for row in rows}, {manifest["study_package"]["task_manifest_sha256"]})
            for source_state in manifest["source_repo_states"].values():
                self.assertFalse(source_state["dirty"])
                self.assertRegex(source_state["tree_hash"], r"^[0-9a-f]{40,64}$")
            for snapshot_state in manifest["repo_snapshots"].values():
                self.assertFalse(snapshot_state["snapshot_dirty"])
                self.assertEqual(snapshot_state["source_commit"], snapshot_state["snapshot_commit"])
                self.assertEqual(snapshot_state["source_tree_hash"], snapshot_state["snapshot_tree_hash"])
            self.assertEqual(audit(out)["status"], "pass")
            semantic_row = next(row for row in rows if row["semantic_access_enabled"])
            semantic_path = Path(semantic_row["run_dir"]) / "semantic-session.json"
            semantic_payload = json.loads(semantic_path.read_text(encoding="utf-8"))
            original_session_id = semantic_payload["session_id"]
            semantic_payload["session_id"] = "wrong-session-id"
            semantic_path.write_text(json.dumps(semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            semantic_audit = audit(out)
            self.assertIn("semantic_session_id", {issue["code"] for issue in semantic_audit["issues"]})
            semantic_payload["session_id"] = original_session_id
            semantic_path.write_text(json.dumps(semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            confirmatory_dry_run = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertEqual(confirmatory_dry_run["status"], "fail")
            confirmatory_dry_run_codes = {issue["code"] for issue in confirmatory_dry_run["issues"]}
            self.assertIn("confirmatory_live", confirmatory_dry_run_codes)
            self.assertIn("confirmatory_task_manifest", confirmatory_dry_run_codes)
            self.assertIn("confirmatory_task_oracles", confirmatory_dry_run_codes)

            manifest["live"] = True
            (out / "run-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            failed_audit = audit(out)
            self.assertEqual(failed_audit["status"], "fail")
            self.assertIn("exact_uncached_input_tokens", {issue["code"] for issue in failed_audit["issues"]})

            row_lines = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            row_lines[0]["snapshot_commit"] = "0" * 40
            (out / "runs.jsonl").write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in row_lines),
                encoding="utf-8",
            )
            snapshot_audit = audit(out)
            self.assertIn("source_snapshot_commit_match", {issue["code"] for issue in snapshot_audit["issues"]})

    def test_task_oracle_plan_requires_task_specific_external_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.tsv"
            oracles = root / "oracles.json"
            weak_oracles = root / "weak-oracles.json"
            write_study_task(tasks)
            write_permissive_oracle(oracles)
            weak_oracles.write_text(
                json.dumps(
                    {
                        "oracles": [
                            {
                                "task_family": "known_symbol_definition",
                                "oracle_id": "family-only",
                                "type": "text_checks",
                                "requires_policy_pass": True,
                                "required_terms": ["declaration"],
                            }
                        ]
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            strong_result = validate_task_oracle_plan(
                tasks=load_tasks(tasks),
                oracles=load_task_oracles(oracles),
                require_task_specific=True,
            )
            self.assertEqual(strong_result["status"], "pass", strong_result)
            weak_result = validate_task_oracle_plan(
                tasks=load_tasks(tasks),
                oracles=load_task_oracles(weak_oracles),
                require_task_specific=True,
            )
            self.assertEqual(weak_result["status"], "fail")
            self.assertIn("oracle_not_task_specific", {issue["code"] for issue in weak_result["issues"]})

    def test_verify_task_oracles_cli_supports_plan_and_run_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks = root / "tasks.tsv"
            oracles = root / "oracles.json"
            run_dir = root / "run"
            runs = root / "runs.jsonl"
            out = root / "oracle-summary.json"
            write_study_task(tasks)
            write_permissive_oracle(oracles)
            run_dir.mkdir()
            (run_dir / "transcript.txt").write_text("route evidence\n", encoding="utf-8")
            runs.write_text(
                json.dumps(
                    {
                        "run_id": "run-1",
                        "task_id": "study_task",
                        "task_family": "known_symbol_definition",
                        "profile": "D-full-router",
                        "run_dir": str(run_dir),
                        "policy_adherence": "pass",
                        "expected_proof_layer": "semantic_identity_or_search_labeled",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with contextlib.redirect_stdout(io.StringIO()):
                plan_code = verify_task_oracles_main(
                    [
                        "--tasks",
                        str(tasks),
                        "--oracles",
                        str(oracles),
                        "--require-task-specific",
                    ]
                )
                run_code = verify_task_oracles_main(
                    [
                        "--runs",
                        str(runs),
                        "--oracles",
                        str(oracles),
                        "--out",
                        str(out),
                    ]
                )
            self.assertEqual(plan_code, 0)
            self.assertEqual(run_code, 0)
            summary = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(summary["oracle_pass_count"], 1)

    def test_confirmatory_audit_requires_analysis_power_and_can_pass_synthetic_live_shape(self) -> None:
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

            promote_dry_run_to_synthetic_live_study(out)
            missing_artifacts = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertEqual(missing_artifacts["status"], "fail")
            self.assertIn("study_analysis", {issue["code"] for issue in missing_artifacts["issues"]})
            self.assertIn("study_power", {issue["code"] for issue in missing_artifacts["issues"]})

            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            wrong_analysis = analyze(out, metric="model_visible_proxy_tokens")
            (out / "study-analysis.json").write_text(json.dumps(wrong_analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            wrong_power = estimate(
                rows,
                metric="model_visible_proxy_tokens",
                minimum_effect=0.15,
                floor_repeats=4,
                alpha=0.05,
                power=0.80,
            )
            (out / "study-power.json").write_text(json.dumps(wrong_power, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            wrong_metric = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            wrong_metric_codes = {issue["code"] for issue in wrong_metric["issues"]}
            self.assertIn("study_analysis_metric", wrong_metric_codes)
            self.assertIn("study_power_metric", wrong_metric_codes)

            analysis = analyze(out, metric="exact_uncached_input_tokens")
            self.assertIn("pairwise_effects_by_task_family", analysis)
            self.assertIn("pairwise_effects_by_repo", analysis)
            self.assertIn("pairwise_effects_by_sequence_position", analysis)
            self.assertIn("factorial_effects_by_task_family", analysis)
            self.assertIn("factorial_effects_by_repo", analysis)
            self.assertEqual(analysis["multiple_comparison_correction"]["method"], "holm")
            (out / "study-analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            power = estimate(
                rows,
                metric="exact_uncached_input_tokens",
                minimum_effect=0.15,
                floor_repeats=4,
                alpha=0.05,
                power=0.80,
            )
            self.assertEqual(power["primary_comparison"], "A-search-only_to_D-full-router")
            self.assertEqual(set(power["pairwise_power"]), {
                "A-search-only_to_B-search-summary",
                "A-search-only_to_C-lsp-naive",
                "C-lsp-naive_to_D-full-router",
                "A-search-only_to_D-full-router",
            })
            self.assertTrue(power["all_preregistered_comparisons_power_target_met"])
            self.assertAlmostEqual(power["z_alpha_two_sided"], 1.95996398)
            self.assertAlmostEqual(power["z_power"], 0.84162123)
            malformed_power = dict(power)
            malformed_power.pop("pairwise_power")
            (out / "study-power.json").write_text(json.dumps(malformed_power, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            malformed = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("study_power_shape", {issue["code"] for issue in malformed["issues"]})
            (out / "study-power.json").write_text(json.dumps(power, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            manifest_path = out / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            tainted_manifest = dict(manifest)
            tainted_manifest.update(
                {
                    "rerun_failed": True,
                    "rerun_carried_forward_runs": 1,
                    "rerun_carried_forward_cells": ["codex/A-search-only/study_task/sample/0"],
                    "invalid_carried_forward_runs": 1,
                    "invalid_carried_forward_cells": ["codex/B-search-summary/study_task/sample/0"],
                    "missing_artifact_carried_forward_runs": 1,
                    "missing_artifact_carried_forward_cells": ["codex/C-lsp-naive/study_task/sample/0"],
                }
            )
            manifest_path.write_text(json.dumps(tainted_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            rerun_policy = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            rerun_policy_codes = {issue["code"] for issue in rerun_policy["issues"]}
            self.assertIn("confirmatory_rerun_failed", rerun_policy_codes)
            self.assertIn("confirmatory_rerun_carried_forward", rerun_policy_codes)
            self.assertIn("confirmatory_invalid_carried_forward", rerun_policy_codes)
            self.assertIn("confirmatory_missing_artifact_carried_forward", rerun_policy_codes)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            confirmatory = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertEqual(confirmatory["status"], "pass", confirmatory)

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
            self.assertIn("pairwise_effects_by_repo", analysis)
            self.assertIn("sample", analysis["pairwise_effects_by_repo"]["A-search-only_to_D-full-router"])
            self.assertIn("factorial_effects", analysis)
            self.assertIn("correctness_pairwise", analysis)
            self.assertTrue(analysis["correctness_pairwise"]["A-search-only_to_D-full-router"]["noninferiority_passed"])
            self.assertEqual(analysis["multiple_comparison_correction"]["method"], "holm")
            self.assertIn("cluster_bootstrap_95ci_percent", analysis["pairwise_effects"]["A-search-only_to_D-full-router"])
            (out / "study-analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            power = estimate(
                rows,
                metric="model_visible_proxy_tokens",
                minimum_effect=0.15,
                floor_repeats=4,
                alpha=0.05,
                power=0.80,
            )
            (out / "study-power.json").write_text(json.dumps(power, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = build_public_bundle(root=out, out=public)
            self.assertTrue((public / "analysis.sanitized.json").exists())
            self.assertTrue((public / "power.sanitized.json").exists())
            self.assertTrue((public / "audit.sanitized.json").exists())
            public_text = (public / "runs.sanitized.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("study_task", public_text)
            self.assertNotIn("sample", public_text)
            self.assertNotIn(str(repo), public_text)
            public_rows = [json.loads(line) for line in public_text.splitlines()]
            self.assertEqual(public_rows[0]["task_public_id"], "task_001")
            self.assertEqual(public_rows[0]["repo_public_id"], "repo_001")
            self.assertIn("semantic_session_mode", public_rows[0])
            self.assertIn("codex_version", public_rows[0])
            self.assertIn("snapshot_state_hmac", public_rows[0])
            semantic_public_row = next(row for row in public_rows if row["semantic_access_enabled"])
            self.assertRegex(semantic_public_row["semantic_session_id_hmac"], r"^[0-9a-f]{24}$")
            self.assertRegex(semantic_public_row["semantic_project_path_hmac"], r"^[0-9a-f]{24}$")
            self.assertNotIn("task_id", public_rows[0])
            self.assertNotIn("repo", public_rows[0])
            self.assertNotIn("source_commit", public_rows[0])
            self.assertNotIn("snapshot_commit", public_rows[0])
            manifest = json.loads((public / "manifest.sanitized.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["privacy"]["private_task_ids_removed"])
            self.assertTrue(manifest["privacy"]["private_repo_ids_removed"])
            self.assertTrue(manifest["privacy"]["private_task_oracle_and_manifest_hashes_omitted"])
            self.assertIn("task_manifest_hmac", manifest["study_package"])
            self.assertIn("task_oracles_hmac", manifest["study_package"])
            self.assertNotIn("task_manifest_sha256", manifest["study_package"])
            self.assertNotIn("task_oracles_sha256", manifest["study_package"])
            self.assertNotIn("task_manifest_path", manifest["study_package"])
            public_analysis_text = (public / "analysis.sanitized.json").read_text(encoding="utf-8")
            self.assertNotIn('"sample":', public_analysis_text)
            public_analysis = json.loads(public_analysis_text)
            self.assertIn(
                "repo_001",
                public_analysis["pairwise_effects_by_repo"]["A-search-only_to_D-full-router"],
            )
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
