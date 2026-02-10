#!/usr/bin/env bash
set -euo pipefail

echo "[ci] running in: $(pwd)"

PYTHON_BIN="python"
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

if [[ -f package.json ]] && command -v npm >/dev/null 2>&1; then
npm test
exit 0
fi

if [[ -f pyproject.toml || -f pytest.ini || -d tests ]]; then
  # Prefer pytest if available, otherwise fall back to stdlib unittest.
  if command -v pytest >/dev/null 2>&1; then
    pytest
    exit 0
  fi

  "$PYTHON_BIN" -m compileall -q .
  "$PYTHON_BIN" -m unittest discover -s tests
  exit 0
fi

if [[ -f Makefile ]]; then
make test
exit 0
fi

echo "[ci] No rule matched. Update scripts/ci.sh for this repo."
exit 2
