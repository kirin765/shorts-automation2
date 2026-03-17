#!/usr/bin/env bash
set -euo pipefail

# Installs crontab entries to run the scheduled wrapper.
# Note: On WSL, cron/systemd may not be enabled by default.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 PYTHONIOENCODING=utf-8 cd $ROOT_DIR && ./scripts/run_scheduled.sh >> logs/cron_\$(date +\\%Y\\%m\\%d).log 2>&1"

mkdir -p "$ROOT_DIR/logs"

tmp="$(mktemp)"
crontab -l 2>/dev/null | grep -v "run_scheduled.sh" > "$tmp" || true
echo "Installing crontab lines:"
if [[ $# -eq 0 ]]; then
  TIMES=("00:00" "08:00" "16:00")
else
  TIMES=("$@")
fi
for TIME in "${TIMES[@]}"; do
  H="${TIME%:*}"
  M="${TIME#*:}"
  LINE="$M $H * * * $CMD"
  echo "$LINE"
  echo "$LINE" >> "$tmp"
done
crontab "$tmp"
rm -f "$tmp"

echo "Installed. Verify with: crontab -l"
echo "If it doesn't run on WSL, enable systemd/cron and start the cron service."
