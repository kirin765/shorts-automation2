#!/usr/bin/env bash
set -euo pipefail

# Wrapper intended for cron/Task Scheduler.
# It generates fresh topics then runs the daily queue.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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
COUNT="${COUNT:-1}"
NO_UPLOAD="${NO_UPLOAD:-0}"   # 1 to skip upload
TARGET_SECONDS="${TARGET_SECONDS:-28}"
NICHE="${NICHE:-테크/AI/인터넷 트렌드}"
STYLE="${STYLE:-테크 뉴스, 한 문장 짧게}"
TONE="${TONE:-빠르고 자신있게}"
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

export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH:-}"
export CLEANUP_ALL_ARTIFACTS
export BACKGROUND_PROVIDER
export OPENCLAW_NOTIFY_ON_FAILURE="1"

set +e
{
  "$PY_BIN" scripts/generate_topics.py \
    --config "$CONFIG" \
    --out jobs/topics.txt \
    --history jobs/topics_history.txt \
    --count "$GEN_TOPIC_COUNT" \
    --niche "$NICHE" \
    --style "$STYLE"

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

  cmd=("$PY_BIN" scripts/run_daily.py --config "$CONFIG" --topics-file jobs/topics.txt --count "$COUNT" --target-seconds "$TARGET_SECONDS" --style "$STYLE" --tone "$TONE")
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
