#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="dry-run"
TARGET_REPO=""
AGENT="generic"
PROFILE="swift-ios"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
PROJECT=""
WORKSPACE=""
SCHEME=""
CONFIGURE_BUILD_SERVER=0
OVERWRITE=0

usage() {
  cat <<'USAGE'
Usage:
  agent-self-install.sh --target-repo /path/to/repo [--agent generic|codex] [--profile swift-ios|android|all] [--dry-run]
  agent-self-install.sh --target-repo /path/to/repo --agent codex --profile android --apply

Optional buildServer.json configuration:
  agent-self-install.sh --target-repo /path/to/repo --workspace App.xcworkspace --scheme "App" --configure-build-server --apply
  agent-self-install.sh --target-repo /path/to/repo --project App.xcodeproj --scheme "App" --configure-build-server --apply

Safety:
  Default mode is --dry-run and writes nothing.
  --apply copies templates without overwriting existing files.
  --overwrite is required to replace an existing Codex skill.
  The script never uses sudo, never changes Xcode developer path, and never builds or tests.
USAGE
}

log() {
  printf '%s\n' "$*"
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

require_file() {
  local path="$1"
  if [ ! -f "$path" ]; then
    echo "Required file missing: $path" >&2
    exit 1
  fi
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

copy_file_safe() {
  local src="$1"
  local dst="$2"
  local label="$3"

  require_file "$src"

  if [ -f "$dst" ]; then
    if cmp -s "$src" "$dst"; then
      log "$label already installed: $dst"
      return
    fi
    if [ "$OVERWRITE" -eq 1 ]; then
      log "$label differs; replacing because --overwrite was provided: $dst"
      run_or_print cp "$src" "$dst"
      return
    fi
    log "$label exists and differs; leaving unchanged: $dst"
    return
  fi

  log "$label will be installed: $dst"
  run_or_print mkdir -p "$(dirname "$dst")"
  run_or_print cp "$src" "$dst"
}

install_project_policy() {
  local src="$ROOT/templates/AGENTS.md"
  local dst="$TARGET_REPO/AGENTS.md"
  local fragment_dir="$TARGET_REPO/.agent-code-router"
  local fragment="$fragment_dir/AGENTS.fragment.md"

  require_file "$src"

  if [ ! -f "$dst" ]; then
    log "Project AGENTS.md will be installed: $dst"
    run_or_print cp "$src" "$dst"
    return
  fi

  if cmp -s "$src" "$dst"; then
    log "Project AGENTS.md already matches template: $dst"
    return
  fi

  log "Existing AGENTS.md found; it will not be overwritten: $dst"
  log "Writing review fragment instead: $fragment"
  copy_file_safe "$src" "$fragment" "Project AGENTS.md review fragment"
}

install_codex_skill() {
  local src="$ROOT/templates/codebase-tool-router/SKILL.md"
  local dst="$CODEX_HOME/skills/codebase-tool-router/SKILL.md"
  copy_file_safe "$src" "$dst" "Codex codebase-tool-router skill"

  if [ "$PROFILE" = "android" ] || [ "$PROFILE" = "all" ]; then
    src="$ROOT/templates/android-codebase-tool-router/SKILL.md"
    dst="$CODEX_HOME/skills/android-codebase-tool-router/SKILL.md"
    copy_file_safe "$src" "$dst" "Codex android-codebase-tool-router skill"
  fi
}

validate_toolkit() {
  require_file "$ROOT/templates/AGENTS.md"
  require_file "$ROOT/templates/codebase-tool-router/SKILL.md"
  require_file "$ROOT/templates/android-codebase-tool-router/SKILL.md"
  require_file "$ROOT/scripts/setup/check-swift-ios-prereqs.sh"
  require_file "$ROOT/scripts/setup/check-android-prereqs.sh"
  require_file "$ROOT/scripts/setup/create-build-server-json.sh"
  require_file "$ROOT/scripts/setup/create-android-serena-project.sh"
  require_file "$ROOT/scripts/benchmarks/shared/benchmark_runner.py"
  require_file "$ROOT/benchmarks/ios/cases.example.tsv"

  if [ "$PROFILE" = "swift-ios" ] || [ "$PROFILE" = "all" ]; then
    log "Checking Swift/iOS prerequisites."
    bash "$ROOT/scripts/setup/check-swift-ios-prereqs.sh"

    log "Validating Swift/iOS benchmark manifest."
    python3 "$ROOT/scripts/benchmarks/shared/benchmark_runner.py" \
      --validate \
      --cases "$ROOT/benchmarks/ios/cases.example.tsv"
  fi

  if [ "$PROFILE" = "android" ] || [ "$PROFILE" = "all" ]; then
    log "Checking Android/Kotlin prerequisites."
    bash "$ROOT/scripts/setup/check-android-prereqs.sh" --target-repo "$TARGET_REPO"
  fi
}

configure_build_server() {
  if [ "$CONFIGURE_BUILD_SERVER" -eq 0 ]; then
    log "buildServer.json configuration skipped."
    return
  fi

  if [ -z "$SCHEME" ]; then
    echo "--scheme is required with --configure-build-server." >&2
    exit 2
  fi

  if [ -n "$PROJECT" ] && [ -n "$WORKSPACE" ]; then
    echo "Pass either --project or --workspace, not both." >&2
    exit 2
  fi

  if [ -z "$PROJECT" ] && [ -z "$WORKSPACE" ]; then
    echo "Pass --project or --workspace with --configure-build-server." >&2
    exit 2
  fi

  if [ -n "$PROJECT" ]; then
    if [ ! -d "$PROJECT" ]; then
      echo "Project not found from target repo: $PROJECT" >&2
      exit 2
    fi
    run_or_print "$ROOT/scripts/setup/create-build-server-json.sh" \
      --project "$PROJECT" \
      --scheme "$SCHEME"
  else
    if [ ! -d "$WORKSPACE" ]; then
      echo "Workspace not found from target repo: $WORKSPACE" >&2
      exit 2
    fi
    run_or_print "$ROOT/scripts/setup/create-build-server-json.sh" \
      --workspace "$WORKSPACE" \
      --scheme "$SCHEME"
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --target-repo)
      require_value "$1" "${2-}"
      TARGET_REPO="${2:-}"
      shift 2
      ;;
    --agent)
      require_value "$1" "${2-}"
      AGENT="${2:-}"
      shift 2
      ;;
    --profile)
      require_value "$1" "${2-}"
      PROFILE="${2:-}"
      shift 2
      ;;
    --codex-home)
      require_value "$1" "${2-}"
      CODEX_HOME="${2:-}"
      shift 2
      ;;
    --project)
      require_value "$1" "${2-}"
      PROJECT="${2:-}"
      shift 2
      ;;
    --workspace)
      require_value "$1" "${2-}"
      WORKSPACE="${2:-}"
      shift 2
      ;;
    --scheme)
      require_value "$1" "${2-}"
      SCHEME="${2:-}"
      shift 2
      ;;
    --configure-build-server)
      CONFIGURE_BUILD_SERVER=1
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --overwrite)
      OVERWRITE=1
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

if [ -z "$TARGET_REPO" ]; then
  echo "--target-repo is required." >&2
  usage >&2
  exit 2
fi

if [ "$AGENT" != "generic" ] && [ "$AGENT" != "codex" ]; then
  echo "--agent must be generic or codex." >&2
  exit 2
fi

if [ "$PROFILE" != "swift-ios" ] && [ "$PROFILE" != "android" ] && [ "$PROFILE" != "all" ]; then
  echo "--profile must be swift-ios, android, or all." >&2
  exit 2
fi

if [ ! -d "$TARGET_REPO" ]; then
  echo "Target repo not found: $TARGET_REPO" >&2
  exit 2
fi

TARGET_REPO="$(cd "$TARGET_REPO" && pwd)"

if [ "$MODE" = "dry-run" ]; then
  log "Mode: dry-run. No files will be written."
else
  log "Mode: apply. Safe non-destructive writes are enabled."
fi

validate_toolkit
install_project_policy

if [ "$AGENT" = "codex" ]; then
  install_codex_skill
else
  log "Generic agent selected; no Codex skill path will be written."
fi

(
  cd "$TARGET_REPO"
  configure_build_server
)

log "Done."
log "Next step: restart or refresh the agent, then ask it to use the codebase tool router."
