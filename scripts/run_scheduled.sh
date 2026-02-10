#!/usr/bin/env bash
set -euo pipefail

# Wrapper intended for cron/Task Scheduler.
# It generates fresh topics then runs the daily queue.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG="${CONFIG:-config.json}"
COUNT="${COUNT:-1}"
NO_UPLOAD="${NO_UPLOAD:-0}"   # 1 to skip upload
TARGET_SECONDS="${TARGET_SECONDS:-28}"
NICHE="${NICHE:-테크/AI/인터넷 트렌드}"
STYLE="${STYLE:-테크 뉴스, 한 문장 짧게}"
TONE="${TONE:-빠르고 자신있게}"

if [[ -f ".venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi

python3 scripts/generate_topics.py \
  --config "$CONFIG" \
  --out jobs/topics.txt \
  --history jobs/topics_history.txt \
  --count 10 \
  --niche "$NICHE" \
  --style "$STYLE"

cmd=(python3 scripts/run_daily.py --config "$CONFIG" --topics-file jobs/topics.txt --count "$COUNT" --target-seconds "$TARGET_SECONDS" --style "$STYLE" --tone "$TONE")
if [[ "$NO_UPLOAD" == "1" ]]; then
  cmd+=(--no-upload)
fi

echo "Running: ${cmd[*]}"
exec "${cmd[@]}"

