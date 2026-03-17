#!/usr/bin/env bash
set -euo pipefail

# Installs a crontab entry to run the daily pipeline.
# Note: On WSL, cron/systemd may not be enabled by default.

TIME="${1:-09:00}"
H="${TIME%:*}"
M="${TIME#*:}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="cd $ROOT_DIR && if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi && python -m shorts pipeline daily --config ENV >> logs/cron_\$(date +\\%Y\\%m\\%d).log 2>&1"

mkdir -p "$ROOT_DIR/logs"

LINE="$M $H * * * $CMD"
echo "Installing crontab line:"
echo "$LINE"
echo

tmp="$(mktemp)"
crontab -l 2>/dev/null | grep -v "python -m shorts pipeline daily" > "$tmp" || true
echo "$LINE" >> "$tmp"
crontab "$tmp"
rm -f "$tmp"

echo "Installed. Verify with: crontab -l"
echo "If it doesn't run on WSL, enable systemd/cron and start the cron service."
