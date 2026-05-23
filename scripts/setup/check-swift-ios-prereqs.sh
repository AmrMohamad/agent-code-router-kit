#!/usr/bin/env bash
set -euo pipefail

missing=0

echo "Swift/iOS same-results dependency gate"
echo
echo "Required layers:"
echo "  1. Xcode SourceKit-LSP"
echo "  2. xcode-build-server"
echo "  3. Serena or equivalent LSP access layer"
echo "  4. rg / fd / ast-grep"
echo

print_version() {
  local label="$1"
  shift
  local version

  version="$("$@" 2>/dev/null | head -n 1 || true)"
  if [ -n "$version" ]; then
    printf "  %-22s %s\n" "$label" "$version"
  fi
}

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
    return
  fi
}

check_sourcekit_lsp() {
  local path

  printf "%-24s" "sourcekit-lsp"
  if command -v xcrun >/dev/null 2>&1 && path="$(xcrun --find sourcekit-lsp 2>/dev/null)"; then
    echo "$path"
  elif path="$(command -v sourcekit-lsp 2>/dev/null)"; then
    echo "$path"
  else
    echo "missing"
    missing=1
    return
  fi
}

check_sourcekit_lsp
check_cmd "xcode-build-server" "xcode-build-server"
check_cmd "serena" "serena"
check_cmd "rg" "rg"
check_cmd "fd" "fd"
check_cmd "ast-grep" "ast-grep"

echo
print_version "xcode-select" xcode-select -p
print_version "serena" serena --version
print_version "rg" rg --version
print_version "fd" fd --version
print_version "ast-grep" ast-grep --version

echo
if [ "$missing" -eq 0 ]; then
  echo "PASS: minimum same-results dependency gate is satisfied."
else
  echo "FAIL: minimum same-results dependency gate is not satisfied."
  echo
  echo "Suggested install starting point:"
  echo "  brew install xcode-build-server fd ripgrep ast-grep"
  echo "  uv tool install -p 3.13 serena-agent@latest --prerelease=allow --force"
  echo
  echo "Xcode must provide sourcekit-lsp. Verify with:"
  echo "  xcrun --find sourcekit-lsp"
fi

exit "$missing"
