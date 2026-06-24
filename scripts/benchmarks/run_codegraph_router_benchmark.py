#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib.codegraph_treatment_config import codegraph_treatment_for_arm, public_codegraph_factor_payload, validate_codegraph_arm_set


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STUDY = ROOT / "benchmarks" / "real-agent-routing" / "studies" / "codegraph-router-v1" / "study.yaml"
TEMPLATE_ROOT = ROOT / "templates" / "codegraph"


def parse_study_yaml(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        data[key.strip()] = value.strip()
    return data


def ensure_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | 0o111)


def write_codegraph_shim(path: Path, *, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/usr/bin/env bash\nprintf '%s\\n' " + json.dumps(message) + "\nexit 2\n", encoding="utf-8")
    ensure_executable(path)


def write_codegraph_passthrough_shim(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env bash\n"
        "if [ -z \"${ACR_CODEGRAPH_BIN:-}\" ]; then\n"
        "  printf '%s\\n' 'ACR_CODEGRAPH_BIN must point to the real CodeGraph binary for the raw-CodeGraph arm.' >&2\n"
        "  exit 127\n"
        "fi\n"
        "exec \"$ACR_CODEGRAPH_BIN\" \"$@\"\n",
        encoding="utf-8",
    )
    ensure_executable(path)


def write_agent_config(path: Path, *, agent: str, gateway_enabled: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if agent == "codex":
        if gateway_enabled:
            path.write_text((TEMPLATE_ROOT / "codex-config.example.toml").read_text(encoding="utf-8"), encoding="utf-8")
        else:
            path.write_text("[mcp_servers]\n", encoding="utf-8")
        return
    if agent == "claude-code":
        payload = {"mcpServers": {}} if not gateway_enabled else json.loads((TEMPLATE_ROOT / "claude-mcp.example.json").read_text(encoding="utf-8"))
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return
    if agent == "cursor-agent":
        payload = {"mcpServers": {}} if not gateway_enabled else json.loads((TEMPLATE_ROOT / "cursor-mcp.example.json").read_text(encoding="utf-8"))
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return
    if agent == "opencode":
        payload = {"mcp": {}} if not gateway_enabled else json.loads((TEMPLATE_ROOT / "opencode.example.json").read_text(encoding="utf-8"))
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return
    raise ValueError(f"unsupported agent: {agent}")


def prepare_arm(out_dir: Path, *, arm_id: str, agent: str, repo_root: Path) -> dict[str, object]:
    treatment = codegraph_treatment_for_arm(arm_id)
    arm_dir = out_dir / arm_id
    blocked_tools_dir = arm_dir / "blocked-tools"
    shim_path = blocked_tools_dir / "codegraph"
    if arm_id == "CG-X-raw-codegraph":
        write_codegraph_passthrough_shim(shim_path)
    elif treatment.gateway_access_enabled:
        write_codegraph_shim(shim_path, message="Direct CodeGraph access is blocked. Use the bounded gateway.")
    else:
        write_codegraph_shim(shim_path, message="Direct CodeGraph access is disabled in this benchmark arm.")

    if agent == "codex":
        config_path = arm_dir / "codex-config.toml"
    elif agent == "claude-code":
        config_path = arm_dir / "claude-mcp.json"
    elif agent == "cursor-agent":
        config_path = arm_dir / "cursor-mcp.json"
    else:
        config_path = arm_dir / "opencode-config.json"
    write_agent_config(config_path, agent=agent, gateway_enabled=treatment.gateway_access_enabled and arm_id != "CG-X-raw-codegraph")

    telemetry_path = arm_dir / "gateway-telemetry.jsonl"
    route_isolation = {
        "arm_id": arm_id,
        "agent": agent,
        "repo_root": str(repo_root),
        "gateway_access_enabled": treatment.gateway_access_enabled,
        "graph_routing_discipline_enabled": treatment.graph_routing_discipline_enabled,
        "blocked_tool_path": str(shim_path),
        "gateway_config_path": str(config_path),
        "gateway_telemetry_path": str(telemetry_path),
        "env": {
            "PATH_prefix": str(blocked_tools_dir),
            "ACR_CODEGRAPH_BIN": os.environ.get("ACR_CODEGRAPH_BIN", "<set-absolute-codegraph-bin>"),
            "ACR_CODEGRAPH_TELEMETRY_PATH": str(telemetry_path),
        },
        "raw_codegraph_bypass_blocked": arm_id != "CG-X-raw-codegraph",
        "raw_codegraph_passthrough": arm_id == "CG-X-raw-codegraph",
    }
    (arm_dir / "route-isolation.json").write_text(json.dumps(route_isolation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return route_isolation


def main() -> int:
    parser = argparse.ArgumentParser(description="CodeGraph router benchmark bootstrap")
    parser.add_argument("--study-plan", default=str(DEFAULT_STUDY))
    parser.add_argument("--agent", default="codex")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", default=str(ROOT / "results" / "codegraph-router-benchmark"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    study_path = Path(args.study_plan).expanduser().resolve()
    study = parse_study_yaml(study_path)
    arms = [item.strip() for item in study.get("arms", "").split(",") if item.strip()]
    validate_codegraph_arm_set(arms, allow_optional_raw=True)
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    route_isolation = [prepare_arm(out_dir, arm_id=arm, agent=args.agent, repo_root=Path(args.repo_root).expanduser().resolve()) for arm in arms]
    payload = {
        "study_id": study.get("study_id", ""),
        "study_plan": str(study_path),
        "agent": args.agent,
        "repo_root": str(Path(args.repo_root).expanduser().resolve()),
        "out_dir": str(out_dir),
        "arms": arms,
        "arm_factors": {arm: public_codegraph_factor_payload(arm) for arm in arms},
        "route_isolation": route_isolation,
        "status": "prepared",
        "note": "Prepared additive CodeGraph benchmark assets, blocked raw codegraph shims, and host config overlays without changing router-effect-v1.",
    }
    (out_dir / "manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Validated CodeGraph benchmark study:")
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
