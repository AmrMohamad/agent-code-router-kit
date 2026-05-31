#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import process_state_probe as process_probe  # noqa: E402

DEFAULT_MANIFEST = ROOT / "benchmarks" / "android" / "operational-gates.sample-b2b.tsv"
DEFAULT_SAMPLE_B2B_REPO = Path("/path/to/sample-repos/sample-b2b-android-app")
DEFAULT_PROJECT = "SampleWholesaleAndroid"
DEFAULT_CONTEXT_FILE = "feature-notifications/src/main/java/com/example/sample/features/notifications/SampleFeatureFragment.kt"
DEFAULT_SYMBOL_FILE = "feature-notifications/src/main/java/com/example/sample/features/notifications/SampleFeatureViewModel.kt"
DEFAULT_SYMBOL = "SampleFeatureViewModel"
DEFAULT_PACKAGE_BY_VARIANT = {
    "stagingDebug": "com.example.sampleb2b.staging",
    "productionDebug": "com.example.sampleb2b",
}
REQUIRED_COLUMNS = ["gate_id", "category", "tool", "expected_status", "required", "purpose"]
VALID_EXPECTED_STATUSES = {"pass", "warn", "fail", "passthrough", "probe", "disagreement"}
EXPECTED_GATES = {
    "process_state",
    "android_studio_check",
    "android_studio_analyze",
    "android_studio_declaration",
    "android_studio_usages",
    "serena_find_symbol",
    "serena_diagnostics",
    "serena_references",
    "project_model",
    "generated_sources",
    "high_fanout_guard",
    "assemble_staging_debug",
    "install_staging_debug",
    "launch_smoke",
}


@dataclass
class GateResult:
    gate_id: str
    category: str
    tool: str
    status: str
    level: str
    message: str
    wall_seconds: float
    details: dict[str, Any]


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def load_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise SystemExit(f"schema mismatch: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise SystemExit("manifest is empty")
    return rows


def validate_manifest(rows: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, start=2):
        for column in REQUIRED_COLUMNS:
            if not row.get(column):
                errors.append(f"line {index}: missing {column}")
        gate_id = row.get("gate_id", "")
        if gate_id in seen:
            errors.append(f"line {index}: duplicate gate_id {gate_id}")
        seen.add(gate_id)
        if row.get("required") not in {"yes", "no"}:
            errors.append(f"line {index}: required must be yes or no")
        if row.get("expected_status") not in VALID_EXPECTED_STATUSES:
            errors.append(f"line {index}: invalid expected_status {row.get('expected_status')!r}")
    missing = sorted(EXPECTED_GATES - seen)
    if missing:
        errors.append(f"manifest missing expected gates: {','.join(missing)}")
    return errors


def manifest_by_gate(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {row["gate_id"]: row for row in rows}


def run_command(argv: list[str], cwd: Path, timeout: float, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                stdout, stderr = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                stdout, stderr = proc.communicate(timeout=10)
            timed_out = True
        exit_code = proc.returncode if proc.returncode is not None else 124
    except FileNotFoundError as exc:
        stdout = ""
        stderr = str(exc)
        timed_out = False
        exit_code = 127
    wall = time.perf_counter() - started
    combined = f"{stdout}{stderr}"
    return {
        "argv": argv,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "stdout": stdout,
        "stderr": stderr,
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
        "line_count": len(combined.splitlines()),
    }


def variant_suffix(variant: str) -> str:
    return variant[:1].upper() + variant[1:]


def package_for_variant(variant: str, override: str | None = None) -> str:
    if override:
        return override
    return DEFAULT_PACKAGE_BY_VARIANT.get(variant, "com.example.sampleb2b.staging")


def gradle_env() -> dict[str, str]:
    env = dict(os.environ)
    preview_jbr = Path("/Applications/Android Studio Preview.app/Contents/jbr/Contents/Home")
    if preview_jbr.exists():
        env["JAVA_HOME"] = str(preview_jbr)
    return env


def make_gate(
    gate_id: str,
    category: str,
    tool: str,
    status: str,
    message: str,
    wall_seconds: float = 0.0,
    details: dict[str, Any] | None = None,
) -> GateResult:
    level = "pass" if status in {"pass", "passthrough"} else "warn" if status in {"warn", "disagreement"} else "fail"
    return GateResult(gate_id, category, tool, status, level, message, wall_seconds, details or {})


def process_state_gate(
    require_clean: bool,
    target_project_path: Path,
    expected_serena_mcp_count: int,
    allow_http_serena_server: bool,
    allow_other_project_serena: bool,
) -> GateResult:
    summary = process_probe.build_summary(
        process_probe.process_table(),
        target_project_path=str(target_project_path),
        expected_serena_mcp_count=expected_serena_mcp_count,
        allow_http_serena_server=allow_http_serena_server,
        allow_other_project_serena=allow_other_project_serena,
    )
    counts = dict(summary["counts"])
    classification_counts = dict(summary.get("classification_counts", {}))
    stale = summary.get("status") != "clean"
    details = {
        "counts": counts,
        "classification_counts": classification_counts,
        "target_project_path": str(target_project_path),
        "expected_serena_mcp_count": expected_serena_mcp_count,
        "allow_http_serena_server": allow_http_serena_server,
        "allow_other_project_serena": allow_other_project_serena,
        "target_serena_mcp_count": summary.get("target_serena_mcp_count"),
        "other_project_serena_mcp_count": summary.get("other_project_serena_mcp_count"),
        "unknown_serena_mcp_count": summary.get("unknown_serena_mcp_count"),
        "process_state_status": summary.get("status"),
    }
    if stale and require_clean:
        return make_gate("process_state", "process", "serena_process_scan", "fail", "Process state is not clean.", details=details)
    if stale:
        return make_gate(
            "process_state",
            "process",
            "serena_process_scan",
            "warn",
            "Process state has stale-session risk; run repair-serena-android-sessions.sh --dry-run before strict mode.",
            details=details,
        )
    return make_gate("process_state", "process", "serena_process_scan", "pass", "Process state is clean.", details=details)


def studio_gate(repo: Path, project: str, context_file: str, symbol: str, timeout: float) -> list[GateResult]:
    context_path = repo / context_file
    commands = [
        ("android_studio_check", ["android", "studio", "check"], lambda r: project in r["stdout"] and "READY" in r["stdout"]),
        (
            "android_studio_analyze",
            ["android", "studio", "analyze-file", "--project", project, context_file],
            lambda r: "No issues found" in r["stdout"] or "Analyzing file:" in r["stdout"],
        ),
        (
            "android_studio_declaration",
            ["android", "studio", "find-declaration", "--project", project, "--short", "--context-file", str(context_path), symbol],
            lambda r: r["exit_code"] == 0 and ".kt:" in r["stdout"],
        ),
        (
            "android_studio_usages",
            ["android", "studio", "find-usages", "--project", project, "--short", symbol],
            lambda r: r["exit_code"] == 0 and ".kt:" in r["stdout"],
        ),
    ]
    results: list[GateResult] = []
    for gate_id, argv, predicate in commands:
        result = run_command(argv, repo, timeout)
        status = "pass" if not result["timed_out"] and predicate(result) else "fail"
        results.append(
            make_gate(
                gate_id,
                "studio",
                "android studio",
                status,
                "Android Studio semantic probe passed." if status == "pass" else "Android Studio semantic probe failed.",
                float(result["wall_seconds"]),
                {
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "stdout_preview": str(result["stdout"])[:500],
                    "stderr_preview": str(result["stderr"])[:500],
                },
            )
        )
    return results


def run_serena_cases(repo: Path, output_root: Path, timeout: float, port: int, repeats: int) -> list[GateResult]:
    with tempfile.TemporaryDirectory() as raw:
        cases = Path(raw) / "serena-stable.tsv"
        cases.write_text(
            "\t".join(
                [
                    "case_id",
                    "repo",
                    "project",
                    "tool_name",
                    "tool_params_json",
                    "expected_status",
                    "min_byte_count",
                    "purpose",
                ]
            )
            + "\n"
            + "\n".join(
                [
                    "\t".join(
                        [
                            "serena_find_symbol",
                            "sample_b2b_android",
                            "sample-b2b-android-app",
                            "find_symbol",
                            json.dumps(
                                {
                                    "name_path_pattern": DEFAULT_SYMBOL,
                                    "relative_path": DEFAULT_SYMBOL_FILE,
                                    "include_body": False,
                                    "depth": 1,
                                    "max_matches": 5,
                                    "max_answer_chars": 6000,
                                },
                                separators=(",", ":"),
                            ),
                            "pass",
                            "500",
                            "Find SampleFeatureViewModel through Serena.",
                        ]
                    ),
                    "\t".join(
                        [
                            "serena_diagnostics",
                            "sample_b2b_android",
                            "sample-b2b-android-app",
                            "get_diagnostics_for_file",
                            json.dumps(
                                {
                                    "relative_path": DEFAULT_SYMBOL_FILE,
                                    "min_severity": 2,
                                    "max_answer_chars": 6000,
                                },
                                separators=(",", ":"),
                            ),
                            "pass",
                            "2",
                            "Get diagnostics for SampleFeatureViewModel through Serena.",
                        ]
                    ),
                    "\t".join(
                        [
                            "serena_references",
                            "sample_b2b_android",
                            "sample-b2b-android-app",
                            "find_referencing_symbols",
                            json.dumps(
                                {
                                    "name_path": DEFAULT_SYMBOL,
                                    "relative_path": DEFAULT_SYMBOL_FILE,
                                    "max_answer_chars": 6000,
                                },
                                separators=(",", ":"),
                            ),
                            "probe",
                            "0",
                            "Record whether Serena references agree with Studio usages.",
                        ]
                    ),
                ]
            )
            + "\n"
        )
        argv = [
            sys.executable,
            str(ROOT / "scripts" / "benchmarks" / "serena_project_server_probe.py"),
            "--validate",
            "--run",
            "--cases",
            str(cases),
            "--repo",
            f"sample_b2b_android={repo}",
            "--output",
            str(output_root / "serena-stable" / stamp()),
            "--warmups",
            "0",
            "--repeats",
            str(repeats),
            "--timeout",
            str(timeout),
            "--port",
            str(port),
        ]
        proc = run_command(argv, ROOT, timeout + 90)
    summary_files = sorted((output_root / "serena-stable").glob("serena-project-server-summary-*.json"))
    if not summary_files:
        summary_files = sorted((output_root / "serena-stable").glob("*/serena-project-server-summary-*.json"))
    summary_by_case: dict[str, dict[str, Any]] = {}
    if summary_files:
        for item in json.loads(summary_files[-1].read_text()):
            summary_by_case[str(item["case_id"])] = item
    results: list[GateResult] = []
    for gate_id in ["serena_find_symbol", "serena_diagnostics", "serena_references"]:
        item = summary_by_case.get(gate_id, {})
        statuses = item.get("statuses", [])
        if not item:
            status = "fail"
            message = f"Serena case {gate_id} did not produce a summary row."
        elif gate_id == "serena_references" and item.get("last_byte_count", 0) <= 5:
            status = "disagreement"
            message = "Serena references returned empty/near-empty output; compare with Android Studio usages."
        else:
            passed = "pass" in statuses or gate_id == "serena_references"
            status = "pass" if passed else "fail"
            message = f"Serena case {gate_id} status={statuses or 'missing'}."
        results.append(
            make_gate(
                gate_id,
                "semantic",
                "serena project server",
                status,
                message,
                float(item.get("median_wall_seconds", proc["wall_seconds"])),
                {
                    "suite_exit_code": proc["exit_code"],
                    "suite_timed_out": proc["timed_out"],
                    "summary": item,
                    "stdout_preview": str(proc["stdout"])[:500],
                    "stderr_preview": str(proc["stderr"])[:500],
                },
            )
        )
    return results


def run_subprobe(argv: list[str], output_dir: Path, timeout: float) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proc = run_command(argv, ROOT, timeout)
    json_files = sorted(output_dir.glob("*.json"))
    summaries = [path for path in json_files if "assertions" not in path.name]
    assertions = [path for path in json_files if "assertions" in path.name]
    summary = json.loads(summaries[-1].read_text()) if summaries else {}
    assertion_payload = json.loads(assertions[-1].read_text()) if assertions else {"summary": {"fail": 1}}
    return proc, summary, assertion_payload


def generated_gate(repo: Path, output_root: Path, timeout: float) -> GateResult:
    output = output_root / "generated-source" / stamp()
    proc, summary, assertions = run_subprobe(
        [
            sys.executable,
            str(ROOT / "scripts" / "benchmarks" / "android_generated_source_probe.py"),
            "--validate",
            "--run",
            "--repo",
            str(repo),
            "--output",
            str(output),
        ],
        output,
        timeout,
    )
    fail_count = int(assertions.get("summary", {}).get("fail", 1))
    return make_gate(
        "generated_sources",
        "generated",
        "generated source probe",
        "pass" if fail_count == 0 else "fail",
        "Generated-source readiness probe completed.",
        float(proc["wall_seconds"]),
        {"summary": summary, "assertions": assertions},
    )


def high_fanout_gate(repo: Path, output_root: Path, timeout: float) -> GateResult:
    output = output_root / "high-fanout" / stamp()
    proc, summary, assertions = run_subprobe(
        [
            sys.executable,
            str(ROOT / "scripts" / "benchmarks" / "android_high_fanout_summary.py"),
            "--validate",
            "--run",
            "--repo",
            str(repo),
            "--output",
            str(output),
        ],
        output,
        timeout,
    )
    fail_count = int(assertions.get("summary", {}).get("fail", 1))
    return make_gate(
        "high_fanout_guard",
        "summary",
        "high fanout summary",
        "pass" if fail_count == 0 else "fail",
        "High-fanout summary probe completed without raw dumps.",
        float(proc["wall_seconds"]),
        {"summary": summary, "assertions": assertions},
    )


def gradle_gate(repo: Path, variant: str, timeout: float, install: bool) -> list[GateResult]:
    suffix = variant_suffix(variant)
    tasks = [("project_model", "help", ["./gradlew", "help", "--no-daemon"])]
    tasks.append((f"assemble_{variant.lower()}", f"assemble{suffix}", ["./gradlew", f":app:assemble{suffix}", "--no-daemon"]))
    if install:
        tasks.append((f"install_{variant.lower()}", f"install{suffix}", ["./gradlew", f":app:install{suffix}", "--no-daemon"]))
    results: list[GateResult] = []
    env = gradle_env()
    for gate_id, task_name, argv in tasks:
        result = run_command(argv, repo, timeout, env=env)
        status = "pass" if result["exit_code"] == 0 and not result["timed_out"] else "fail"
        canonical_gate = gate_id
        if gate_id == f"assemble_{variant.lower()}":
            canonical_gate = "assemble_staging_debug" if variant == "stagingDebug" else gate_id
        if gate_id == f"install_{variant.lower()}":
            canonical_gate = "install_staging_debug" if variant == "stagingDebug" else gate_id
        results.append(
            make_gate(
                canonical_gate,
                "gradle" if task_name == "help" else "build" if task_name.startswith("assemble") else "runtime",
                f"gradle {task_name}",
                status,
                f"Gradle task {task_name} {'passed' if status == 'pass' else 'failed'}.",
                float(result["wall_seconds"]),
                {
                    "exit_code": result["exit_code"],
                    "timed_out": result["timed_out"],
                    "stdout_tail": str(result["stdout"])[-1200:],
                    "stderr_tail": str(result["stderr"])[-1200:],
                },
            )
        )
    return results


def launch_activity_visible(package_name: str, activity_text: str) -> bool:
    return package_name in activity_text and ("visible=true" in activity_text or "topResumedActivity" in activity_text)


def launch_gate(repo: Path, device: str, package_name: str, timeout: float) -> GateResult:
    launch = run_command(["adb", "-s", device, "shell", "monkey", "-p", package_name, "1"], repo, timeout)
    pid = run_command(["adb", "-s", device, "shell", "pidof", package_name], repo, timeout)
    activity = run_command(["adb", "-s", device, "shell", "dumpsys", "activity", "activities"], repo, timeout)
    logcat = run_command(["adb", "-s", device, "logcat", "-d", "-t", "120"], repo, timeout)
    activity_text = str(activity["stdout"])
    activity_visible = launch_activity_visible(package_name, activity_text)
    launched = launch["exit_code"] == 0 and (bool(str(pid["stdout"]).strip()) or activity_visible)
    return make_gate(
        "launch_smoke",
        "runtime",
        "adb monkey",
        "passthrough" if launched else "fail",
        "App launch smoke captured; no business-flow correctness is claimed." if launched else "App launch smoke failed.",
        float(launch["wall_seconds"]) + float(pid["wall_seconds"]) + float(logcat["wall_seconds"]),
        {
            "package": package_name,
            "device": device,
            "launch_exit_code": launch["exit_code"],
            "pidof": str(pid["stdout"]).strip(),
            "activity_visible": activity_visible,
            "logcat_line_count": int(logcat["line_count"]),
            "logcat_byte_count": int(logcat["byte_count"]),
            "stdout_preview": str(launch["stdout"])[:500],
            "stderr_preview": str(launch["stderr"])[:500],
            "activity_preview": activity_text[:1000],
        },
    )


def expected_status_ok(expected: str, actual_status: str, actual_level: str) -> bool:
    if expected == "probe":
        return actual_level != "fail"
    if expected == "pass":
        return actual_level == "pass"
    if expected == "warn":
        return actual_level in {"pass", "warn"}
    return expected == actual_status or expected == actual_level


def apply_manifest_policy(results: list[GateResult], manifest_rows: list[dict[str, str]]) -> tuple[list[GateResult], list[dict[str, Any]]]:
    manifest = manifest_by_gate(manifest_rows)
    by_gate = {item.gate_id: item for item in results}
    policy_assertions: list[dict[str, Any]] = []
    adjusted = list(results)

    for gate_id, row in manifest.items():
        result = by_gate.get(gate_id)
        if result is None:
            policy_assertions.append(
                {
                    "status": "fail",
                    "check": "manifest_gate_present",
                    "message": f"required={row['required']} gate={gate_id} missing",
                }
            )
            if row["required"] == "yes":
                adjusted.append(
                    make_gate(
                        gate_id,
                        row["category"],
                        row["tool"],
                        "fail",
                        "Required manifest gate did not run.",
                    )
                )
            continue
        expected_ok = expected_status_ok(row["expected_status"], result.status, result.level)
        required_ok = row["required"] != "yes" or result.level != "fail"
        policy_assertions.append(
            {
                "status": "pass" if expected_ok and required_ok else "fail",
                "check": "manifest_policy",
                "message": (
                    f"gate={gate_id} expected={row['expected_status']} "
                    f"actual_status={result.status} actual_level={result.level} required={row['required']}"
                ),
            }
        )
        if not expected_ok and row["required"] == "yes" and result.level != "fail":
            adjusted[adjusted.index(result)] = make_gate(
                result.gate_id,
                result.category,
                result.tool,
                "fail",
                f"Manifest policy failed: expected {row['expected_status']} but got {result.status}/{result.level}.",
                result.wall_seconds,
                result.details,
            )
    return adjusted, policy_assertions


def write_outputs(
    output_root: Path,
    results: list[GateResult],
    manifest_rows: list[dict[str, str]],
    enforce: bool,
) -> tuple[Path, Path, dict[str, int]]:
    output_root.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    rows_path = output_root / f"android-operational-gates-{run_id}.tsv"
    summary_path = output_root / f"android-operational-summary-{run_id}.json"
    results, policy_assertions = apply_manifest_policy(results, manifest_rows)
    rows = [
        {
            "gate_id": item.gate_id,
            "category": item.category,
            "tool": item.tool,
            "status": item.status,
            "level": item.level,
            "message": item.message,
            "wall_seconds": f"{item.wall_seconds:.6f}",
            "details_json": json.dumps(item.details, sort_keys=True),
        }
        for item in results
    ]
    with rows_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    counts = {
        "pass": sum(1 for item in results if item.level == "pass"),
        "warn": sum(1 for item in results if item.level == "warn"),
        "fail": sum(1 for item in results if item.level == "fail"),
    }
    summary = {
        "created_at": utc_now(),
        "overall_status": "pass" if counts["fail"] == 0 else "fail",
        "enforce_assertions": enforce,
        "summary": counts,
        "gates": rows,
        "manifest_policy": {
            "summary": {
                "pass": sum(1 for item in policy_assertions if item["status"] == "pass"),
                "fail": sum(1 for item in policy_assertions if item["status"] == "fail"),
            },
            "assertions": policy_assertions,
        },
        "boundary": "Launch smoke does not claim business-flow correctness.",
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {rows_path}")
    print(f"Wrote {summary_path}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}")
    return rows_path, summary_path, counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run an Android operational gate. "
            "This is app-level build/install/launch smoke, not a global completion claim."
        )
    )
    parser.add_argument("--sample-b2b-repo", default=str(DEFAULT_SAMPLE_B2B_REPO))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output", default="results/android/operational")
    parser.add_argument("--project", default=DEFAULT_PROJECT)
    parser.add_argument("--context-file", default=DEFAULT_CONTEXT_FILE)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--variant", default="stagingDebug")
    parser.add_argument("--package-name", default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--gradle-timeout", type=float, default=900.0)
    parser.add_argument("--serena-port", type=int, default=24492)
    parser.add_argument("--serena-repeats", type=int, default=3)
    parser.add_argument("--require-clean-process-state", action="store_true")
    parser.add_argument("--expected-serena-mcp-count", type=int, default=1)
    parser.add_argument("--allow-http-serena-server", action="store_true")
    parser.add_argument("--allow-other-project-serena", action="store_true")
    parser.add_argument("--skip-build-install", action="store_true")
    parser.add_argument("--skip-launch", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    repo = Path(args.sample_b2b_repo).expanduser().resolve()
    manifest = Path(args.manifest).expanduser().resolve()
    rows = load_manifest(manifest)
    errors = validate_manifest(rows)
    if not args.validate_only:
        if not repo.exists():
            errors.append(f"repo path missing: {repo}")
        if not (repo / args.context_file).exists():
            errors.append(f"context file missing: {repo / args.context_file}")
    if args.timeout <= 0 or args.gradle_timeout <= 0:
        errors.append("timeouts must be > 0")
    if args.serena_port <= 0:
        errors.append("--serena-port must be > 0")
    if args.serena_repeats < 1:
        errors.append("--serena-repeats must be >= 1")
    if args.expected_serena_mcp_count < 0:
        errors.append("--expected-serena-mcp-count must be >= 0")
    if errors:
        raise SystemExit("\n".join(errors))
    print("VALIDATION PASSED: Android Sample B2B operational hardening gate")
    if args.validate_only:
        return 0

    output_root = Path(args.output).expanduser().resolve()
    results: list[GateResult] = [
        process_state_gate(
            args.require_clean_process_state,
            repo,
            args.expected_serena_mcp_count,
            args.allow_http_serena_server,
            args.allow_other_project_serena,
        )
    ]
    results.extend(studio_gate(repo, args.project, args.context_file, args.symbol, args.timeout))
    results.extend(run_serena_cases(repo, output_root, args.timeout, args.serena_port, args.serena_repeats))
    results.append(generated_gate(repo, output_root, args.timeout))
    results.append(high_fanout_gate(repo, output_root, args.timeout))
    if not args.skip_build_install:
        results.extend(gradle_gate(repo, args.variant, args.gradle_timeout, install=True))
    if not args.skip_launch:
        results.append(launch_gate(repo, args.device, package_for_variant(args.variant, args.package_name or None), args.timeout))
    _, _, counts = write_outputs(output_root, results, rows, args.enforce_assertions)
    if args.enforce_assertions and counts["fail"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
