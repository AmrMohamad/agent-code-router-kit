#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
MODE="dry-run"
PACKAGE_DIR="$ROOT/packages/codegraph-gateway"
PACKAGE_NAME="$(python3 - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path('packages/codegraph-gateway/pyproject.toml').read_text(encoding='utf-8'))
print(data['project']['name'])
PY
)"
PACKAGE_VERSION="$(python3 - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path('packages/codegraph-gateway/pyproject.toml').read_text(encoding='utf-8'))
print(data['project']['version'])
PY
)"
MCP_REQUIREMENT="$(python3 - <<'PY'
import tomllib
from pathlib import Path
data = tomllib.loads(Path('packages/codegraph-gateway/pyproject.toml').read_text(encoding='utf-8'))
deps = data['project'].get('dependencies', [])
print(next((dep for dep in deps if dep.startswith('mcp')), 'mcp'))
PY
)"

usage() {
  cat <<'USAGE'
Usage:
  install-codegraph-gateway.sh [--dry-run]
  install-codegraph-gateway.sh --apply

Safety:
  Default mode is dry-run and writes nothing.
  The script never installs CodeGraph itself and never initializes a repository index.
USAGE
}

run_or_print() {
  if [ "$MODE" = "apply" ]; then
    "$@"
  else
    printf '[dry-run] '
    printf '%q ' "$@"
    printf '\n'
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply)
      MODE="apply"
      shift
      ;;
    --dry-run)
      MODE="dry-run"
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

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required to install the gateway." >&2
  exit 2
fi

printf 'Gateway package: %s %s\n' "$PACKAGE_NAME" "$PACKAGE_VERSION"
printf 'Pinned dependency: %s\n' "$MCP_REQUIREMENT"

if uv tool list 2>/dev/null | grep -Eq "^${PACKAGE_NAME} "; then
  if [ "$MODE" = "apply" ]; then
    echo "$PACKAGE_NAME is already installed. Refusing silent upgrade." >&2
    exit 2
  fi
  echo "[dry-run] $PACKAGE_NAME is already installed. Skipping install to avoid a silent upgrade."
  exit 0
fi

run_or_print uv tool install --from "$PACKAGE_DIR" acr-codegraph-gateway
run_or_print acr-codegraph-gateway --help
