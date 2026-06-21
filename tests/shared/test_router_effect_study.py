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
from scripts.benchmarks.shared.check_public_sanitization import public_evidence_schema_violations
from scripts.benchmarks.verify_task_oracles import main as verify_task_oracles_main
from scripts.lib.agent_session import AgentProfile, load_route_profile, load_tasks
from scripts.lib.environment_capture import file_sha256
from scripts.lib.experiment_design import balanced_latin_square, load_study_plan
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
        "study_task\tknown_symbol_definition\tios_reference\tFind the sample declaration and report route-appropriate evidence.\tA-search-only,B-search-summary,C-lsp-naive,D-full-router\tfalse\tfalse\tsemantic_identity_or_search_labeled\tdeclaration reported\tDo not claim runtime behavior.\t900\n",
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
    manifest["prewarm_semantic_layer"] = True
    manifest["serena_readiness_enabled"] = True
    manifest["controller_dirty"] = False
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
                    "controller_commit": manifest["controller_commit"],
                    "controller_tree_hash": manifest["controller_tree_hash"],
                    "protocol_commit": manifest["controller_commit"],
                    "exact_input_tokens": value + 100,
                    "exact_cached_input_tokens": 100,
                    "exact_uncached_input_tokens": value,
                    "exact_output_tokens": 50,
                    "exact_total_tokens": value + 150,
                    "exact_uncached_total_tokens": value + 50,
                    "exact_reasoning_output_tokens": 0,
                    "exact_usage_event_count": 1,
                    "wall_seconds": 1.0,
                    "semantic_setup_seconds": 0.25 if row["semantic_access_enabled"] else 0.0,
                    "task_execution_seconds": 1.0,
                    "end_to_end_seconds": 1.25 if row["semantic_access_enabled"] else 1.0,
                    "serena_readiness_status": "pass" if row["semantic_access_enabled"] else "",
                    "serena_readiness_ready": True if row["semantic_access_enabled"] else None,
                    "serena_readiness_reason": "",
                    "serena_process_state_after_readiness": {
                        "serena_mcp": 0,
                        "sourcekit_lsp": 0,
                        "kotlin_lsp": 0,
                        "json_lsp": 0,
                    }
                    if row["semantic_access_enabled"]
                    else {},
                    "semantic_lifecycle_owner": "codex_subprocess_stdio" if row["semantic_access_enabled"] else "none",
                    "semantic_teardown_verified": True,
                    "semantic_process_survivor_count": 0,
                    "semantic_child_lsp_survivor_count": 0,
                    "serena_process_state_before": {
                        "serena_mcp": 0,
                        "sourcekit_lsp": 0,
                        "kotlin_lsp": 0,
                        "json_lsp": 0,
                    },
                    "serena_process_state_after": {
                        "serena_mcp": 0,
                        "sourcekit_lsp": 0,
                        "kotlin_lsp": 0,
                        "json_lsp": 0,
                    },
                    "codex_version": "codex-test 1.0",
                    "serena_version": "serena-test 1.0",
                    "os_version": "test-os",
                }
            )
            if row["semantic_access_enabled"]:
                run_dir = Path(row["run_dir"])
                semantic_path = run_dir / "semantic-session.json"
                semantic_payload = json.loads(semantic_path.read_text(encoding="utf-8"))
                readiness = {
                    "status": "pass",
                    "ready": True,
                    "reason": "",
                    "symbol": "StudySymbol",
                    "source_file": "Sources/StudySymbol.swift",
                    "warnings": [],
                    "semantic_session_home": semantic_payload["semantic_session_home"],
                    "isolated_env_keys": sorted(semantic_payload["mcp_env_keys"]),
                    "process_state_after": row["serena_process_state_after_readiness"],
                }
                (run_dir / "serena-readiness.json").write_text(
                    json.dumps(readiness, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                semantic_payload["readiness_status"] = "pass"
                semantic_payload["readiness_ready"] = True
                semantic_payload["readiness_process_state_after"] = row["serena_process_state_after_readiness"]
                semantic_payload["lifecycle_owner"] = "codex_subprocess_stdio"
                semantic_payload["teardown_verified"] = True
                semantic_payload["process_survivor_count"] = 0
                semantic_payload["child_lsp_survivor_count"] = 0
                semantic_payload["pre_task_process_state"] = row["serena_process_state_before"]
                semantic_payload["post_task_process_state"] = row["serena_process_state_after"]
                semantic_path.write_text(json.dumps(semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            handle.write(json.dumps(row, sort_keys=True) + "\n")


class RouterEffectStudyTests(unittest.TestCase):
    def test_router_effect_v1_task_manifests_use_only_ios_and_web_labels(self) -> None:
        allowed = {"ios_reference", "web_reference"}
        study_dir = ROOT / "benchmarks/real-agent-routing/studies/router-effect-v1"
        study_plan = load_study_plan(study_dir / "study.yaml")
        self.assertTrue(study_plan.require_explicit_reasoning_effort)
        for name, expected_count in {
            "pilot-tasks.tsv": 6,
            "confirmatory-tasks.tsv": 15,
        }.items():
            with self.subTest(name=name):
                tasks = load_tasks(study_dir / name)
                self.assertEqual(len(tasks), expected_count)
                self.assertLessEqual({task.repo for task in tasks}, allowed)

    def test_balanced_latin_square_places_each_arm_once_per_position(self) -> None:
        arms = ["A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"]
        square = balanced_latin_square(arms)

        self.assertEqual(len(square), 4)
        for sequence in square:
            self.assertEqual(sorted(sequence), sorted(arms))
        for arm in arms:
            positions = [sequence.index(arm) + 1 for sequence in square]
            self.assertEqual(sorted(positions), [1, 2, 3, 4])

    def test_analysis_keeps_same_task_id_separate_across_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = []
            token_values = {
                "repo_alpha": {
                    "A-search-only": 1000,
                    "B-search-summary": 900,
                    "C-lsp-naive": 800,
                    "D-full-router": 700,
                },
                "repo_beta": {
                    "A-search-only": 2000,
                    "B-search-summary": 1800,
                    "C-lsp-naive": 1600,
                    "D-full-router": 1400,
                },
            }
            for repo, values in token_values.items():
                for sequence_position, (profile, value) in enumerate(values.items(), start=1):
                    rows.append(
                        {
                            "agent": "codex",
                            "task_id": "shared_task_id",
                            "repo": repo,
                            "task_family": "known_symbol_definition",
                            "repeat_index": 0,
                            "profile": profile,
                            "sequence_position": sequence_position,
                            "oracle_status": "pass",
                            "exact_uncached_input_tokens": value,
                        }
                    )
            (root / "runs.jsonl").write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                encoding="utf-8",
            )

            result = analyze(root, metric="exact_uncached_input_tokens")
            comparison = "A-search-only_to_D-full-router"

            self.assertEqual(result["cell_key_fields"], ["agent", "task_id", "repo", "repeat_index"])
            self.assertEqual(result["cluster_unit"], "repository_task")
            self.assertEqual(result["pairwise_effects"][comparison]["pair_count"], 2)
            self.assertEqual(result["correctness_pairwise"][comparison]["pair_count"], 2)
            self.assertEqual(
                set(result["pairwise_effects_by_repo"][comparison]),
                {"repo_alpha", "repo_beta"},
            )
            self.assertEqual(result["factorial_effects"]["semantic_access_main_effect"]["pair_count"], 2)

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
                        f"ios_reference={repo}",
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
            self.assertRegex(manifest["controller_commit"], r"^[0-9a-f]{40,64}$")
            self.assertRegex(manifest["controller_tree_hash"], r"^[0-9a-f]{40,64}$")
            self.assertIsInstance(manifest["controller_dirty"], bool)
            self.assertEqual(
                set(manifest["route_profile_hashes"]),
                {"A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"},
            )
            for digest in manifest["route_profile_hashes"].values():
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
            for row in rows:
                run_dir = Path(row["run_dir"])
                self.assertTrue((run_dir / "semantic-session.json").exists())
                self.assertEqual(row["semantic_session_artifact"], "semantic-session.json")
                self.assertEqual(row["protocol_commit"], manifest["controller_commit"])
                self.assertEqual(row["controller_commit"], manifest["controller_commit"])
                self.assertEqual(row["controller_tree_hash"], manifest["controller_tree_hash"])
                self.assertIn("codex_version", row)
                self.assertRegex(row["source_commit"], r"^[0-9a-f]{40,64}$")
                self.assertEqual(row["source_commit"], row["snapshot_commit"])
                self.assertEqual(row["source_tree_hash"], row["snapshot_tree_hash"])
                self.assertEqual(row["source_lockfile_hash"], row["lockfile_hash"])
                self.assertRegex(row["snapshot_state_hmac"], r"^[0-9a-f]{24}$")
                self.assertEqual(row["route_profile_hash"], manifest["route_profile_hashes"][row["profile"]])
                self.assertEqual(row["model_id"], manifest["model_id"])
                self.assertEqual(row["reasoning_effort"], manifest["reasoning_effort"])
                semantic_session = json.loads((run_dir / "semantic-session.json").read_text(encoding="utf-8"))
                self.assertTrue(row["semantic_teardown_verified"])
                self.assertEqual(row["semantic_process_survivor_count"], 0)
                self.assertEqual(row["semantic_child_lsp_survivor_count"], 0)
                self.assertEqual(row["serena_process_state_before"], semantic_session["pre_task_process_state"])
                self.assertEqual(row["serena_process_state_after"], semantic_session["post_task_process_state"])
                if row["semantic_access_enabled"]:
                    self.assertEqual(semantic_session["session_id"], row["run_id"])
                    self.assertEqual(semantic_session["mode"], "codex_mcp_stdio_per_run")
                    self.assertTrue(semantic_session["isolated"])
                    self.assertEqual(semantic_session["transport"], "stdio")
                    self.assertEqual(row["semantic_lifecycle_owner"], "dry_run_no_process_started")
                    self.assertEqual(semantic_session["lifecycle_owner"], "dry_run_no_process_started")
                    self.assertTrue(semantic_session["teardown_verified"])
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
                    self.assertEqual(row["semantic_lifecycle_owner"], "none")
            self.assertTrue(manifest["snapshot_repos"])
            self.assertTrue(manifest["isolated_agent_home"])
            self.assertTrue(manifest["require_clean_serena_process_state"])
            self.assertTrue(manifest["require_explicit_reasoning_effort"])
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
            treatment_diffs = [
                json.loads(line)
                for line in (out / "treatment-diffs.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(treatment_diffs), 4)
            for treatment_diff in treatment_diffs:
                self.assertTrue(treatment_diff["valid"], treatment_diff)
                comparison_pairs = {
                    (comparison["left_profile"], comparison["right_profile"])
                    for comparison in treatment_diff["comparisons"]
                }
                self.assertEqual(
                    comparison_pairs,
                    {
                        ("A-search-only", "B-search-summary"),
                        ("A-search-only", "C-lsp-naive"),
                        ("C-lsp-naive", "D-full-router"),
                        ("B-search-summary", "D-full-router"),
                        ("A-search-only", "D-full-router"),
                    },
                )
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
            original_language_versions = dict(semantic_payload["language_server_versions"])
            semantic_payload["language_server_versions"]["sourcekit-lsp"] = "different-sourcekit"
            semantic_path.write_text(json.dumps(semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            language_version_audit = audit(out)
            self.assertIn("semantic_language_version_match", {issue["code"] for issue in language_version_audit["issues"]})
            semantic_payload["language_server_versions"] = original_language_versions
            semantic_path.write_text(json.dumps(semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            runs_path = out / "runs.jsonl"
            original_runs_text = runs_path.read_text(encoding="utf-8")
            row_lines = [json.loads(line) for line in original_runs_text.splitlines()]
            row_lines[0]["codex_version"] = "different-codex-version"
            runs_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in row_lines), encoding="utf-8")
            tool_version_audit = audit(out)
            self.assertIn("block_tool_version_match", {issue["code"] for issue in tool_version_audit["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")
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
            self.assertIn("exact_token_telemetry", {issue["code"] for issue in failed_audit["issues"]})

            row_lines = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            row_lines[0]["snapshot_commit"] = "0" * 40
            (out / "runs.jsonl").write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in row_lines),
                encoding="utf-8",
            )
            snapshot_audit = audit(out)
            self.assertIn("source_snapshot_commit_match", {issue["code"] for issue in snapshot_audit["issues"]})

    def test_live_study_mode_requires_explicit_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "CODEX_HOME": str(fake_codex_home(root)),
                "RARB_PRIVATE_HMAC_KEY": "test-hmac-key",
            }
            with patch.dict("os.environ", env):
                with self.assertRaisesRegex(SystemExit, "reasoning-effort"):
                    main(
                        [
                            "--live",
                            "--agent",
                            "codex",
                            "--repo",
                            str(root),
                            "--study-plan",
                            str(ROOT / "benchmarks/real-agent-routing/studies/router-effect-v1/study.yaml"),
                            "--arms",
                            "A-search-only,B-search-summary,C-lsp-naive,D-full-router",
                            "--repeats",
                            "4",
                            "--snapshot-repos",
                            "--model-id",
                            "codex-test-model",
                        ]
                    )

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
                        f"ios_reference={repo}",
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

            manifest_path = out / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            dirty_controller_manifest = dict(manifest)
            dirty_controller_manifest["controller_dirty"] = True
            manifest_path.write_text(json.dumps(dirty_controller_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            dirty_controller = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("controller_clean", {issue["code"] for issue in dirty_controller["issues"]})
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            default_reasoning_manifest = dict(manifest)
            default_reasoning_manifest["reasoning_effort"] = "default"
            manifest_path.write_text(json.dumps(default_reasoning_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            default_reasoning = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            default_reasoning_codes = {issue["code"] for issue in default_reasoning["issues"]}
            self.assertIn("reasoning_effort", default_reasoning_codes)
            self.assertIn("row_reasoning_effort_match", default_reasoning_codes)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            runs_path = out / "runs.jsonl"
            original_runs_text = runs_path.read_text(encoding="utf-8")
            mismatched_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            mismatched_rows[0]["protocol_commit"] = "0" * 40
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in mismatched_rows),
                encoding="utf-8",
            )
            mismatched_controller = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("row_protocol_commit_match", {issue["code"] for issue in mismatched_controller["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

            mismatched_model_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            mismatched_model_rows[0]["model_id"] = "different-test-model"
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in mismatched_model_rows),
                encoding="utf-8",
            )
            mismatched_model = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("row_model_id_match", {issue["code"] for issue in mismatched_model["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

            mismatched_reasoning_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            mismatched_reasoning_rows[0]["reasoning_effort"] = "medium"
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in mismatched_reasoning_rows),
                encoding="utf-8",
            )
            mismatched_reasoning = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("row_reasoning_effort_match", {issue["code"] for issue in mismatched_reasoning["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

            missing_usage_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            missing_usage_rows[0]["exact_usage_event_count"] = 0
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in missing_usage_rows),
                encoding="utf-8",
            )
            missing_usage_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("exact_usage_event_count", {issue["code"] for issue in missing_usage_audit["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

            inconsistent_token_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            inconsistent_token_rows[0]["exact_uncached_input_tokens"] += 1
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in inconsistent_token_rows),
                encoding="utf-8",
            )
            inconsistent_token_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("exact_token_consistency", {issue["code"] for issue in inconsistent_token_audit["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

            bad_timing_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            bad_timing_rows[0]["end_to_end_seconds"] = 0.5
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in bad_timing_rows),
                encoding="utf-8",
            )
            bad_timing_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("timing_decomposition", {issue["code"] for issue in bad_timing_audit["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

            missing_setup_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            semantic_index = next(index for index, row in enumerate(missing_setup_rows) if row["semantic_access_enabled"])
            missing_setup_rows[semantic_index]["semantic_setup_seconds"] = 0.0
            missing_setup_rows[semantic_index]["end_to_end_seconds"] = missing_setup_rows[semantic_index]["task_execution_seconds"]
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in missing_setup_rows),
                encoding="utf-8",
            )
            missing_setup_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("semantic_setup_seconds", {issue["code"] for issue in missing_setup_audit["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

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
            self.assertEqual(power["cell_key_fields"], ["agent", "task_id", "repo", "repeat_index"])
            self.assertEqual(power["cluster_unit"], "repository_task")
            self.assertEqual(set(power["pairwise_power"]), {
                "A-search-only_to_B-search-summary",
                "A-search-only_to_C-lsp-naive",
                "C-lsp-naive_to_D-full-router",
                "A-search-only_to_D-full-router",
            })
            self.assertTrue(power["all_preregistered_comparisons_power_target_met"])
            self.assertAlmostEqual(power["z_alpha_two_sided"], 1.95996398)
            self.assertAlmostEqual(power["z_power"], 0.84162123)
            (out / "study-power.json").write_text(json.dumps(power, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            unpriced_analysis_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("study_analysis_cost", {issue["code"] for issue in unpriced_analysis_audit["issues"]})
            malformed_power = dict(power)
            malformed_power.pop("pairwise_power")
            (out / "study-power.json").write_text(json.dumps(malformed_power, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            malformed = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("study_power_shape", {issue["code"] for issue in malformed["issues"]})
            (out / "study-power.json").write_text(json.dumps(power, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            stale_analysis = json.loads(json.dumps(analysis))
            stale_analysis["pairwise_effects"]["A-search-only_to_D-full-router"]["median_percent_change"] = 123.45
            (out / "study-analysis.json").write_text(json.dumps(stale_analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            stale_analysis_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("study_analysis_consistency", {issue["code"] for issue in stale_analysis_audit["issues"]})
            (out / "study-analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            stale_power = json.loads(json.dumps(power))
            stale_power["pairwise_power"]["A-search-only_to_D-full-router"]["observed_pairs"] = 999
            (out / "study-power.json").write_text(json.dumps(stale_power, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            stale_power_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("study_power_consistency", {issue["code"] for issue in stale_power_audit["issues"]})
            (out / "study-power.json").write_text(json.dumps(power, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            original_runs_text = runs_path.read_text(encoding="utf-8")
            row_lines = [json.loads(line) for line in original_runs_text.splitlines()]
            runs_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in row_lines[:-1]), encoding="utf-8")
            missing_matrix = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            missing_matrix_codes = {issue["code"] for issue in missing_matrix["issues"]}
            self.assertIn("confirmatory_matrix_cell_count", missing_matrix_codes)
            self.assertIn("confirmatory_matrix_missing", missing_matrix_codes)
            runs_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in [*row_lines, row_lines[0]]), encoding="utf-8")
            duplicate_matrix = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            duplicate_matrix_codes = {issue["code"] for issue in duplicate_matrix["issues"]}
            self.assertIn("confirmatory_matrix_cell_count", duplicate_matrix_codes)
            self.assertIn("confirmatory_matrix_duplicate", duplicate_matrix_codes)
            runs_path.write_text(original_runs_text, encoding="utf-8")

            treatment_diffs_path = out / "treatment-diffs.jsonl"
            original_treatment_diffs = treatment_diffs_path.read_text(encoding="utf-8")
            treatment_diff_rows = [json.loads(line) for line in original_treatment_diffs.splitlines()]
            treatment_diff_rows[0]["valid"] = False
            treatment_diffs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in treatment_diff_rows),
                encoding="utf-8",
            )
            stale_treatment_diff = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            stale_treatment_diff_codes = {issue["code"] for issue in stale_treatment_diff["issues"]}
            self.assertIn("treatment_diff_artifact_consistency", stale_treatment_diff_codes)
            self.assertIn("treatment_diff_artifact_valid", stale_treatment_diff_codes)
            treatment_diffs_path.write_text(original_treatment_diffs, encoding="utf-8")
            treatment_diffs_path.unlink()
            missing_treatment_diff = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("treatment_diff_artifact", {issue["code"] for issue in missing_treatment_diff["issues"]})
            treatment_diffs_path.write_text(original_treatment_diffs, encoding="utf-8")

            row_lines = [json.loads(line) for line in original_runs_text.splitlines()]
            first_route_path = Path(row_lines[0]["run_dir"]) / "route-isolation.json"
            first_route = json.loads(first_route_path.read_text(encoding="utf-8"))
            first_route_original = json.loads(json.dumps(first_route))
            first_route["args"] = [arg for arg in first_route["args"] if arg != "--ignore-rules"]
            first_route_path.write_text(json.dumps(first_route, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            missing_flag_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("route_isolation_invocation", {issue["code"] for issue in missing_flag_audit["issues"]})
            first_route_path.write_text(json.dumps(first_route_original, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            semantic_row = next(row for row in row_lines if row["semantic_access_enabled"])
            semantic_route_path = Path(semantic_row["run_dir"]) / "route-isolation.json"
            semantic_route = json.loads(semantic_route_path.read_text(encoding="utf-8"))
            semantic_route_original = json.loads(json.dumps(semantic_route))
            semantic_route["args"] = [
                "mcp_servers={}" if isinstance(arg, str) and arg.startswith("mcp_servers=") else arg
                for arg in semantic_route["args"]
            ]
            semantic_route_path.write_text(json.dumps(semantic_route, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            missing_semantic_mcp = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("route_isolation_semantic_mcp", {issue["code"] for issue in missing_semantic_mcp["issues"]})
            semantic_route_path.write_text(json.dumps(semantic_route_original, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            pricing = {
                "model_id": "codex-test-model",
                "input_per_1m": 2.0,
                "cached_input_per_1m": 0.5,
                "output_per_1m": 8.0,
                "reasoning_output_per_1m": 8.0,
            }
            priced_analysis = analyze(out, metric="exact_uncached_input_tokens", pricing=pricing)
            self.assertEqual(priced_analysis["cost"]["status"], "estimated")
            self.assertEqual(priced_analysis["cost"]["pricing_model_id"], "codex-test-model")
            self.assertEqual(
                set(priced_analysis["cost"]["by_arm"]),
                {"A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"},
            )
            self.assertIn("estimated_cost_per_run", priced_analysis["cost"]["by_arm"]["A-search-only"])
            self.assertIn("estimated_cost_per_successful_task", priced_analysis["cost"]["by_arm"]["A-search-only"])
            (out / "study-analysis.json").write_text(json.dumps(priced_analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            priced_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertEqual(priced_audit["status"], "pass", priced_audit)

            bad_route_hash_rows = [json.loads(line) for line in original_runs_text.splitlines()]
            bad_route_hash_rows[0]["route_profile_hash"] = "0" * 64
            runs_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in bad_route_hash_rows),
                encoding="utf-8",
            )
            bad_route_hash_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("row_route_profile_hash_match", {issue["code"] for issue in bad_route_hash_audit["issues"]})
            runs_path.write_text(original_runs_text, encoding="utf-8")

            first_row = json.loads(original_runs_text.splitlines()[0])
            effective_config_path = Path(first_row["run_dir"]) / "effective-agent-config.json"
            effective_config = json.loads(effective_config_path.read_text(encoding="utf-8"))
            original_effective_config = dict(effective_config)
            effective_config["route_profile_hash"] = "0" * 64
            effective_config_path.write_text(json.dumps(effective_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            bad_effective_hash_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("effective_config_route_profile_hash", {issue["code"] for issue in bad_effective_hash_audit["issues"]})
            effective_config_path.write_text(json.dumps(original_effective_config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            malformed_cost_analysis = dict(priced_analysis)
            malformed_cost_analysis["cost"] = {
                "status": "estimated",
                "pricing_model_id": "different-model",
                "pricing_per_1m_tokens": {"input_per_1m": 2.0},
                "by_arm": {},
            }
            (out / "study-analysis.json").write_text(json.dumps(malformed_cost_analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            malformed_cost = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("study_analysis_cost", {issue["code"] for issue in malformed_cost["issues"]})
            (out / "study-analysis.json").write_text(json.dumps(priced_analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            no_prewarm_manifest = dict(manifest)
            no_prewarm_manifest["prewarm_semantic_layer"] = False
            no_prewarm_manifest["serena_readiness_enabled"] = False
            manifest_path.write_text(json.dumps(no_prewarm_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            no_prewarm = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            no_prewarm_codes = {issue["code"] for issue in no_prewarm["issues"]}
            self.assertIn("prewarm_semantic_layer", no_prewarm_codes)
            self.assertIn("serena_readiness_enabled", no_prewarm_codes)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            no_process_state_manifest = dict(manifest)
            no_process_state_manifest["require_clean_serena_process_state"] = False
            manifest_path.write_text(json.dumps(no_process_state_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            no_process_state = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("serena_process_state", {issue["code"] for issue in no_process_state["issues"]})
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            no_reasoning_policy_manifest = dict(manifest)
            no_reasoning_policy_manifest["require_explicit_reasoning_effort"] = False
            manifest_path.write_text(json.dumps(no_reasoning_policy_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            no_reasoning_policy = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("reasoning_effort_policy", {issue["code"] for issue in no_reasoning_policy["issues"]})
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            bad_analysis_plan = root / "bad-analysis-plan.yaml"
            good_analysis_plan_text = (
                ROOT / "benchmarks/real-agent-routing/studies/router-effect-v1/analysis-plan.yaml"
            ).read_text(encoding="utf-8")
            bad_analysis_plan.write_text(
                good_analysis_plan_text.replace("cluster_unit: repository_task", "cluster_unit: task_id"),
                encoding="utf-8",
            )
            bad_plan_manifest = dict(manifest)
            bad_plan_package = dict(manifest["study_package"])
            bad_plan_package["analysis_plan_path"] = str(bad_analysis_plan)
            bad_plan_manifest["study_package"] = bad_plan_package
            manifest_path.write_text(json.dumps(bad_plan_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            bad_plan_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            bad_plan_codes = {issue["code"] for issue in bad_plan_audit["issues"]}
            self.assertIn("analysis_plan", bad_plan_codes)
            self.assertIn("study_package_hash_match", bad_plan_codes)
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            bad_tasks = root / "bad-tasks.tsv"
            bad_tasks.write_text(
                tasks.read_text(encoding="utf-8").replace("\tios_reference\t", "\tserver_reference\t", 1),
                encoding="utf-8",
            )
            bad_tasks_manifest = dict(manifest)
            bad_tasks_package = dict(manifest["study_package"])
            bad_tasks_package["task_manifest_path"] = str(bad_tasks)
            bad_tasks_package["task_manifest_sha256"] = file_sha256(bad_tasks)
            bad_tasks_manifest["study_package"] = bad_tasks_package
            manifest_path.write_text(json.dumps(bad_tasks_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            bad_repo_label_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("confirmatory_repository_labels", {issue["code"] for issue in bad_repo_label_audit["issues"]})
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            row_lines = [json.loads(line) for line in original_runs_text.splitlines()]
            semantic_index = next(index for index, row in enumerate(row_lines) if row["semantic_access_enabled"])
            row_lines[semantic_index]["serena_readiness_status"] = "fail"
            row_lines[semantic_index]["serena_readiness_ready"] = False
            semantic_path = Path(row_lines[semantic_index]["run_dir"]) / "semantic-session.json"
            semantic_payload = json.loads(semantic_path.read_text(encoding="utf-8"))
            original_semantic_payload = dict(semantic_payload)
            semantic_payload["readiness_status"] = "fail"
            semantic_payload["readiness_ready"] = False
            semantic_path.write_text(json.dumps(semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            readiness_path = Path(row_lines[semantic_index]["run_dir"]) / "serena-readiness.json"
            readiness_text = readiness_path.read_text(encoding="utf-8")
            readiness_path.unlink()
            runs_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in row_lines), encoding="utf-8")
            readiness_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            readiness_codes = {issue["code"] for issue in readiness_audit["issues"]}
            self.assertIn("semantic_readiness", readiness_codes)
            self.assertIn("semantic_session_readiness", readiness_codes)
            self.assertIn("semantic_readiness_artifact", readiness_codes)
            semantic_path.write_text(json.dumps(original_semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            readiness_path.write_text(readiness_text, encoding="utf-8")
            runs_path.write_text(original_runs_text, encoding="utf-8")

            readiness_payload = json.loads(readiness_text)
            readiness_payload["semantic_session_home"] = str(Path(row_lines[semantic_index]["run_dir"]) / "wrong-serena-session")
            readiness_path.write_text(json.dumps(readiness_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            readiness_home_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("semantic_readiness_isolation", {issue["code"] for issue in readiness_home_audit["issues"]})
            readiness_path.write_text(readiness_text, encoding="utf-8")

            readiness_payload = json.loads(readiness_text)
            readiness_payload["isolated_env_keys"] = ["SERENA_HOME"]
            readiness_path.write_text(json.dumps(readiness_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            readiness_env_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("semantic_readiness_isolation", {issue["code"] for issue in readiness_env_audit["issues"]})
            readiness_path.write_text(readiness_text, encoding="utf-8")

            readiness_payload = json.loads(readiness_text)
            dirty_readiness_state = dict(readiness_payload["process_state_after"])
            dirty_readiness_state["sourcekit_lsp"] = 1
            readiness_payload["process_state_after"] = dirty_readiness_state
            readiness_path.write_text(json.dumps(readiness_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            readiness_process_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("semantic_readiness_process_state", {issue["code"] for issue in readiness_process_audit["issues"]})
            readiness_path.write_text(readiness_text, encoding="utf-8")

            row_lines = [json.loads(line) for line in original_runs_text.splitlines()]
            semantic_index = next(index for index, row in enumerate(row_lines) if row["semantic_access_enabled"])
            semantic_path = Path(row_lines[semantic_index]["run_dir"]) / "semantic-session.json"
            semantic_payload = json.loads(semantic_path.read_text(encoding="utf-8"))
            original_semantic_payload = dict(semantic_payload)
            survivor_state = dict(semantic_payload["post_task_process_state"])
            survivor_state["sourcekit_lsp"] = 1
            semantic_payload["post_task_process_state"] = survivor_state
            semantic_payload["teardown_verified"] = False
            semantic_payload["process_survivor_count"] = 1
            semantic_payload["child_lsp_survivor_count"] = 1
            row_lines[semantic_index]["serena_process_state_after"] = survivor_state
            row_lines[semantic_index]["semantic_teardown_verified"] = False
            row_lines[semantic_index]["semantic_process_survivor_count"] = 1
            row_lines[semantic_index]["semantic_child_lsp_survivor_count"] = 1
            semantic_path.write_text(json.dumps(semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            runs_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in row_lines), encoding="utf-8")
            teardown_audit = audit(out, confirmatory=True, min_task_families=1, min_tasks_per_family=1)
            self.assertIn("semantic_teardown", {issue["code"] for issue in teardown_audit["issues"]})
            semantic_path.write_text(json.dumps(original_semantic_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            runs_path.write_text(original_runs_text, encoding="utf-8")

            tainted_manifest = dict(manifest)
            tainted_manifest.update(
                {
                    "rerun_failed": True,
                    "rerun_carried_forward_runs": 1,
                    "rerun_carried_forward_cells": ["codex/A-search-only/study_task/ios_reference/0"],
                    "invalid_carried_forward_runs": 1,
                    "invalid_carried_forward_cells": ["codex/B-search-summary/study_task/ios_reference/0"],
                    "missing_artifact_carried_forward_runs": 1,
                    "missing_artifact_carried_forward_cells": ["codex/C-lsp-naive/study_task/ios_reference/0"],
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
            public = root / "benchmarks" / "real-agent-routing" / "evidence" / "router-effect-v1-public"
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
                        f"ios_reference={repo}",
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
            pricing = {
                "model_id": "codex-test-model",
                "input_per_1m": 2.0,
                "cached_input_per_1m": 0.5,
                "output_per_1m": 8.0,
                "reasoning_output_per_1m": 8.0,
            }
            analysis = analyze(out, metric="exact_uncached_input_tokens", pricing=pricing)
            self.assertIn("pairwise_effects_by_repo", analysis)
            self.assertIn("ios_reference", analysis["pairwise_effects_by_repo"]["A-search-only_to_D-full-router"])
            self.assertIn("factorial_effects", analysis)
            self.assertIn("correctness_pairwise", analysis)
            self.assertTrue(analysis["correctness_pairwise"]["A-search-only_to_D-full-router"]["noninferiority_passed"])
            self.assertEqual(analysis["multiple_comparison_correction"]["method"], "holm")
            self.assertIn("cluster_bootstrap_95ci_percent", analysis["pairwise_effects"]["A-search-only_to_D-full-router"])
            self.assertEqual(analysis["cost"]["status"], "estimated")
            (out / "study-analysis.json").write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            rows = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            power = estimate(
                rows,
                metric="exact_uncached_input_tokens",
                minimum_effect=0.15,
                floor_repeats=4,
                alpha=0.05,
                power=0.80,
            )
            (out / "study-power.json").write_text(json.dumps(power, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "confirmatory audit"):
                build_public_bundle(root=out, out=public)
            result = build_public_bundle(root=out, out=public, min_task_families=1, min_tasks_per_family=1)
            schema_violations = []
            for path in sorted(public.iterdir()):
                schema_violations.extend(public_evidence_schema_violations(path, root))
            self.assertEqual(schema_violations, [])
            self.assertTrue((public / "analysis.sanitized.json").exists())
            self.assertTrue((public / "power.sanitized.json").exists())
            self.assertTrue((public / "audit.sanitized.json").exists())
            self.assertTrue((public / "treatment-diffs.sanitized.jsonl").exists())
            public_audit = json.loads((public / "audit.sanitized.json").read_text(encoding="utf-8"))
            self.assertEqual(public_audit["audit_mode"], "confirmatory")
            self.assertEqual(public_audit["status"], "pass")
            self.assertEqual(public_audit["min_task_families"], 1)
            self.assertEqual(public_audit["min_tasks_per_family"], 1)
            public_text = (public / "runs.sanitized.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("study_task", public_text)
            self.assertNotIn("ios_reference", public_text)
            self.assertNotIn(str(repo), public_text)
            public_rows = [json.loads(line) for line in public_text.splitlines()]
            self.assertEqual(public_rows[0]["task_public_id"], "task_001")
            self.assertEqual(public_rows[0]["repo_public_id"], "repo_001")
            self.assertIn("exact_uncached_total_tokens", public_rows[0])
            self.assertIn("exact_usage_event_count", public_rows[0])
            self.assertIn("semantic_session_mode", public_rows[0])
            self.assertIn("semantic_teardown_verified", public_rows[0])
            self.assertIn("semantic_child_lsp_survivor_count", public_rows[0])
            self.assertIn("serena_process_state_before", public_rows[0])
            self.assertIn("serena_process_state_after", public_rows[0])
            self.assertIn("codex_version", public_rows[0])
            self.assertRegex(public_rows[0]["protocol_commit"], r"^[0-9a-f]{40,64}$")
            self.assertEqual(public_rows[0]["controller_commit"], public_rows[0]["protocol_commit"])
            self.assertRegex(public_rows[0]["controller_tree_hash"], r"^[0-9a-f]{40,64}$")
            self.assertIn("snapshot_state_hmac", public_rows[0])
            semantic_public_row = next(row for row in public_rows if row["semantic_access_enabled"])
            self.assertRegex(semantic_public_row["semantic_session_id_hmac"], r"^[0-9a-f]{24}$")
            self.assertRegex(semantic_public_row["semantic_project_path_hmac"], r"^[0-9a-f]{24}$")
            self.assertTrue(semantic_public_row["semantic_teardown_verified"])
            self.assertEqual(semantic_public_row["semantic_child_lsp_survivor_count"], 0)
            self.assertNotIn("task_id", public_rows[0])
            self.assertNotIn("repo", public_rows[0])
            self.assertNotIn("source_commit", public_rows[0])
            self.assertNotIn("snapshot_commit", public_rows[0])
            manifest = json.loads((public / "manifest.sanitized.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["privacy"]["private_task_ids_removed"])
            self.assertTrue(manifest["privacy"]["private_repo_ids_removed"])
            self.assertTrue(manifest["privacy"]["private_task_oracle_and_manifest_hashes_omitted"])
            self.assertRegex(manifest["controller_commit"], r"^[0-9a-f]{40,64}$")
            self.assertRegex(manifest["controller_tree_hash"], r"^[0-9a-f]{40,64}$")
            self.assertIsInstance(manifest["controller_dirty"], bool)
            self.assertEqual(
                set(manifest["route_profile_hashes"]),
                {"A-search-only", "B-search-summary", "C-lsp-naive", "D-full-router"},
            )
            for digest in manifest["route_profile_hashes"].values():
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertTrue(manifest["require_clean_serena_process_state"])
            self.assertTrue(manifest["require_explicit_reasoning_effort"])
            self.assertIn("study_plan_hmac", manifest["study_package"])
            self.assertIn("protocol_hmac", manifest["study_package"])
            self.assertIn("analysis_plan_hmac", manifest["study_package"])
            self.assertIn("task_manifest_hmac", manifest["study_package"])
            self.assertIn("task_oracles_hmac", manifest["study_package"])
            self.assertNotIn("task_manifest_sha256", manifest["study_package"])
            self.assertNotIn("task_oracles_sha256", manifest["study_package"])
            self.assertNotIn("task_manifest_path", manifest["study_package"])
            public_analysis_text = (public / "analysis.sanitized.json").read_text(encoding="utf-8")
            self.assertNotIn('"ios_reference":', public_analysis_text)
            public_analysis = json.loads(public_analysis_text)
            self.assertEqual(public_analysis["cluster_unit"], "repository_task")
            self.assertIn(
                "repo_001",
                public_analysis["pairwise_effects_by_repo"]["A-search-only_to_D-full-router"],
            )
            public_power = json.loads((public / "power.sanitized.json").read_text(encoding="utf-8"))
            self.assertEqual(public_power["cluster_unit"], "repository_task")
            public_treatment_text = (public / "treatment-diffs.sanitized.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("study_task", public_treatment_text)
            self.assertNotIn('"ios_reference"', public_treatment_text)
            public_treatment_rows = [json.loads(line) for line in public_treatment_text.splitlines()]
            self.assertEqual(public_treatment_rows[0]["task_public_id"], "task_001")
            self.assertEqual(public_treatment_rows[0]["repo_public_id"], "repo_001")
            self.assertNotIn("task_id", public_treatment_rows[0])
            self.assertNotIn("repo", public_treatment_rows[0])
            self.assertIn("manifest.sanitized.json", result["artifact_hashes"])
            self.assertIn("treatment-diffs.sanitized.jsonl", result["artifact_hashes"])
            artifact_hashes = json.loads((public / "artifact-hashes.sha256.json").read_text(encoding="utf-8"))
            expected_hashed_artifacts = {
                path.name
                for path in public.iterdir()
                if path.is_file() and path.name != "artifact-hashes.sha256.json"
            }
            self.assertEqual(set(artifact_hashes), expected_hashed_artifacts)
            self.assertEqual(artifact_hashes, result["artifact_hashes"])
            for name, digest in artifact_hashes.items():
                self.assertEqual(digest, file_sha256(public / name))
            manifest["unexpected_private_shape"] = True
            (public / "manifest.sanitized.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            manifest_violations = public_evidence_schema_violations(public / "manifest.sanitized.json", root)
            self.assertIn("evidence_unexpected_json_field", {item["label"] for item in manifest_violations})

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
                            f"ios_reference={repo}",
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
