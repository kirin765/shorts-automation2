#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export LANG="${LANG:-en_US.UTF-8}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"
export CLEANUP_ALL_ARTIFACTS="${CLEANUP_ALL_ARTIFACTS:-1}"

mkdir -p logs
exec ./scripts/run_scheduled.sh >> "logs/cron_$(date +%Y%m%d).log" 2>&1
