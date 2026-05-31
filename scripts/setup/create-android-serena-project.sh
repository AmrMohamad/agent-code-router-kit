#!/usr/bin/env bash
set -euo pipefail

target_repo=""
include_java=0
index_project=0
overwrite=0

usage() {
  cat <<'USAGE'
Usage:
  create-android-serena-project.sh --target-repo /path/to/android-repo [--include-java] [--index] [--overwrite]

Creates or updates Serena project metadata for an Android/Kotlin repo.
Default languages are kotlin + json. Use --include-java for mixed Java/Kotlin repos.

This script does not use sudo, does not run Gradle, does not start emulators,
and does not claim build/runtime proof.
USAGE
}

require_value() {
  local option="$1"
  local value="${2-}"
  if [ -z "$value" ]; then
    echo "$option requires a value." >&2
    usage >&2
    exit 2
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-repo)
      require_value "$1" "${2-}"
      target_repo="${2:-}"
      shift 2
      ;;
    --include-java)
      include_java=1
      shift
      ;;
    --index)
      index_project=1
      shift
      ;;
    --overwrite)
      overwrite=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "$target_repo" ]; then
  echo "--target-repo is required." >&2
  usage >&2
  exit 2
fi

if [ ! -d "$target_repo" ]; then
  echo "Target repo not found: $target_repo" >&2
  exit 2
fi

if ! command -v serena >/dev/null 2>&1; then
  echo "serena is not installed or not on PATH." >&2
  exit 127
fi

target_repo="$(cd "$target_repo" && pwd)"
project_yml="$target_repo/.serena/project.yml"

if [ -f "$project_yml" ] && [ "$overwrite" -eq 0 ]; then
  echo "Serena project already exists: $project_yml"
  echo "Leaving unchanged. Pass --overwrite to recreate it."
  exit 0
fi

cmd=(serena project create "$target_repo" --language kotlin --language json)

if [ "$include_java" -eq 1 ]; then
  cmd+=(--language java)
fi

if [ "$index_project" -eq 1 ]; then
  cmd+=(--index)
fi

echo "Running:"
printf '  %q' "${cmd[@]}"
printf '\n'

"${cmd[@]}"

echo
echo "Done. Verify with:"
echo "  serena project health-check \"$target_repo\""
echo
echo "Build/runtime proof still belongs to Gradle, Android Studio, emulator/device, or CI."
