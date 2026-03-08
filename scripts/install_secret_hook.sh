#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK_DIR="$ROOT_DIR/.git/hooks"
SCRIPT_SOURCE="$ROOT_DIR/.githooks/pre-push"
SCRIPT_TARGET="$HOOK_DIR/pre-push"

if [[ ! -f "$SCRIPT_SOURCE" ]]; then
  echo "Pre-push hook template not found: $SCRIPT_SOURCE" >&2
  exit 1
fi

cp "$SCRIPT_SOURCE" "$SCRIPT_TARGET"
chmod +x "$SCRIPT_TARGET"
echo "Installed repo secret-scan pre-push hook to $SCRIPT_TARGET"
