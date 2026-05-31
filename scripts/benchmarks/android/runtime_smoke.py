#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


def variant_suffix(variant: str) -> str:
    return variant[:1].upper() + variant[1:]


def variant_gate_suffix(variant: str) -> str:
    parts: list[str] = []
    current = ""
    for char in variant:
        if char.isupper() and current:
            parts.append(current.lower())
            current = char
        else:
            current += char
    if current:
        parts.append(current.lower())
    return "_".join(parts)


def gradle_task(module: str, task: str) -> str:
    normalized = module.strip()
    if not normalized:
        return task
    return f"{normalized}:{task}" if normalized.startswith(":") else f":{normalized}:{task}"


def gradle_env(device: str) -> dict[str, str]:
    env = dict(os.environ)
    preview_jbr = Path("/Applications/Android Studio Preview.app/Contents/jbr/Contents/Home")
    stable_jbr = Path("/Applications/Android Studio.app/Contents/jbr/Contents/Home")
    if preview_jbr.exists():
        env["JAVA_HOME"] = str(preview_jbr)
    elif stable_jbr.exists():
        env["JAVA_HOME"] = str(stable_jbr)
    if device:
        env["ANDROID_SERIAL"] = device
    return env


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
        "line_count": len(combined.splitlines()),
        "byte_count": len(combined.encode()),
        "estimated_tokens": estimate_tokens(combined),
    }


def command_gate(gate_id: str, category: str, tool: str, result: dict[str, Any], success_message: str, fail_message: str) -> dict[str, Any]:
    passed = result["exit_code"] == 0 and not result["timed_out"]
    level = "pass" if passed else "fail"
    return {
        "gate_id": gate_id,
        "category": category,
        "tool": tool,
        "status": "pass" if passed else "fail",
        "level": level,
        "message": success_message if passed else fail_message,
        "wall_seconds": f"{float(result['wall_seconds']):.6f}",
        "details_json": json.dumps(
            {
                "argv": result["argv"],
                "exit_code": result["exit_code"],
                "timed_out": result["timed_out"],
                "stdout_tail": str(result["stdout"])[-1200:],
                "stderr_tail": str(result["stderr"])[-1200:],
                "line_count": result["line_count"],
                "byte_count": result["byte_count"],
                "estimated_tokens": result["estimated_tokens"],
            },
            sort_keys=True,
        ),
    }


def launch_activity_visible(package_name: str, activity_text: str) -> bool:
    return package_name in activity_text and ("visible=true" in activity_text or "topResumedActivity" in activity_text)


def launch_gate(repo: Path, device: str, package_name: str, timeout: float) -> dict[str, Any]:
    launch = run_command(["adb", "-s", device, "shell", "monkey", "-p", package_name, "1"], repo, timeout)
    pid = run_command(["adb", "-s", device, "shell", "pidof", package_name], repo, timeout)
    activity = run_command(["adb", "-s", device, "shell", "dumpsys", "activity", "activities"], repo, timeout)
    activity_text = str(activity["stdout"])
    activity_visible = launch_activity_visible(package_name, activity_text)
    passed = launch["exit_code"] == 0 and not launch["timed_out"] and (bool(str(pid["stdout"]).strip()) or activity_visible)
    return {
        "gate_id": "launch_smoke",
        "category": "runtime",
        "tool": "adb monkey",
        "status": "passthrough" if passed else "fail",
        "level": "pass" if passed else "fail",
        "message": "App launch smoke captured; no business-flow correctness is claimed." if passed else "App launch smoke failed.",
        "wall_seconds": f"{float(launch['wall_seconds']) + float(pid['wall_seconds']) + float(activity['wall_seconds']):.6f}",
        "details_json": json.dumps(
            {
                "package": package_name,
                "device": device,
                "launch_exit_code": launch["exit_code"],
                "launch_timed_out": launch["timed_out"],
                "pidof": str(pid["stdout"]).strip(),
                "activity_visible": activity_visible,
                "stdout_preview": str(launch["stdout"])[:500],
                "stderr_preview": str(launch["stderr"])[:500],
                "activity_preview": activity_text[:1000],
            },
            sort_keys=True,
        ),
    }


def local_property_keys(repo: Path) -> list[str]:
    path = repo / "local.properties"
    if not path.exists():
        return []
    keys: list[str] = []
    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.append(stripped.split("=", 1)[0].strip())
    return sorted(keys)


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo).expanduser().resolve()
    suffix = variant_suffix(args.variant)
    gate_suffix = variant_gate_suffix(args.variant)
    env = gradle_env(args.device)
    gates: list[dict[str, Any]] = []

    help_result = run_command(["./gradlew", "help", "--no-daemon"], repo, args.gradle_timeout, env=env)
    gates.append(
        command_gate(
            "project_model",
            "gradle",
            "gradle help",
            help_result,
            "Gradle help passed.",
            "Gradle help failed.",
        )
    )

    if not args.skip_assemble:
        assemble_task = gradle_task(args.module, f"assemble{suffix}")
        assemble_result = run_command(["./gradlew", assemble_task, "--no-daemon"], repo, args.gradle_timeout, env=env)
        gates.append(
            command_gate(
                f"assemble_{gate_suffix}",
                "build",
                f"gradle {assemble_task}",
                assemble_result,
                f"Gradle task {assemble_task} passed.",
                f"Gradle task {assemble_task} failed.",
            )
        )

    if not args.skip_install:
        install_task = gradle_task(args.module, f"install{suffix}")
        install_result = run_command(["./gradlew", install_task, "--no-daemon"], repo, args.gradle_timeout, env=env)
        gates.append(
            command_gate(
                f"install_{gate_suffix}",
                "runtime",
                f"gradle {install_task}",
                install_result,
                f"Gradle task {install_task} passed.",
                f"Gradle task {install_task} failed.",
            )
        )

    if not args.skip_launch:
        gates.append(launch_gate(repo, args.device, args.package_name, args.timeout))

    counts = {
        "pass": sum(1 for gate in gates if gate["level"] == "pass"),
        "warn": sum(1 for gate in gates if gate["level"] == "warn"),
        "fail": sum(1 for gate in gates if gate["level"] == "fail"),
    }
    return {
        "schema": "agent-code-router-kit.android-runtime-smoke.v1",
        "created_at": utc_now(),
        "repo": str(repo),
        "module": args.module,
        "variant": args.variant,
        "device": args.device,
        "package_name": args.package_name,
        "local_property_keys": local_property_keys(repo),
        "overall_status": "pass" if counts["fail"] == 0 else "fail",
        "summary": counts,
        "gates": gates,
        "boundary": "Runtime launch smoke proves install/launch only; it does not claim business-flow correctness.",
    }


def validate_args(args: argparse.Namespace) -> list[str]:
    errors: list[str] = []
    repo = Path(args.repo).expanduser().resolve()
    if not repo.exists():
        errors.append(f"repo path missing: {repo}")
    if not (repo / "gradlew").exists():
        errors.append(f"gradlew missing: {repo / 'gradlew'}")
    if not args.variant:
        errors.append("--variant is required")
    if not args.package_name and not args.skip_launch:
        errors.append("--package-name is required unless --skip-launch is used")
    if args.timeout <= 0 or args.gradle_timeout <= 0:
        errors.append("timeouts must be > 0")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a generic Android build/install/launch runtime smoke.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--module", default=":android:app")
    parser.add_argument("--variant", default="stagingDebug")
    parser.add_argument("--device", default="emulator-5554")
    parser.add_argument("--package-name", default="")
    parser.add_argument("--output", default="results/android/stable-runtime-smoke")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--gradle-timeout", type=float, default=900.0)
    parser.add_argument("--skip-assemble", action="store_true")
    parser.add_argument("--skip-install", action="store_true")
    parser.add_argument("--skip-launch", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    errors = validate_args(args)
    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 2
    print("VALIDATION PASSED: Android runtime smoke")
    if args.validate_only:
        return 0

    summary = run_smoke(args)
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    summary_path = output / f"android-sample_retail-operational-summary-{run_id}.json"
    if "sample_retail" not in output.name:
        summary_path = output / f"android-runtime-smoke-summary-{run_id}.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    counts = summary["summary"]
    print(f"Wrote {summary_path}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}")
    if args.enforce_assertions and counts["fail"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
