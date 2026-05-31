#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FEATURE_PATTERNS = {
    "apollo": ["apollo", "com.apollographql"],
    "ksp": ["ksp", "com.google.devtools.ksp"],
    "kapt": ["kapt"],
    "hilt_or_dagger": ["hilt", "dagger"],
    "room": ["room"],
    "view_binding": ["viewBinding"],
    "data_binding": ["dataBinding"],
    "build_config": ["BuildConfig", "buildConfig"],
}
CONFIG_SUFFIXES = {".gradle", ".kts", ".toml"}
SKIP_DIRS = {".git", ".gradle", ".idea", ".serena", "node_modules"}


def stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d-%H%M%S")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iter_config_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and (path.name in {"settings.gradle.kts", "build.gradle.kts"} or path.suffix in CONFIG_SUFFIXES):
            files.append(path)
    return sorted(files)


def detect_features(repo: Path) -> dict[str, Any]:
    hits = {name: [] for name in FEATURE_PATTERNS}
    for path in iter_config_files(repo):
        text = path.read_text(errors="replace")
        rel = str(path.relative_to(repo))
        for feature, needles in FEATURE_PATTERNS.items():
            if any(needle.lower() in text.lower() for needle in needles):
                hits[feature].append(rel)
    return {
        feature: {
            "present": bool(paths),
            "files": paths[:20],
            "file_count": len(paths),
        }
        for feature, paths in hits.items()
    }


def generated_kind(path: Path) -> str:
    parts = set(path.parts)
    lowered = str(path).lower()
    if "ksp" in parts or "ksp" in lowered:
        return "ksp"
    if "kapt" in parts or "kapt" in lowered:
        return "kapt"
    if "apollo" in lowered or "operationoutput" in lowered:
        return "apollo"
    if "buildconfig" in lowered:
        return "build_config"
    if "source" in parts:
        return "source"
    return "other"


def find_generated_dirs(repo: Path, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in repo.rglob("*"):
        if any(part in {".git", ".gradle", ".idea", ".serena"} for part in path.parts):
            continue
        if not path.is_dir():
            continue
        rel_parts = path.relative_to(repo).parts
        if "build" not in rel_parts:
            continue
        if "generated" not in rel_parts and "ksp" not in rel_parts and "kapt" not in rel_parts:
            continue
        try:
            child_count = sum(1 for _ in path.iterdir())
        except OSError:
            child_count = 0
        rows.append(
            {
                "path": str(path.relative_to(repo)),
                "kind": generated_kind(path),
                "child_count": child_count,
            }
        )
        if len(rows) >= limit:
            break
    return sorted(rows, key=lambda item: item["path"])


def build_payload(repo: Path, limit: int) -> dict[str, Any]:
    features = detect_features(repo)
    generated_dirs = find_generated_dirs(repo, limit)
    kind_counts: dict[str, int] = {}
    for row in generated_dirs:
        kind_counts[row["kind"]] = kind_counts.get(row["kind"], 0) + 1
    return {
        "created_at": utc_now(),
        "repo": str(repo),
        "features": features,
        "generated_dirs": generated_dirs,
        "generated_dir_count": len(generated_dirs),
        "generated_kind_counts": kind_counts,
        "notes": [
            "This probe discovers generated-source readiness only.",
            "It does not validate GraphQL schema correctness or prove runtime behavior.",
        ],
    }


def build_assertions(payload: dict[str, Any]) -> dict[str, Any]:
    features = payload["features"]
    generated_count = int(payload["generated_dir_count"])
    assertions: list[dict[str, Any]] = [
        {"status": "pass", "check": "generated-scan-ran", "message": "Generated-source scan completed."}
    ]
    if generated_count:
        assertions.append(
            {
                "status": "pass",
                "check": "generated-dirs-present",
                "message": f"generated_dir_count={generated_count}",
            }
        )
    else:
        assertions.append(
            {
                "status": "warn",
                "check": "generated-dirs-present",
                "message": "No generated directories found; run Gradle/Studio sync before trusting generated symbol lookup.",
            }
        )
    for feature in ["apollo", "ksp", "room", "build_config"]:
        assertions.append(
            {
                "status": "pass" if features[feature]["present"] else "warn",
                "check": f"feature-{feature}",
                "message": f"present={features[feature]['present']} files={features[feature]['file_count']}",
            }
        )
    counts = {
        "pass": sum(1 for item in assertions if item["status"] == "pass"),
        "warn": sum(1 for item in assertions if item["status"] == "warn"),
        "fail": sum(1 for item in assertions if item["status"] == "fail"),
    }
    return {"summary": counts, "assertions": assertions}


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe generated-source readiness in Android repos.")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--output", default="results/android/generated-source")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--enforce-assertions", action="store_true")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    if args.validate:
        if not repo.exists():
            raise SystemExit(f"repo path missing: {repo}")
        print("VALIDATION PASSED: generated-source probe")
    if not args.run:
        return 0

    payload = build_payload(repo, args.limit)
    assertions = build_assertions(payload)
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    run_id = stamp()
    summary_path = output / f"android-generated-source-summary-{run_id}.json"
    assertions_path = output / f"android-generated-source-assertions-{run_id}.json"
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    assertions_path.write_text(json.dumps(assertions, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {summary_path}")
    print(f"Wrote {assertions_path}")
    print(
        "Assertions: "
        f"pass={assertions['summary']['pass']}, "
        f"warn={assertions['summary']['warn']}, "
        f"fail={assertions['summary']['fail']}"
    )
    if args.enforce_assertions and assertions["summary"]["fail"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
