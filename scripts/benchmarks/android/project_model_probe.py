#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


REQUIRED_COLUMNS = ["case_id", "repo", "expected_status", "purpose"]
VALID_STATUSES = {
    "pass",
    "missing-local-properties",
    "missing-gradle",
    "timeout",
    "gradle-error",
    "error",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def load_cases(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise SystemExit(f"schema mismatch: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise SystemExit("case manifest is empty")
    return rows


def parse_repo_args(values: list[str]) -> dict[str, Path]:
    repos: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--repo must be name=/path, got {value!r}")
        name, raw = value.split("=", 1)
        repos[name] = Path(raw).expanduser().resolve()
    return repos


def validate(cases: list[dict[str, str]], repos: dict[str, Path], require_repos: bool) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(cases, start=2):
        for col in REQUIRED_COLUMNS:
            if col not in row or not row[col]:
                errors.append(f"line {index}: missing {col}")
        case_id = row.get("case_id", "")
        if case_id in seen:
            errors.append(f"line {index}: duplicate case_id {case_id}")
        seen.add(case_id)
        expected = row.get("expected_status", "")
        if expected not in VALID_STATUSES:
            errors.append(f"line {index}: invalid expected_status {expected!r}")
        if require_repos:
            repo = row.get("repo", "")
            if repo not in repos:
                errors.append(f"line {index}: repo {repo!r} not provided")
            elif not repos[repo].exists():
                errors.append(f"line {index}: repo path missing: {repos[repo]}")
    return errors


def read_properties(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def required_local_property_keys(repo: Path) -> list[str]:
    patterns = [
        re.compile(r'getPropertyFromLocalPropertiesFile\("([^"]+)"\)'),
        re.compile(r"getPropertyFromLocalPropertiesFile\('([^']+)'\)"),
        re.compile(r'getProperty\("([^"]+)"\)\s*\?:\s*(?:error|throw).*local\.properties'),
        re.compile(r"getProperty\('([^']+)'\)\s*\?:\s*(?:error|throw).*local\.properties"),
    ]
    required: set[str] = set()
    for path in repo.rglob("*"):
        if path.is_dir():
            continue
        if "build" in path.parts or ".gradle" in path.parts:
            continue
        if path.suffix not in {".kt", ".kts"}:
            continue
        text = path.read_text(errors="replace")
        for pattern in patterns:
            required.update(pattern.findall(text))
    return sorted(required)


def wrapper_distribution(repo: Path) -> dict[str, str]:
    props = read_properties(repo / "gradle" / "wrapper" / "gradle-wrapper.properties")
    raw_url = props.get("distributionUrl", "").replace("\\:", ":")
    zip_name = raw_url.rsplit("/", 1)[-1] if raw_url else ""
    dist_name = zip_name.removesuffix(".zip")
    version_name = dist_name.removesuffix("-bin")
    return {
        "distribution_url": raw_url,
        "zip_name": zip_name,
        "dist_name": dist_name,
        "version_name": version_name,
    }


def cached_gradle_executable(repo: Path) -> Path | None:
    dist = wrapper_distribution(repo)
    dist_name = dist["dist_name"]
    version_name = dist["version_name"]
    if not dist_name or not version_name:
        return None
    root = Path.home() / ".gradle" / "wrapper" / "dists" / dist_name
    matches = sorted(root.glob(f"*/{version_name}/bin/gradle"))
    return matches[0] if matches else None


def gradle_wrapper_status(repo: Path) -> str:
    wrapper = repo / "gradlew"
    if wrapper.exists() and wrapper.stat().st_mode & 0o111:
        return "wrapper-executable"
    if wrapper.exists():
        return "wrapper-not-executable"
    if (repo / "gradle" / "wrapper" / "gradle-wrapper.properties").exists():
        return "wrapper-script-missing"
    return "wrapper-missing"


def gradle_command(repo: Path) -> tuple[list[str] | None, str]:
    wrapper = repo / "gradlew"
    if wrapper.exists() and wrapper.stat().st_mode & 0o111:
        return [str(wrapper), "help", "--no-daemon"], "wrapper"
    cached = cached_gradle_executable(repo)
    if cached:
        return [str(cached), "help", "--no-daemon"], "cached-wrapper-distribution"
    system_gradle = shutil.which("gradle")
    if system_gradle:
        return [system_gradle, "help", "--no-daemon"], "system-gradle"
    return None, "missing"


def classify(
    exit_code: int,
    stdout: str,
    stderr: str,
    timed_out: bool,
    missing_keys: list[str],
    argv: list[str] | None,
) -> str:
    text = f"{stdout}\n{stderr}"
    if missing_keys:
        return "missing-local-properties"
    if not argv:
        return "missing-gradle"
    if timed_out:
        return "timeout"
    if exit_code == 0:
        return "pass"
    if "local.properties" in text and "not found" in text:
        return "missing-local-properties"
    if "BUILD FAILED" in text or exit_code != 0:
        return "gradle-error"
    return "error"


def execute(row: dict[str, str], repo: Path, timeout: float, run_gradle: bool) -> dict[str, object]:
    local_values = read_properties(repo / "local.properties")
    required_keys = required_local_property_keys(repo)
    missing_keys = sorted(set(required_keys) - set(local_values))
    dist = wrapper_distribution(repo)
    cached = cached_gradle_executable(repo)
    argv, command_source = gradle_command(repo)
    wrapper_status = gradle_wrapper_status(repo)
    started = time.perf_counter()
    stdout = ""
    stderr = ""
    exit_code = 0
    timed_out = False

    if run_gradle and argv:
        try:
            proc = subprocess.run(
                argv,
                cwd=repo,
                shell=False,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
            stdout = proc.stdout
            stderr = proc.stderr
            exit_code = proc.returncode
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            exit_code = 124
            timed_out = True
    wall = time.perf_counter() - started
    combined = f"{stdout}{stderr}"
    preflight = {
        "required_local_properties": required_keys,
        "present_local_properties": sorted(local_values),
        "missing_local_properties": missing_keys,
        "gradle_distribution": dist,
        "gradle_wrapper_status": wrapper_status,
        "cached_gradle_executable": str(cached) if cached else "",
        "selected_command_source": command_source,
        "selected_command": argv or [],
        "ran_gradle": run_gradle and bool(argv),
    }
    status = classify(exit_code, stdout, stderr, timed_out, missing_keys, argv)
    return {
        "status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "line_count": len(combined.splitlines()),
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
        "stdout": stdout,
        "stderr": stderr,
        "preflight": preflight,
    }


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("_")


def run(args: argparse.Namespace, cases: list[dict[str, str]], repos: dict[str, Path]) -> int:
    output_root = Path(args.output).expanduser().resolve()
    run_id = stamp()
    raw_dir = output_root / "raw" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    preflights: list[dict[str, object]] = []

    for pass_index in range(1, args.repeats + 1):
        for row in cases:
            result = execute(row, repos[row["repo"]], args.timeout, args.run_gradle)
            base = safe_name(f"{row['repo']}_{row['case_id']}_pass{pass_index}")
            stdout_path = raw_dir / f"{base}.stdout"
            stderr_path = raw_dir / f"{base}.stderr"
            stdout_path.write_text(str(result["stdout"]))
            stderr_path.write_text(str(result["stderr"]))
            preflight = dict(result["preflight"])
            preflight.update({"repo": row["repo"], "case_id": row["case_id"], "pass_index": pass_index})
            preflights.append(preflight)
            rows.append(
                {
                    "pass_index": pass_index,
                    "repo": row["repo"],
                    "case_id": row["case_id"],
                    "expected_status": row["expected_status"],
                    "purpose": row["purpose"],
                    "status": result["status"],
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "wall_seconds": f"{float(result['wall_seconds']):.6f}",
                    "line_count": result["line_count"],
                    "byte_count": result["byte_count"],
                    "estimated_tokens": result["estimated_tokens"],
                    "missing_local_properties": ",".join(preflight["missing_local_properties"]),
                    "gradle_distribution": preflight["gradle_distribution"]["dist_name"],
                    "gradle_wrapper_status": preflight["gradle_wrapper_status"],
                    "cached_gradle_executable": preflight["cached_gradle_executable"],
                    "selected_command_source": preflight["selected_command_source"],
                    "ran_gradle": preflight["ran_gradle"],
                    "stdout_path": str(stdout_path),
                    "stderr_path": str(stderr_path),
                    "command_argv": json.dumps(preflight["selected_command"]),
                }
            )

    output_root.mkdir(parents=True, exist_ok=True)
    rows_path = output_root / f"android-project-model-{run_id}.tsv"
    summary_path = output_root / f"android-project-model-summary-{run_id}.json"
    assertions_path = output_root / f"android-project-model-assertions-{run_id}.json"
    preflight_path = output_root / f"android-project-model-preflight-{run_id}.json"

    fieldnames = [
        "pass_index",
        "repo",
        "case_id",
        "expected_status",
        "purpose",
        "status",
        "exit_code",
        "timed_out",
        "wall_seconds",
        "line_count",
        "byte_count",
        "estimated_tokens",
        "missing_local_properties",
        "gradle_distribution",
        "gradle_wrapper_status",
        "cached_gradle_executable",
        "selected_command_source",
        "ran_gradle",
        "stdout_path",
        "stderr_path",
        "command_argv",
    ]
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case_id"]), []).append(row)
    summary = []
    for case_id, group in sorted(grouped.items()):
        walls = [float(row["wall_seconds"]) for row in group]
        last = group[-1]
        summary.append(
            {
                "case_id": case_id,
                "repo": last["repo"],
                "statuses": sorted({str(row["status"]) for row in group}),
                "expected_status": last["expected_status"],
                "missing_local_properties": str(last["missing_local_properties"]).split(",")
                if last["missing_local_properties"]
                else [],
                "gradle_distribution": last["gradle_distribution"],
                "gradle_wrapper_status": last["gradle_wrapper_status"],
                "selected_command_source": last["selected_command_source"],
                "best_wall_seconds": min(walls),
                "median_wall_seconds": median(walls),
                "avg_wall_seconds": mean(walls),
                "last_byte_count": int(last["byte_count"]),
                "last_estimated_tokens": int(last["estimated_tokens"]),
                "ran_gradle": bool(last["ran_gradle"]),
            }
        )
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    preflight_path.write_text(json.dumps(preflights, indent=2, sort_keys=True) + "\n")

    assertions = []
    for row in rows:
        expected = str(row["expected_status"])
        status = str(row["status"])
        assertions.append(
            {
                "status": "pass" if status == expected else "fail",
                "check": "expected_status",
                "message": f"expected={expected} actual={status}",
                "context": {
                    "repo": row["repo"],
                    "case_id": row["case_id"],
                    "pass_index": row["pass_index"],
                },
            }
        )
        if status != "pass":
            assertions.append(
                {
                    "status": "warn",
                    "check": "project_model_not_ready",
                    "message": f"status={status}; missing={row['missing_local_properties']}",
                    "context": {
                        "repo": row["repo"],
                        "case_id": row["case_id"],
                        "pass_index": row["pass_index"],
                    },
                }
            )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    assertions_path.write_text(
        json.dumps(
            {
                "schema": "agent-code-router-kit.android-project-model-assertions.v1",
                "date_utc": utc_now(),
                "summary": counts,
                "assertions": assertions,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {preflight_path}")
    print(f"Wrote {assertions_path}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}")
    return 3 if args.enforce_assertions and counts["fail"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure Android Gradle project-model readiness.")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--repo", action="append", default=[], help="Repo mapping name=/path")
    parser.add_argument("--output", default="results/android/project-model")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--run-gradle", action="store_true", help="Run the selected Gradle help command.")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    if not args.validate and not args.run:
        parser.error("choose --validate and/or --run")
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    cases = load_cases(Path(args.cases))
    repos = parse_repo_args(args.repo)
    errors = validate(cases, repos, require_repos=args.run)
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 2
    if args.validate:
        print(f"VALIDATION PASSED: {len(cases)} cases")
    if args.run:
        return run(args, cases, repos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
