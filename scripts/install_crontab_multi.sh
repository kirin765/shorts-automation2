#!/usr/bin/env bash
set -euo pipefail

# Installs multiple crontab entries to run the scheduled wrapper.
# Usage:
#   ./scripts/install_crontab_multi.sh 00:00 08:00 16:00
# If no times are provided, it installs the default 3-times-a-day schedule.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT_DIR/logs"

if [[ $# -eq 0 ]]; then
  TIMES=("00:00" "08:00" "16:00")
else
  TIMES=("$@")
fi

is_time() {
  [[ "$1" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]
}

CMD="LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 PYTHONIOENCODING=utf-8 cd $ROOT_DIR && ./scripts/run_scheduled.sh >> logs/cron_\\\$(date +\\\%Y\\\%m\\\%d).log 2>&1"

tmp="$(mktemp)"
crontab -l 2>/dev/null | grep -v "run_scheduled.sh" > "$tmp" || true

echo "Installing crontab lines:"
for TIME in "${TIMES[@]}"; do
  if ! is_time "$TIME"; then
    echo "Invalid time format: '$TIME' (expected HH:MM, 00:00-23:59)" >&2
    rm -f "$tmp"
    exit 2
  fi
  H="${TIME%:*}"
  M="${TIME#*:}"
  LINE="$M $H * * * $CMD"
  echo "$LINE"
  echo "$LINE" >> "$tmp"
done

crontab "$tmp"
rm -f "$tmp"

echo
echo "Installed. Verify with: crontab -l"
echo "If it doesn't run (especially on WSL), ensure cron/systemd is enabled and cron service is running."
