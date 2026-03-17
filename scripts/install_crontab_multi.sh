#!/usr/bin/env bash
set -euo pipefail

# Installs multiple crontab entries to run the daily pipeline.
# Usage:
#   ./scripts/install_crontab_multi.sh 09:00 12:00 15:00 18:00 21:00
# If no times are provided, it installs a reasonable 5-times-a-day default.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT_DIR/logs"

if [[ $# -eq 0 ]]; then
  TIMES=("09:00" "12:00" "15:00" "18:00" "21:00")
else
  TIMES=("$@")
fi

is_time() {
  [[ "$1" =~ ^([01]?[0-9]|2[0-3]):[0-5][0-9]$ ]]
}

CMD="cd $ROOT_DIR && if [ -f .venv/bin/activate ]; then . .venv/bin/activate; fi && python -m shorts pipeline daily --config ENV >> logs/cron_\\\$(date +\\\%Y\\\%m\\\%d).log 2>&1"

tmp="$(mktemp)"
crontab -l 2>/dev/null | grep -v "python -m shorts pipeline daily" > "$tmp" || true

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
