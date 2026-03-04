#!/usr/bin/env bash
set -euo pipefail

# Install a cron job that runs every 3 hours.
# Usage:
#   ./scripts/install_crontab_every_3h.sh [minute]
# minute default: 0

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT_DIR/logs"

MINUTE="${1:-0}"
if ! [[ "$MINUTE" =~ ^[0-5]?[0-9]$ ]]; then
  echo "Invalid minute: '$MINUTE' (expected 0-59)" >&2
  exit 2
fi

CMD="cd $ROOT_DIR && CLEANUP_ALL_ARTIFACTS=1 ./scripts/run_scheduled.sh >> logs/cron_\$(date +\\%Y\\%m\\%d).log 2>&1"

tmp="$(mktemp)"
crontab -l 2>/dev/null | grep -v "run_scheduled.sh" > "$tmp" || true
LINE="$MINUTE */3 * * * $CMD"
echo "Installing crontab line:"
echo "$LINE"
echo "$LINE" >> "$tmp"
crontab "$tmp"
rm -f "$tmp"

echo "Installed every-3-hour cron rule (minute=$MINUTE)."
echo "To make minute configurable, edit CMD/line or add a custom minute in the schedule."
echo "Installed. Verify with: crontab -l"
