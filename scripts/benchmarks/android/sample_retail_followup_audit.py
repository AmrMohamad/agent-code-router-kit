#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def latest_file(root: Path, pattern: str) -> Path | None:
    matches = sorted(root.glob(pattern))
    return matches[-1] if matches else None


def load_json(path: Path | None) -> Any:
    if path is None:
        return None
    return json.loads(path.read_text())


def summary_counts(assertions: dict[str, Any] | None) -> dict[str, int]:
    if not assertions:
        return {"pass": 0, "warn": 0, "fail": 0}
    raw = assertions.get("summary", {})
    return {
        "pass": int(raw.get("pass", 0)),
        "warn": int(raw.get("warn", 0)),
        "fail": int(raw.get("fail", 0)),
    }


def sample_retail_serena_stats(serena_summary: list[dict[str, Any]] | None) -> dict[str, int]:
    stats = {
        "find_symbol_pass": 0,
        "overview_pass": 0,
        "references_empty": 0,
        "diagnostics_empty": 0,
        "implementation_boundary": 0,
    }
    for item in serena_summary or []:
        if item.get("repo") != "sample_retail_android":
            continue
        statuses = set(item.get("statuses", []))
        tool = item.get("tool_name")
        if tool == "find_symbol" and statuses == {"pass"}:
            stats["find_symbol_pass"] += 1
        elif tool == "get_symbols_overview" and statuses == {"pass"}:
            stats["overview_pass"] += 1
        elif tool == "find_referencing_symbols" and "empty" in statuses:
            stats["references_empty"] += 1
        elif tool == "get_diagnostics_for_file" and "empty" in statuses:
            stats["diagnostics_empty"] += 1
        elif tool == "find_implementations" and "error" in statuses:
            stats["implementation_boundary"] += 1
    return stats


def project_model_pass(project_model_summary: list[dict[str, Any]] | None) -> bool:
    for item in project_model_summary or []:
        if item.get("repo") == "sample_retail_android" and item.get("statuses") == ["pass"]:
            return True
    return False


def process_state_counts(process_summary: dict[str, Any] | None) -> dict[str, int]:
    if not process_summary:
        return {}
    return {key: int(value) for key, value in process_summary.get("counts", {}).items()}


def process_state_has_stale_risk(process_summary: dict[str, Any] | None) -> bool:
    if not process_summary:
        return False
    if process_summary.get("status") == "clean":
        return False
    target_count = int(process_summary.get("target_serena_mcp_count", 0))
    unknown_count = int(process_summary.get("unknown_serena_mcp_count", 0))
    if target_count > int(process_summary.get("expected_serena_mcp_count", 1)):
        return True
    if unknown_count:
        return True
    counts = process_state_counts(process_summary)
    return int(counts.get("serena_mcp", 0)) > 1 or int(counts.get("kotlin_lsp", 0)) > 1


def studio_matrix_stats(studio_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not studio_summary:
        return {
            "status": "missing",
            "trusted_studio_layer": False,
            "case_count": 0,
            "declaration_pass_count": 0,
            "usage_pass_count": 0,
        }
    trusted = bool(studio_summary.get("trusted_studio_layer", False))
    return {
        "status": "pass" if trusted else "boundary",
        "trusted_studio_layer": trusted,
        "case_count": int(studio_summary.get("case_count", 0)),
        "declaration_pass_count": int(studio_summary.get("declaration_pass_count", 0)),
        "usage_pass_count": int(studio_summary.get("usage_pass_count", 0)),
        "classification_counts": studio_summary.get("classification_counts", {}),
    }


def operational_smoke_stats(operational_summary: dict[str, Any] | None) -> dict[str, Any]:
    if not operational_summary:
        return {
            "status": "missing",
            "build_install_launch_passed": False,
            "summary": {"pass": 0, "warn": 0, "fail": 0},
        }
    gates = operational_summary.get("gates", [])
    gate_status = {item.get("gate_id"): item.get("level") for item in gates if isinstance(item, dict)}
    required = ("assemble_debug", "assemble_staging_debug", "install_debug", "install_staging_debug", "launch_smoke")
    build_pass = any(gate_status.get(item) == "pass" for item in ("assemble_debug", "assemble_staging_debug"))
    install_pass = any(gate_status.get(item) == "pass" for item in ("install_debug", "install_staging_debug"))
    launch_pass = gate_status.get("launch_smoke") == "pass"
    summary = operational_summary.get("summary", {})
    passed = bool(build_pass and install_pass and launch_pass and int(summary.get("fail", 0)) == 0)
    return {
        "status": "pass" if passed else "boundary",
        "build_install_launch_passed": passed,
        "summary": summary,
        "gate_status": gate_status,
        "overall_status": operational_summary.get("overall_status"),
    }


def build_assertions(payload: dict[str, Any]) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []

    project_model_ok = project_model_pass(payload.get("project_model_summary"))
    assertions.append(
        {
            "status": "pass" if project_model_ok else "fail",
            "check": "sample_retail_project_model_help",
            "message": "Sample Retail Gradle help passed with the recorded timeout." if project_model_ok else "Sample Retail Gradle help did not pass.",
        }
    )

    generated_counts = summary_counts(payload.get("generated_assertions"))
    assertions.append(
        {
            "status": "pass" if generated_counts["fail"] == 0 and generated_counts["pass"] >= 4 else "fail",
            "check": "sample_retail_generated_source_discovery",
            "message": f"generated assertions={generated_counts}",
        }
    )

    high_fanout_counts = summary_counts(payload.get("high_fanout_assertions"))
    assertions.append(
        {
            "status": "pass" if high_fanout_counts["fail"] == 0 else "fail",
            "check": "sample_retail_high_fanout_summary",
            "message": f"high-fanout assertions={high_fanout_counts}",
        }
    )

    serena_stats = sample_retail_serena_stats(payload.get("serena_summary"))
    assertions.append(
        {
            "status": "pass" if serena_stats["find_symbol_pass"] >= 5 else "fail",
            "check": "sample_retail_serena_symbol_lookup",
            "message": f"find_symbol_pass={serena_stats['find_symbol_pass']}",
        }
    )
    assertions.append(
        {
            "status": "warn" if serena_stats["references_empty"] else "pass",
            "check": "sample_retail_serena_reference_boundary",
            "message": f"references_empty={serena_stats['references_empty']}",
        }
    )
    assertions.append(
        {
            "status": "warn" if serena_stats["diagnostics_empty"] else "pass",
            "check": "sample_retail_serena_diagnostics_boundary",
            "message": f"diagnostics_empty={serena_stats['diagnostics_empty']}",
        }
    )

    process_summary = payload.get("process_state_summary")
    process_counts = process_state_counts(process_summary)
    stale_risk = process_state_has_stale_risk(process_summary)
    assertions.append(
        {
            "status": "warn" if stale_risk else "pass",
            "check": "sample_retail_process_state",
            "message": f"process_counts={process_counts}",
        }
    )

    studio_stats = studio_matrix_stats(payload.get("sample_retail_studio_matrix_summary"))
    assertions.append(
        {
            "status": "pass" if studio_stats["trusted_studio_layer"] else "warn",
            "check": "sample_retail_studio_symbol_matrix",
            "message": (
                "Sample Retail Studio matrix trusted."
                if studio_stats["trusted_studio_layer"]
                else f"Sample Retail Studio matrix not yet trusted: {studio_stats}"
            ),
        }
    )

    runtime_stats = operational_smoke_stats(payload.get("sample_retail_operational_summary"))
    assertions.append(
        {
            "status": "pass" if runtime_stats["build_install_launch_passed"] else "warn",
            "check": "sample_retail_build_install_launch_smoke",
            "message": (
                "Sample Retail build/install/launch smoke passed."
                if runtime_stats["build_install_launch_passed"]
                else f"Sample Retail build/install/launch smoke not yet equivalent: {runtime_stats}"
            ),
        }
    )

    equivalent_operational = bool(
        project_model_ok
        and generated_counts["fail"] == 0
        and high_fanout_counts["fail"] == 0
        and serena_stats["find_symbol_pass"] >= 5
        and studio_stats["trusted_studio_layer"]
        and runtime_stats["build_install_launch_passed"]
    )
    assertions.append(
        {
            "status": "pass" if equivalent_operational else "warn",
            "check": "sample_retail_equivalent_operational_gate",
            "message": (
                "Sample Retail has equivalent operational proof."
                if equivalent_operational
                else "Sample Retail remains follow-up evidence, not equivalent operational proof."
            ),
        }
    )

    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions}


def default_paths(results_root: Path) -> dict[str, Path | None]:
    return {
        "project_model_summary": latest_file(results_root / "project-model", "android-project-model-summary-*.json"),
        "serena_summary": latest_file(results_root / "serena-project-server", "serena-project-server-summary-*.json"),
        "generated_summary": latest_file(results_root / "generated-sources-sample_retail", "android-generated-source-summary-*.json"),
        "generated_assertions": latest_file(results_root / "generated-sources-sample_retail", "android-generated-source-assertions-*.json"),
        "high_fanout_summary": latest_file(results_root / "high-fanout-summary-sample_retail", "android-high-fanout-summary-*.json"),
        "high_fanout_assertions": latest_file(results_root / "high-fanout-summary-sample_retail", "android-high-fanout-assertions-*.json"),
        "process_state_summary": latest_file(results_root / "process-state", "android-process-state-summary-*.json"),
        "sample_retail_studio_matrix_summary": latest_file(
            results_root / "studio-symbol-matrix-sample_retail",
            "android-studio-symbol-matrix-summary-*.json",
        ),
        "sample_retail_operational_summary": latest_file(
            results_root / "sample_retail-operational",
            "android-sample_retail-operational-summary-*.json",
        ),
    }


def load_payload(paths: dict[str, Path | None]) -> dict[str, Any]:
    payload = {key: load_json(path) for key, path in paths.items()}
    payload["input_paths"] = {key: str(path) if path else "" for key, path in paths.items()}
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Sample Retail stable follow-up evidence from existing Android benchmark artifacts.")
    parser.add_argument("--results-root", default="results/android")
    parser.add_argument("--output", default="results/android/sample_retail-followup")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    results_root = Path(args.results_root).expanduser().resolve()
    paths = default_paths(results_root)
    optional_inputs = {"sample_retail_studio_matrix_summary", "sample_retail_operational_summary"}
    missing = [key for key, path in paths.items() if path is None and key not in optional_inputs]
    if missing:
        print("MISSING INPUTS")
        for key in missing:
            print(f"- {key}")
        return 2

    payload = load_payload(paths)
    assertions = build_assertions(payload)
    run_id = stamp()
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / f"android-sample_retail-followup-summary-{run_id}.json"
    assertions_path = output / f"android-sample_retail-followup-assertions-{run_id}.json"
    summary = {
        "schema": "agent-code-router-kit.android-sample_retail-followup.v1",
        "date_utc": utc_now(),
        "status": (
            "followup-operational-equivalent"
            if any(item["check"] == "sample_retail_equivalent_operational_gate" and item["status"] == "pass" for item in assertions["assertions"])
            else "followup-pass-with-boundaries"
            if assertions["summary"]["fail"] == 0
            else "followup-failed"
        ),
        "assertions": assertions["summary"],
        "serena_stats": sample_retail_serena_stats(payload.get("serena_summary")),
        "process_counts": process_state_counts(payload.get("process_state_summary")),
        "studio_matrix": studio_matrix_stats(payload.get("sample_retail_studio_matrix_summary")),
        "runtime_smoke": operational_smoke_stats(payload.get("sample_retail_operational_summary")),
        "input_paths": payload["input_paths"],
    }
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n")
    counts = assertions["summary"]
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(f"Assertions: pass={counts['pass']}, warn={counts['warn']}, fail={counts['fail']}")
    print(f"Status: {summary['status']}")
    return 3 if args.enforce_assertions and counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
