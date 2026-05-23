#!/usr/bin/env bash
set -euo pipefail

missing=0

check_cmd() {
  local label="$1"
  local cmd="$2"
  printf "%-22s" "$label"
  if command -v "$cmd" >/dev/null 2>&1; then
    command -v "$cmd"
  else
    echo "missing"
    missing=1
  fi
}

printf "%-22s" "sourcekit-lsp"
if command -v sourcekit-lsp >/dev/null 2>&1; then
  command -v sourcekit-lsp
elif command -v xcrun >/dev/null 2>&1 && xcrun --find sourcekit-lsp >/dev/null 2>&1; then
  xcrun --find sourcekit-lsp
else
  echo "missing"
  missing=1
fi

check_cmd "xcode-build-server" "xcode-build-server"
check_cmd "rg" "rg"
check_cmd "fd" "fd"
check_cmd "ast-grep" "ast-grep"
check_cmd "serena" "serena"

echo
if [ "$missing" -eq 0 ]; then
  echo "All checked tools are present."
else
  echo "Some tools are missing."
  echo "Suggested install starting point:"
  echo "  brew install xcode-build-server fd ripgrep ast-grep"
  echo "Install Serena using its current official instructions."
fi

exit "$missing"

