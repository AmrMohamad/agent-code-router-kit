#!/usr/bin/env bash
set -euo pipefail

mode="dry-run"

usage() {
  cat <<'USAGE'
Usage:
  repair-serena-android-sessions.sh [--dry-run|--kill]

Lists Serena MCP and language-server processes that can make Android/Kotlin
semantic probes unstable. The default is --dry-run and does not terminate
anything.

Use --kill only when you intentionally want to stop stale Serena/LSP sessions
before restarting Codex/Serena and re-running Android semantic probes.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      mode="dry-run"
      shift
      ;;
    --kill)
      mode="kill"
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

process_lines() {
  local pattern="$1"
  ps ax -o pid=,command= | awk -v pattern="$pattern" -v self="$$" '
    $1 != self && $2 != "awk" && index($0, pattern) > 0 {
      print
    }
  '
}

print_processes() {
  local label="$1"
  local pattern="$2"
  local lines
  local count

  lines="$(process_lines "$pattern" || true)"
  count="$(printf '%s\n' "$lines" | awk 'NF {count++} END {print count + 0}')"

  printf "%-28s %s\n" "$label" "$count"
  if [ "$count" -gt 0 ]; then
    printf '%s\n' "$lines" | sed 's/^/  /'
  fi
}

kill_processes() {
  local label="$1"
  local pattern="$2"
  local pids

  pids="$(process_lines "$pattern" | awk '{print $1}' || true)"
  if [ -z "$pids" ]; then
    return
  fi

  echo "Stopping $label: $(printf '%s' "$pids" | tr '\n' ' ')"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
}

echo "Serena Android session repair"
echo "Mode: $mode"
echo

print_processes "Serena MCP processes" "serena start-mcp-server"
print_processes "Kotlin LSP processes" "KotlinLspServerKt"
print_processes "JSON LSP processes" "vscode-json-languageserver"
print_processes "Java/JDTLS processes" "org.eclipse.equinox.launcher"
echo

if [ "$mode" = "dry-run" ]; then
  cat <<'NEXT'
Dry run only. No processes were stopped.

Recommended cleanup sequence:
  1. Close active Codex sessions that are using Serena, or expect them to reconnect.
  2. Run this script with --kill.
  3. Restart Codex from the target Android repo.
  4. Confirm only one Serena MCP session is active.
  5. Re-run the Android benchmark suite.
NEXT
  exit 0
fi

kill_processes "Serena MCP processes" "serena start-mcp-server"
kill_processes "Kotlin LSP processes" "KotlinLspServerKt"
kill_processes "JSON LSP processes" "vscode-json-languageserver"
kill_processes "Java/JDTLS processes" "org.eclipse.equinox.launcher"

echo
echo "Stopped candidate Serena/LSP processes. Restart Codex/Serena before probing again."
