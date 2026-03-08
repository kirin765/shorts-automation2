#!/usr/bin/env bash
set -euo pipefail

CONFIG="ENV"
if [[ "$CONFIG" == "ENV" && -f "config.json" ]]; then
  CONFIG="config.json"
fi
QUEUE_DIR="jobs/queue"
DONE_DIR="jobs/done"
FAILED_DIR="jobs/failed"
LOG_DIR="logs"
RETRIES=3
SLEEP_S=3
NO_UPLOAD=0
CLEANUP_ALL_ARTIFACTS=0
LAST_RESULT_LINE=""

usage() {
  cat <<'EOF'
Usage:
  scripts/run_queue.sh [--config config.json] [--queue-dir jobs/queue] [--no-upload]
                       [--cleanup-all-artifacts] [--retries 3] [--sleep 3] [--done-dir jobs/done] [--failed-dir jobs/failed]

Behavior:
  - Runs each *.json in the queue directory (sorted) through run_short.py
  - Retries failures
  - Moves succeeded jobs to done dir, failed jobs to failed dir
  - Writes a per-run log under logs/
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --queue-dir) QUEUE_DIR="$2"; shift 2 ;;
    --done-dir) DONE_DIR="$2"; shift 2 ;;
    --failed-dir) FAILED_DIR="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --retries) RETRIES="$2"; shift 2 ;;
    --sleep) SLEEP_S="$2"; shift 2 ;;
    --no-upload) NO_UPLOAD=1; shift ;;
    --cleanup-all-artifacts) CLEANUP_ALL_ARTIFACTS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 2 ;;
  esac
done

mkdir -p "$QUEUE_DIR" "$DONE_DIR" "$FAILED_DIR" "$LOG_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/run_queue_${STAMP}.log"

python_cmd() {
  local py_bin="python3"
  if [[ -x ".venv/bin/python" ]]; then
    py_bin=".venv/bin/python"
  elif command -v python >/dev/null 2>&1; then
    py_bin="python"
  elif ! command -v "$py_bin" >/dev/null 2>&1; then
    echo "python interpreter not found (python/python3/.venv/bin/python)" >&2
    return 127
  fi

  local cleanup_flag=()
  if [[ "$CLEANUP_ALL_ARTIFACTS" -eq 1 ]]; then
    cleanup_flag=(--cleanup-all-artifacts)
  fi
  local no_upload_flag=()
  if [[ "$NO_UPLOAD" -eq 1 ]]; then
    no_upload_flag=(--no-upload)
  fi
  local notify_on_failure="$1"
  local job="$2"

  OPENCLAW_NOTIFY_ON_FAILURE="$notify_on_failure" \
  "$py_bin" -u run_short.py --config "$CONFIG" --job "$job" "${cleanup_flag[@]}" "${no_upload_flag[@]}"
}

run_job() {
  local job="$1"
  local base
  base="$(basename "$job")"
  local tmp_out
  tmp_out="$(mktemp)"

  for attempt in $(seq 1 "$RETRIES"); do
    echo "=== JOB ${base} (attempt ${attempt}/${RETRIES}) ==="
    local notify_on_failure=1
    if [[ "$attempt" -lt "$RETRIES" ]]; then
      notify_on_failure=0
    fi

    set +e
    python_cmd "$notify_on_failure" "$job" 2>&1 | tee "$tmp_out"
    local rc="${PIPESTATUS[0]}"
    set -e

    local result_line=""
    # run_short.py prints RESULT ... as a single line near the end; keep the last one we saw.
    result_line="$(grep -E '^RESULT ' "$tmp_out" | tail -n 1 || true)"
    if [[ -n "$result_line" ]]; then
      LAST_RESULT_LINE="$result_line"
    fi

    if [[ "$rc" -eq 0 ]]; then
      echo "=== OK  ${base} ==="
      if [[ -n "$result_line" ]]; then
        # Make it easy to grep a one-line summary from queue logs.
        echo "$result_line"
      fi
      mv -f "$job" "$DONE_DIR/$base"
      rm -f "$tmp_out"
      return 0
    fi
    echo "=== FAIL ${base} ==="
    if [[ -n "$result_line" ]]; then
      echo "$result_line"
    fi
    if [[ "$attempt" -lt "$RETRIES" ]]; then
      sleep "$SLEEP_S"
    fi
  done

  mv -f "$job" "$FAILED_DIR/$base"
  rm -f "$tmp_out"
  return 1
}

{
  echo "Run started: $STAMP"
  echo "config=$CONFIG queue=$QUEUE_DIR no_upload=$NO_UPLOAD retries=$RETRIES sleep=$SLEEP_S"
  echo

  shopt -s nullglob
  jobs=("$QUEUE_DIR"/*.json)
  shopt -u nullglob

  if [[ ${#jobs[@]} -gt 0 ]]; then
    # Keep deterministic order without relying on bash>=4 mapfile/readarray.
    IFS=$'\n' jobs=($(printf '%s\n' "${jobs[@]}" | sort))
    unset IFS
  fi

  if [[ ${#jobs[@]} -eq 0 ]]; then
    echo "No jobs in $QUEUE_DIR"
    exit 0
  fi

  failed=0
  for j in "${jobs[@]}"; do
    if ! run_job "$j"; then
      failed=$((failed + 1))
    fi
    echo
  done

  if [[ "$failed" -gt 0 ]]; then
    echo "Run finished with failures: $failed"
    if [[ -n "$LAST_RESULT_LINE" ]]; then
      echo "$LAST_RESULT_LINE"
    fi
    exit 1
  fi

  echo "Run finished: all ok"
  if [[ -n "$LAST_RESULT_LINE" ]]; then
    echo "$LAST_RESULT_LINE"
  fi
} 2>&1 | tee "$LOG_FILE"
