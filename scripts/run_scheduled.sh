#!/usr/bin/env bash
set -euo pipefail

# Wrapper intended for cron/Task Scheduler.
# It generates fresh topics then runs the daily queue.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Force UTF-8 output for cron/non-interactive environments.
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export PYTHONUNBUFFERED=1

# Prevent overlapping runs (cron can fire while a previous run is still executing).
LOCKFILE="${LOCKFILE:-$ROOT_DIR/.shorts_automation2.lock}"
if [[ "${_LOCKED:-0}" != "1" ]] && command -v flock >/dev/null 2>&1; then
  export _LOCKED=1
  exec flock -n "$LOCKFILE" "$0" "$@"
fi
LOCKDIR="${LOCKDIR:-$ROOT_DIR/.shorts_automation2.lockdir}"
if mkdir "$LOCKDIR" 2>/dev/null; then
  trap 'rmdir "$LOCKDIR"' EXIT
else
  echo "Another run is already in progress; exiting."
  exit 0
fi

# Load local env vars for cron (optional). Keep secrets out of git by using .env (gitignored).
if [[ -f ".env" ]]; then
  set -o allexport
  # shellcheck disable=SC1091
  . ./.env
  set +o allexport
fi

LOG_DIR="${LOG_DIR:-logs}"
mkdir -p "$LOG_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/run_scheduled_${STAMP}.log"

notify_openclaw() {
  local message="$1"
  local enabled
  local cmd="${OPENCLAW_NOTIFY_CMD:-}"

  enabled="${OPENCLAW_NOTIFY_ENABLED:-0}"
  case "${enabled,,}" in
    1|true|yes|on|y) ;;
    *) return 0 ;;
  esac
  if [[ -z "$cmd" ]]; then
    return 0
  fi

  local quoted
  quoted="$(printf '%q' "$message")"
  if [[ "$cmd" == *"{message}"* ]]; then
    cmd="${cmd//\{message\}/$quoted}"
  else
    cmd="$cmd $quoted"
  fi

  bash -lc "$cmd" >/dev/null 2>&1 || true
}

CONFIG="${CONFIG:-ENV}"
if [[ "$CONFIG" == "ENV" && -f "config.json" ]]; then
  CONFIG="config.json"
fi
COUNT="${COUNT:-1}"
NO_UPLOAD="${NO_UPLOAD:-0}"   # 1 to skip upload
TARGET_SECONDS="${TARGET_SECONDS:-28}"
NICHE="${NICHE:-}"
STYLE="${STYLE:-}"
TONE="${TONE:-빠르고 자신있게}"
STYLE_MODE="${STYLE_MODE:-auto}"
GEN_TOPIC_COUNT="${GEN_TOPIC_COUNT:-10}"
CLEANUP_ALL_ARTIFACTS="${CLEANUP_ALL_ARTIFACTS:-1}"
BACKGROUND_PROVIDER="${BACKGROUND_PROVIDER:-pexels}"

if [[ "$COUNT" -gt "$GEN_TOPIC_COUNT" ]]; then
  GEN_TOPIC_COUNT="$COUNT"
fi

PY_BIN="python3"
if [[ -x ".venv/bin/python" ]]; then
  PY_BIN=".venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
fi

cleanup_output_artifacts() {
  "$PY_BIN" - "$CONFIG" <<'PY'
from config_loader import load_config
from pathlib import Path
from datetime import datetime, timedelta
import os
import shutil
import sys

cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "ENV")
if str(cfg.get("output_cleanup_enabled", True)).strip().lower() in {"0", "false", "no", "off"}:
    raise SystemExit(0)

out_dir = Path(cfg.get("output_dir", "output"))
if not out_dir.exists():
    raise SystemExit(0)

keep_latest = max(0, int(cfg.get("output_cleanup_keep_latest", 30) or 30))
keep_days = max(0, float(cfg.get("output_cleanup_keep_days", 5) or 5))
min_free_gb = max(0.0, float(cfg.get("output_cleanup_min_free_gb", 5) or 5))
min_free_bytes = int(min_free_gb * (1024 ** 3))
cutoff = datetime.now() - timedelta(days=keep_days)

groups: dict[str, list[Path]] = {}
for path in out_dir.iterdir():
    if not path.is_file():
        continue
    name = path.name
    stamp = name.split(".", 1)[0]
    if len(stamp) != 15 or stamp[8] != "_":
        continue
    groups.setdefault(stamp, []).append(path)

ordered = sorted(groups.items(), key=lambda item: item[0], reverse=True)
keep_stamps = {stamp for stamp, _ in ordered[:keep_latest]}

deleted = 0
freed = 0
for stamp, paths in ordered[keep_latest:]:
    newest_mtime = max((p.stat().st_mtime for p in paths), default=0.0)
    if datetime.fromtimestamp(newest_mtime) > cutoff:
        continue
    for path in paths:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        try:
            path.unlink()
            deleted += 1
            freed += size
        except FileNotFoundError:
            continue
        except Exception as exc:
            print(f"[-] output cleanup failed for {path}: {exc}")

usage = shutil.disk_usage(out_dir)
if deleted:
    print(f"[cleanup] removed_files={deleted} freed_bytes={freed} keep_latest={keep_latest} keep_days={keep_days}")
print(f"[cleanup] free_bytes={usage.free} min_required_bytes={min_free_bytes}")
if usage.free < min_free_bytes:
    raise SystemExit(f"insufficient free disk after cleanup: free={usage.free} required={min_free_bytes}")
PY
}

SLOT_STATUS="$("$PY_BIN" - "$CONFIG" "$NO_UPLOAD" <<'PY'
from config_loader import load_config
from datetime import datetime
import sys

cfg = load_config(sys.argv[1] if len(sys.argv) > 1 else "ENV")
no_upload = str(sys.argv[2] if len(sys.argv) > 2 else "0").strip() == "1"
raw_slots = cfg.get("upload_slots_hours") or [0, 8, 16]
slots = []
for item in raw_slots:
    try:
        slots.append(int(item) % 24)
    except Exception:
        continue
if not slots:
    slots = [0, 8, 16]
enforce = str(cfg.get("enforce_upload_slots", True)).strip().lower() not in {"0", "false", "no", "off"}
hour = datetime.now().hour
print("run" if no_upload or (not enforce) or hour in slots else "skip")
PY
)"

export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
export CLEANUP_ALL_ARTIFACTS
export BACKGROUND_PROVIDER
export OPENCLAW_NOTIFY_ON_FAILURE="1"

if [[ "$SLOT_STATUS" == "skip" ]]; then
  echo "[schedule] current hour is outside upload_slots_hours; skipping upload run"
  exit 0
fi

cleanup_output_artifacts

set +e
{
  topic_cmd=(
    "$PY_BIN" scripts/generate_topics.py \
    --config "$CONFIG" \
    --out jobs/topics.txt \
    --history jobs/topics_history.txt \
    --count "$GEN_TOPIC_COUNT" \
  )

  if [[ -n "$NICHE" ]]; then
    topic_cmd+=(--niche "$NICHE")
  fi
  if [[ -n "$STYLE" ]]; then
    topic_cmd+=(--style "$STYLE")
  fi
  topic_cmd+=(--style-mode "$STYLE_MODE")

  "${topic_cmd[@]}"

  topic_count="$(
    grep -Ev '^\s*(#|$)' jobs/topics.txt 2>/dev/null | wc -l | tr -d ' '
  )"
  required_count="$COUNT"
  if [[ -z "$topic_count" ]]; then
    topic_count="0"
  fi
  if [[ "$topic_count" -lt "$required_count" ]]; then
    echo "topic generation failed to provide unique set (got $topic_count, need $required_count)"
    exit 1
  fi

  cmd=("$PY_BIN" scripts/run_daily.py --config "$CONFIG" --topics-file jobs/topics.txt --count "$COUNT" --target-seconds "$TARGET_SECONDS" --tone "$TONE")
  if [[ "$STYLE_MODE" == "fixed" && -n "$STYLE" ]]; then
    cmd+=(--style "$STYLE")
  fi
  if [[ "$NO_UPLOAD" == "1" ]]; then
    cmd+=(--no-upload)
  fi

  echo "Running: ${cmd[*]}"
  "${cmd[@]}"
} 2>&1 | tee "$LOG_FILE"
rc="${PIPESTATUS[0]}"
set -e

if [[ "$rc" -ne 0 ]]; then
  notify_openclaw "run_scheduled failed (rc=$rc), config=$CONFIG, count=$COUNT, log=$LOG_FILE"
  exit "$rc"
fi
