#!/usr/bin/env bash
set -euo pipefail

# One-command runner for daily operations.
# - Runs scripts/run_scheduled.sh
# - Writes a timestamped log under logs/
# - Prints the last RESULT line (if present) for quick grep

usage() {
  cat <<'EOF'
Usage:
  scripts/run_once.sh [--config config.json] [--no-upload] [--count N] [--target-seconds N]
                      [--niche "text"] [--style "text"] [--tone "text"]

Environment equivalents (override defaults):
  CONFIG, NO_UPLOAD=1, COUNT, TARGET_SECONDS, NICHE, STYLE, TONE

Output:
  - logs/run_once_YYYYMMDD_HHMMSS.log
  - prints last "RESULT ..." line to stdout when available
EOF
}

CONFIG="${CONFIG:-config.json}"
NO_UPLOAD="${NO_UPLOAD:-0}"
COUNT="${COUNT:-1}"
TARGET_SECONDS="${TARGET_SECONDS:-28}"
NICHE="${NICHE:-테크/AI/인터넷 트렌드}"
STYLE="${STYLE:-테크 뉴스, 한 문장 짧게}"
TONE="${TONE:-빠르고 자신있게}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --no-upload) NO_UPLOAD=1; shift ;;
    --count) COUNT="$2"; shift 2 ;;
    --target-seconds) TARGET_SECONDS="$2"; shift 2 ;;
    --niche) NICHE="$2"; shift 2 ;;
    --style) STYLE="$2"; shift 2 ;;
    --tone) TONE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p logs

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="logs/run_once_${STAMP}.log"

# Ensure Python output is line-buffered in logs.
export PYTHONUNBUFFERED=1

set +e
CONFIG="$CONFIG" \
NO_UPLOAD="$NO_UPLOAD" \
COUNT="$COUNT" \
TARGET_SECONDS="$TARGET_SECONDS" \
NICHE="$NICHE" \
STYLE="$STYLE" \
TONE="$TONE" \
  scripts/run_scheduled.sh 2>&1 | tee "$LOG_FILE"
rc="${PIPESTATUS[0]}"
set -e

last_result="$(grep -E '^RESULT ' "$LOG_FILE" | tail -n 1 || true)"
if [[ -n "$last_result" ]]; then
  echo "$last_result"
fi

exit "$rc"

