#!/usr/bin/env bash
set -euo pipefail

target_repo=""
missing=0
warnings=0

usage() {
  cat <<'USAGE'
Usage:
  check-android-prereqs.sh [--target-repo /path/to/android-repo]

Checks the local dependencies needed for Android/Kotlin agent routing.
It does not install packages, edit files, run Gradle, or start emulators.
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

check_cmd() {
  local label="$1"
  local cmd="$2"
  local path

  printf "%-24s" "$label"
  if path="$(command -v "$cmd" 2>/dev/null)"; then
    echo "$path"
  else
    echo "missing"
    missing=1
  fi
}

check_optional_cmd() {
  local label="$1"
  local cmd="$2"
  local path

  printf "%-24s" "$label"
  if path="$(command -v "$cmd" 2>/dev/null)"; then
    echo "$path"
  else
    echo "missing (optional)"
    warnings=$((warnings + 1))
  fi
}

check_gradle_wrapper_cache() {
  local repo="$1"
  local props="$repo/gradle/wrapper/gradle-wrapper.properties"
  local distribution_url
  local dist_zip
  local dist_name
  local version_name
  local cached_executable

  if [ ! -f "$props" ]; then
    echo "  Gradle wrapper props     missing"
    warnings=$((warnings + 1))
    return
  fi

  distribution_url="$(grep -E '^distributionUrl=' "$props" | sed 's/^distributionUrl=//' | sed 's#\\:#:#g' || true)"
  dist_zip="$(basename "$distribution_url")"
  dist_name="${dist_zip%.zip}"
  version_name="${dist_name%-bin}"

  echo "  Gradle distribution      $dist_name"

  if find "$HOME/.gradle/wrapper/dists/$dist_name" -maxdepth 2 -type d -name "$version_name" 2>/dev/null | grep -q .; then
    echo "  Gradle wrapper cache     present"
    cached_executable="$(find "$HOME/.gradle/wrapper/dists/$dist_name" -maxdepth 5 -path "*/$version_name/bin/gradle" -type f 2>/dev/null | head -n 1 || true)"
    if [ -n "$cached_executable" ]; then
      echo "  Gradle cached executable $cached_executable"
    fi
  else
    echo "  Gradle wrapper cache     missing or incomplete"
    echo "    first Gradle sync may download $dist_zip"
    warnings=$((warnings + 1))
  fi
}

check_local_properties_keys() {
  local repo="$1"
  local local_props="$repo/local.properties"
  local result

  result="$(python3 - "$repo" "$local_props" <<'PY'
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1])
local_props = Path(sys.argv[2])

present = set()
if local_props.exists():
    for line in local_props.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        present.add(stripped.split("=", 1)[0].strip())

required = set()
patterns = [
    re.compile(r'getPropertyFromLocalPropertiesFile\("([^"]+)"\)'),
    re.compile(r"getPropertyFromLocalPropertiesFile\('([^']+)'\)"),
    re.compile(r'getProperty\("([^"]+)"\)\s*\?:\s*(?:error|throw).*local\.properties'),
    re.compile(r"getProperty\('([^']+)'\)\s*\?:\s*(?:error|throw).*local\.properties"),
]

for path in repo.rglob("*"):
    if path.is_dir():
        continue
    if "build" in path.parts or ".gradle" in path.parts:
        continue
    if path.suffix not in {".kt", ".kts"}:
        continue
    text = path.read_text(errors="replace")
    for pattern in patterns:
        required.update(pattern.findall(text))

missing = sorted(required - present)
print("present=" + ",".join(sorted(present)))
print("required=" + ",".join(sorted(required)))
print("missing=" + ",".join(missing))
PY
)"

  if [ ! -f "$local_props" ]; then
    echo "  local.properties         missing"
    missing=1
    return
  fi

  echo "  local.properties         present"
  echo "$result" | sed 's/^/    /'

  if echo "$result" | grep -Eq '^missing=.+$'; then
    echo "  local.properties keys    missing required keys for Gradle sync"
    missing=1
  else
    echo "  local.properties keys    satisfied"
  fi
}

print_version() {
  local label="$1"
  shift
  local version

  version="$("$@" 2>/dev/null | head -n 1 || true)"
  if [ -n "$version" ]; then
    printf "  %-22s %s\n" "$label" "$version"
  fi
}

check_serena_processes() {
  local serena_mcp_count
  local kotlin_lsp_count
  local json_lsp_count
  local jdtls_count

  serena_mcp_count="$(count_processes 'serena start-mcp-server')"
  kotlin_lsp_count="$(count_processes 'KotlinLspServerKt')"
  json_lsp_count="$(count_processes 'vscode-json-languageserver')"
  jdtls_count="$(count_processes 'org.eclipse.equinox.launcher')"

  echo
  echo "Serena process state:"
  echo "  Serena MCP processes    $serena_mcp_count"
  echo "  Kotlin LSP processes    $kotlin_lsp_count"
  echo "  JSON LSP processes      $json_lsp_count"
  echo "  Java/JDTLS processes    $jdtls_count"

  if [ "$serena_mcp_count" -gt 1 ]; then
    echo "  Serena MCP warning      multiple MCP servers can leave Codex connected to a stale instance"
    echo "    inspect cleanup with: scripts/setup/repair-serena-android-sessions.sh --dry-run"
    warnings=$((warnings + 1))
  fi

  if [ "$kotlin_lsp_count" -gt 1 ]; then
    echo "  Kotlin LSP warning      multiple Kotlin LSP sessions can trigger workspace ownership conflicts"
    echo "    inspect cleanup with: scripts/setup/repair-serena-android-sessions.sh --dry-run"
    warnings=$((warnings + 1))
  fi

  if [ "$jdtls_count" -gt 0 ]; then
    echo "  Java/JDTLS warning      Java support may trigger Gradle sync and local.properties failures"
    echo "    inspect cleanup with: scripts/setup/repair-serena-android-sessions.sh --dry-run"
    warnings=$((warnings + 1))
  fi
}

count_processes() {
  local pattern="$1"
  { ps ax -o command= | grep -F "$pattern" | grep -v grep || true; } | wc -l | tr -d ' '
}

check_android_studio_install() {
  local app_path
  local version
  local bundle_id

  echo
  echo "Android Studio app install:"
  for app_path in "/Applications/Android Studio Preview.app" "/Applications/Android Studio.app"; do
    if [ -d "$app_path" ]; then
      version="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app_path/Contents/Info.plist" 2>/dev/null || true)"
      bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app_path/Contents/Info.plist" 2>/dev/null || true)"
      echo "  $(basename "$app_path")"
      echo "    path       $app_path"
      [ -n "$version" ] && echo "    version    $version"
      [ -n "$bundle_id" ] && echo "    bundle id  $bundle_id"
    fi
  done

  if [ ! -d "/Applications/Android Studio Preview.app" ]; then
    echo "  Preview app warning      /Applications/Android Studio Preview.app not found"
    echo "    Android CLI studio commands require Android Studio Preview/Quail 2 Canary 1 or higher."
    warnings=$((warnings + 1))
  fi
}

check_android_studio_bridge() {
  local check_output
  local project_name

  if ! command -v android >/dev/null 2>&1; then
    return
  fi

  echo
  echo "Android Studio CLI bridge:"
  if check_output="$(android studio check 2>&1)"; then
    echo "$check_output" | sed 's/^/  /'
  else
    echo "$check_output" | sed 's/^/  /'
    echo "  not ready"
    echo "  Open Android Studio Preview/Quail with the target project and finish Gradle sync/indexing."
    warnings=$((warnings + 1))
    return
  fi

  if [ -n "$target_repo" ]; then
    project_name="$(basename "$target_repo")"
    if printf '%s\n' "$check_output" | grep -Fq "$target_repo"; then
      echo "  target project           open: $project_name"
    else
      echo "  target project warning   not listed by android studio check: $project_name"
      echo "    open this exact repo root in Android Studio Preview before trusting IDE-backed probes."
      warnings=$((warnings + 1))
    fi
  fi
}

has_serena_language() {
  local project_file="$1"
  local language="$2"
  grep -Eq "^[[:space:]]*-[[:space:]]*$language[[:space:]]*$" "$project_file"
}

echo "Android/Kotlin agent-routing dependency gate"
echo
echo "Required layers:"
echo "  1. Serena with Kotlin/JSON language support"
echo "  2. rg / fd / ast-grep"
echo "  3. Java + Gradle wrapper for build/test proof"
echo "  4. Optional Android CLI + Android Studio Preview/Quail for IDE-backed semantic probes"
echo "  5. Optional Android SDK tools for emulator/device proof"
echo

check_cmd "serena" "serena"
check_cmd "rg" "rg"
check_cmd "fd" "fd"
check_cmd "ast-grep" "ast-grep"
check_cmd "java" "java"
check_cmd "jq" "jq"
check_optional_cmd "android CLI" "android"
check_optional_cmd "adb" "adb"

echo
print_version "serena" serena --version
print_version "rg" rg --version
print_version "fd" fd --version
print_version "ast-grep" ast-grep --version
print_version "java" java -version
print_version "android" android --version

check_serena_processes
check_android_studio_install
check_android_studio_bridge

if [ -n "$target_repo" ]; then
  echo
  echo "Target repo checks:"
  if [ ! -d "$target_repo" ]; then
    echo "  missing target repo: $target_repo"
    missing=1
  else
    if [ -x "$target_repo/gradlew" ]; then
      echo "  gradlew                  $target_repo/gradlew"
    elif [ -f "$target_repo/gradle/wrapper/gradle-wrapper.properties" ]; then
      echo "  gradlew                  missing or not executable"
      echo "    use the declared wrapper distribution, not system Gradle, when possible"
    elif command -v gradle >/dev/null 2>&1; then
      echo "  gradlew                  missing or not executable"
      echo "  gradle fallback          $(command -v gradle)"
    else
      echo "  gradlew                  missing or not executable"
      missing=1
    fi

    check_gradle_wrapper_cache "$target_repo"

    if find "$target_repo" -maxdepth 1 \( -name 'settings.gradle' -o -name 'settings.gradle.kts' \) | grep -q .; then
      echo "  settings.gradle          present"
    else
      echo "  settings.gradle          missing"
      missing=1
    fi

    check_local_properties_keys "$target_repo"

    if [ -f "$target_repo/.serena/project.yml" ]; then
      echo "  Serena project           $target_repo/.serena/project.yml"
      if has_serena_language "$target_repo/.serena/project.yml" "kotlin"; then
        echo "  Serena language kotlin   present"
      else
        echo "  Serena language kotlin   missing"
      fi
      if has_serena_language "$target_repo/.serena/project.yml" "json"; then
        echo "  Serena language json     present"
      else
        echo "  Serena language json     missing"
      fi
      if has_serena_language "$target_repo/.serena/project.yml" "java"; then
        echo "  Serena language java     present"
        echo "    note: Java/JDTLS can trigger Gradle sync. Keep it only when Java proof is needed."
        warnings=$((warnings + 1))
      fi
    else
      echo "  Serena project           missing"
      echo "  suggested:"
      echo "    cd \"$target_repo\" && serena project create --language kotlin --language json"
      echo "    Run a .kt source-symbol smoke test before full indexing."
    fi
  fi
fi

echo
if [ "$missing" -eq 0 ]; then
  echo "PASS: minimum Android/Kotlin routing dependency gate is satisfied."
  if [ "$warnings" -gt 0 ]; then
    echo "WARN: optional or stability warnings: $warnings"
  fi
else
  echo "FAIL: minimum Android/Kotlin routing dependency gate is not satisfied."
  echo
  echo "If command dependencies are present, fix the target repo readiness items above"
  echo "before expecting stable Kotlin/Android semantic lookup."
  echo
  echo "Suggested install starting point:"
  echo "  brew install fd ripgrep ast-grep jq"
  echo "  uv tool install -p 3.13 serena-agent@latest --prerelease=allow --force"
  echo "  Install Android Studio or Android command-line tools for SDK/emulator work."
fi

exit "$missing"
