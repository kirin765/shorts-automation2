#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/3] System deps (ffmpeg, venv)"
sudo apt-get update -y
sudo apt-get install -y ffmpeg python3-venv

echo "[2/3] Python venv + deps"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt

echo "[3/3] Done"
echo "Try: python run_short.py --config config.json --job jobs/today.json --no-upload"

