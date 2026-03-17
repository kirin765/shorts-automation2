#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${HOME}/.config/systemd/user"
mkdir -p "$UNIT_DIR"

install -m 0644 "$ROOT_DIR/systemd/shorts-automation2.service" "$UNIT_DIR/shorts-automation2.service"
install -m 0644 "$ROOT_DIR/systemd/shorts-automation2.timer" "$UNIT_DIR/shorts-automation2.timer"
install -m 0644 "$ROOT_DIR/systemd/shorts-automation2-lid-inhibit.service" "$UNIT_DIR/shorts-automation2-lid-inhibit.service"
chmod 0755 "$ROOT_DIR/scripts/run_scheduled_systemd.sh"
chmod 0755 "$ROOT_DIR/scripts/lid_inhibit_idle.sh"

systemctl --user daemon-reload
systemctl --user enable --now shorts-automation2.timer
systemctl --user enable --now shorts-automation2-lid-inhibit.service
systemctl --user start shorts-automation2.service || true

echo "Installed user service/timer:"
systemctl --user list-timers shorts-automation2.timer --all --no-pager
systemctl --user --no-pager --full status shorts-automation2-lid-inhibit.service || true
