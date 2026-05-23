#!/usr/bin/env bash
set -euo pipefail

project=""
workspace=""
scheme=""

usage() {
  cat <<'USAGE'
Usage:
  create-build-server-json.sh --project YourApp.xcodeproj --scheme "Your Scheme"
  create-build-server-json.sh --workspace YourApp.xcworkspace --scheme "Your Scheme"

This script creates or updates buildServer.json using xcode-build-server.
It does not use sudo and does not run build or test.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --project)
      project="${2:-}"
      shift 2
      ;;
    --workspace)
      workspace="${2:-}"
      shift 2
      ;;
    --scheme)
      scheme="${2:-}"
      shift 2
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

if ! command -v xcode-build-server >/dev/null 2>&1; then
  echo "xcode-build-server is not installed or not on PATH." >&2
  exit 127
fi

if [ -z "$scheme" ]; then
  echo "--scheme is required." >&2
  usage >&2
  exit 2
fi

if [ -n "$project" ] && [ -n "$workspace" ]; then
  echo "Pass either --project or --workspace, not both." >&2
  exit 2
fi

if [ -z "$project" ] && [ -z "$workspace" ]; then
  echo "Pass --project or --workspace." >&2
  exit 2
fi

if [ -n "$project" ]; then
  if [ ! -d "$project" ]; then
    echo "Project not found: $project" >&2
    exit 2
  fi
  echo "Running: xcode-build-server config -project $project -scheme $scheme"
  xcode-build-server config -project "$project" -scheme "$scheme"
else
  if [ ! -d "$workspace" ]; then
    echo "Workspace not found: $workspace" >&2
    exit 2
  fi
  echo "Running: xcode-build-server config -workspace $workspace -scheme $scheme"
  xcode-build-server config -workspace "$workspace" -scheme "$scheme"
fi

echo "Done. Consider excluding buildServer.json locally:"
echo "  printf '\\nbuildServer.json\\n.compile/\\n' >> .git/info/exclude"

