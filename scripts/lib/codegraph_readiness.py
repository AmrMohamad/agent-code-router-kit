from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ReadinessCheck:
    name: str
    status: str
    message: str
    details: dict[str, Any]


def run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def tool_version(command: str, *args: str) -> tuple[str | None, str]:
    resolved = shutil.which(command)
    if not resolved:
        return None, ""
    completed = run([resolved, *args])
    output = (completed.stdout or completed.stderr).strip()
    return output or "available", resolved


def codegraph_readiness(target_repo: str | Path, *, gateway_command: str = "acr-codegraph-gateway") -> dict[str, Any]:
    repo = Path(target_repo).expanduser().resolve()
    checks: list[ReadinessCheck] = []
    compat_manifest = Path(__file__).resolve().parents[2] / "packages" / "codegraph-gateway" / "compat" / "codegraph-tools-v1.json"
    compat_payload = json.loads(compat_manifest.read_text(encoding="utf-8")) if compat_manifest.exists() else {}
    codegraph_version, codegraph_path = tool_version("codegraph", "--version")
    checks.append(
        ReadinessCheck(
            "codegraph_executable",
            "pass" if codegraph_version else "fail",
            "CodeGraph executable is available." if codegraph_version else "CodeGraph executable was not found on PATH.",
            {"version": codegraph_version or "", "path": codegraph_path or ""},
        )
    )
    gateway_version, gateway_path = tool_version(gateway_command, "--help")
    checks.append(
        ReadinessCheck(
            "gateway_executable",
            "pass" if gateway_version else "warn",
            "Gateway executable is available." if gateway_version else "Gateway executable was not found on PATH.",
            {"path": gateway_path or ""},
        )
    )
    checks.append(
        ReadinessCheck(
            "target_repo",
            "pass" if repo.exists() and repo.is_dir() else "fail",
            "Target repository exists." if repo.exists() and repo.is_dir() else "Target repository was not found.",
            {"target_repo": str(repo)},
        )
    )
    index_dir = repo / ".codegraph"
    checks.append(
        ReadinessCheck(
            "index_directory",
            "pass" if index_dir.exists() and index_dir.is_dir() else "warn",
            ".codegraph index directory is present." if index_dir.exists() and index_dir.is_dir() else ".codegraph index directory is missing.",
            {"path": str(index_dir)},
        )
    )
    checks.append(
        ReadinessCheck(
            "compat_manifest",
            "pass" if compat_manifest.exists() else "fail",
            "Compatibility manifest is present." if compat_manifest.exists() else "Compatibility manifest is missing.",
            {
                "path": str(compat_manifest),
                "required_tools": compat_payload.get("required_tools", []),
                "tested_codegraph_versions": compat_payload.get("tested_codegraph_versions", []),
                "contract_capture_status": compat_payload.get("contract_capture_status", ""),
            },
        )
    )
    if compat_manifest.exists() and not compat_payload.get("tested_codegraph_versions"):
        checks.append(
            ReadinessCheck(
                "live_provider_capture",
                "warn",
                "No live CodeGraph provider version has been captured in the compatibility manifest yet.",
                {"manifest_path": str(compat_manifest)},
            )
        )
    payload = {
        "target_repo": str(repo),
        "checks": [asdict(check) for check in checks],
        "ready": all(check.status == "pass" for check in checks if check.name in {"codegraph_executable", "target_repo"}),
    }
    return payload


def readiness_text(report: dict[str, Any]) -> str:
    lines = [f"Target repo: {report['target_repo']}"]
    for item in report["checks"]:
        lines.append(f"[{item['status']}] {item['name']}: {item['message']}")
    return "\n".join(lines)
