#!/usr/bin/env bash
set -euo pipefail

# Wrapper intended for cron/Task Scheduler.
# It generates fresh topics then runs the daily queue.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Prevent overlapping runs (cron can fire while a previous run is still executing).
LOCKFILE="${LOCKFILE:-/tmp/shorts_automation2.lock}"
if [[ "${_LOCKED:-0}" != "1" ]] && command -v flock >/dev/null 2>&1; then
  export _LOCKED=1
  exec flock -n "$LOCKFILE" "$0" "$@"
fi
LOCKDIR="${LOCKDIR:-/tmp/shorts_automation2.lockdir}"
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

CONFIG="${CONFIG:-ENV}"
COUNT="${COUNT:-1}"
NO_UPLOAD="${NO_UPLOAD:-0}"   # 1 to skip upload
TARGET_SECONDS="${TARGET_SECONDS:-28}"
NICHE="${NICHE:-?뚰겕/AI/?명꽣???몃젋??"
STYLE="${STYLE:-?뚰겕 ?댁뒪, ??臾몄옣 吏㏐쾶}"
TONE="${TONE:-鍮좊Ⅴ怨??먯떊?덇쾶}"
GEN_TOPIC_COUNT="${GEN_TOPIC_COUNT:-10}"

if [[ "$COUNT" -gt "$GEN_TOPIC_COUNT" ]]; then
  GEN_TOPIC_COUNT="$COUNT"
fi

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

python3 scripts/generate_topics.py \
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

cmd=(python3 scripts/run_daily.py --config "$CONFIG" --topics-file jobs/topics.txt --count "$COUNT" --target-seconds "$TARGET_SECONDS" --style "$STYLE" --tone "$TONE")
if [[ "$NO_UPLOAD" == "1" ]]; then
  cmd+=(--no-upload)
fi

echo "Running: ${cmd[*]}"
exec "${cmd[@]}"
