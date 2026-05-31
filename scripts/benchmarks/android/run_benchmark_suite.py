#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SAMPLE_B2B_REPO = Path("/path/to/sample-repos/sample-b2b-android-app")
DEFAULT_SAMPLE_RETAIL_REPO = Path("/path/to/sample-repos/sample-retail-android-app")


@dataclass(frozen=True)
class Step:
    name: str
    argv: list[str]
    timeout_seconds: float


def repo_args(args: argparse.Namespace) -> list[str]:
    return [
        "--repo",
        f"sample_b2b_android={Path(args.sample_b2b_repo).expanduser().resolve()}",
        "--repo",
        f"sample_retail_android={Path(args.sample_retail_repo).expanduser().resolve()}",
    ]


def output_path(results_root: Path, layer: str) -> str:
    return str(results_root / layer)


def build_steps(args: argparse.Namespace) -> list[Step]:
    results_root = Path(args.results_root).expanduser().resolve()
    common_repos = repo_args(args)
    mode = ["--validate"] if args.validate_only else ["--validate", "--run"]
    steps = [
        Step(
            "default-search",
            [
                sys.executable,
                "scripts/benchmarks/shared/benchmark_runner.py",
                *mode,
                "--cases",
                "benchmarks/android/cases.sample.tsv",
                *common_repos,
                "--output",
                output_path(results_root, "default-search"),
                "--warmups",
                str(args.default_warmups),
                "--repeats",
                str(args.default_repeats),
                "--timeout",
                str(args.timeout),
            ],
            args.step_timeout,
        ),
        Step(
            "android-studio-semantic",
            [
                sys.executable,
                "scripts/benchmarks/android/studio_semantic_probe.py",
                *mode,
                "--cases",
                "benchmarks/android/studio-semantic-cases.sample.tsv",
                *common_repos,
                "--output",
                output_path(results_root, "android-studio-semantic"),
                "--repeats",
                str(args.semantic_repeats),
                "--timeout",
                str(args.timeout),
            ],
            args.step_timeout,
        ),
        Step(
            "serena-source-symbol",
            [
                sys.executable,
                "scripts/benchmarks/android/serena_source_symbol_probe.py",
                *mode,
                "--cases",
                "benchmarks/android/serena-source-symbol-cases.sample.tsv",
                *common_repos,
                "--output",
                output_path(results_root, "serena-source-symbol"),
                "--repeats",
                str(args.serena_repeats),
                "--timeout",
                str(args.serena_timeout),
            ],
            args.step_timeout,
        ),
        Step(
            "serena-project-server",
            [
                sys.executable,
                "scripts/benchmarks/android/serena_project_server_probe.py",
                *mode,
                "--cases",
                "benchmarks/android/serena-project-server-cases.sample.tsv",
                *common_repos,
                "--output",
                output_path(results_root, "serena-project-server"),
                "--warmups",
                str(args.serena_project_warmups),
                "--repeats",
                str(args.serena_project_repeats),
                "--timeout",
                str(args.serena_project_timeout),
                "--port",
                str(args.serena_project_port),
            ],
            args.serena_project_step_timeout,
        ),
        Step(
            "process-state",
            [
                sys.executable,
                "scripts/benchmarks/android/process_state_probe.py",
                *mode,
                "--output",
                output_path(results_root, "process-state"),
            ],
            args.step_timeout,
        ),
        Step(
            "project-model",
            [
                sys.executable,
                "scripts/benchmarks/android/project_model_probe.py",
                *mode,
                "--cases",
                "benchmarks/android/project-model-cases.sample.tsv",
                *common_repos,
                "--output",
                output_path(results_root, "project-model"),
                "--repeats",
                str(args.project_model_repeats),
                "--timeout",
                str(args.gradle_timeout),
            ],
            args.step_timeout,
        ),
    ]
    if args.run_gradle_project_model:
        steps[-1].argv.append("--run-gradle")
    if args.require_clean_process_state:
        for step in steps:
            if step.name == "process-state":
                step.argv.append("--require-clean")
    if args.enforce_assertions:
        for step in steps:
            step.argv.append("--enforce-assertions")
    if not args.validate_only and not args.no_report:
        report_name = args.report_name or f"android-benchmark-report-{datetime.now().strftime('%Y-%m-%d')}.md"
        steps.append(
            Step(
                "combined-report",
                [
                    sys.executable,
                    "scripts/benchmarks/android/generate_report.py",
                    "--results-root",
                    str(results_root),
                    "--output",
                    str(results_root / report_name),
                ],
                args.step_timeout,
            )
        )
        steps.append(
            Step(
                "goal-audit",
                [
                    sys.executable,
                    "scripts/benchmarks/android/goal_audit.py",
                    "--results-root",
                    str(results_root),
                    "--output-json",
                    str(results_root / "android-routing-goal-audit.json"),
                    "--output-md",
                    str(results_root / "android-routing-goal-audit.md"),
                ],
                args.step_timeout,
            )
        )
    return steps


def run_step(step: Step) -> int:
    print(f"== {step.name} ==")
    print(" ".join(step.argv), flush=True)
    proc = subprocess.Popen(step.argv, cwd=ROOT, shell=False, start_new_session=True)
    try:
        return_code = proc.wait(timeout=step.timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
        print(f"FAIL: {step.name} exceeded step timeout {step.timeout_seconds:g}s", file=sys.stderr)
        return 124
    if return_code:
        print(f"FAIL: {step.name} exited with {return_code}", file=sys.stderr)
    return return_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Android routing benchmark suite.")
    parser.add_argument("--sample-b2b-repo", default=str(DEFAULT_SAMPLE_B2B_REPO))
    parser.add_argument("--sample-retail-repo", default=str(DEFAULT_SAMPLE_RETAIL_REPO))
    parser.add_argument("--results-root", default="results/android")
    parser.add_argument("--default-warmups", type=int, default=1)
    parser.add_argument("--default-repeats", type=int, default=3)
    parser.add_argument("--semantic-repeats", type=int, default=3)
    parser.add_argument("--serena-repeats", type=int, default=1)
    parser.add_argument("--serena-project-repeats", type=int, default=3)
    parser.add_argument("--project-model-repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--serena-timeout", type=float, default=180.0)
    parser.add_argument("--serena-project-warmups", type=int, default=1)
    parser.add_argument("--serena-project-timeout", type=float, default=180.0)
    parser.add_argument("--serena-project-step-timeout", type=float, default=900.0)
    parser.add_argument("--serena-project-port", type=int, default=24392)
    parser.add_argument("--gradle-timeout", type=float, default=180.0)
    parser.add_argument("--step-timeout", type=float, default=600.0)
    parser.add_argument("--run-gradle-project-model", action="store_true")
    parser.add_argument("--require-clean-process-state", action="store_true")
    parser.add_argument("--enforce-assertions", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-report", action="store_true")
    parser.add_argument("--report-name", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.default_warmups < 0 or args.serena_project_warmups < 0:
        parser.error("warmup counts must be >= 0")
    if (
        args.default_repeats < 1
        or args.semantic_repeats < 1
        or args.serena_repeats < 1
        or args.serena_project_repeats < 1
        or args.project_model_repeats < 1
    ):
        parser.error("repeat counts must be >= 1")
    if (
        args.timeout <= 0
        or args.serena_timeout <= 0
        or args.serena_project_timeout <= 0
        or args.serena_project_step_timeout <= 0
        or args.gradle_timeout <= 0
        or args.step_timeout <= 0
    ):
        parser.error("timeouts must be > 0")
    if args.serena_project_port <= 0:
        parser.error("--serena-project-port must be > 0")

    steps = build_steps(args)
    if args.dry_run:
        for step in steps:
            print(f"{step.name}: {' '.join(step.argv)}")
        return 0

    for step in steps:
        code = run_step(step)
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
