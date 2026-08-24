#!/usr/bin/env bash
# MMC Delta Scanner - launcher for Linux and macOS.
# On Windows, use RUN_MMC_SCANNER.bat instead.
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================"
echo "  MMC Delta Scanner - starting up"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found. Please install Python 3.10 or newer."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[1/3] First run - creating a virtual environment..."
    python3 -m venv .venv
else
    echo "[1/3] Virtual environment found."
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/3] Checking and installing libraries..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

echo "[3/3] Launching the scanner..."
echo
echo "Your browser should open automatically. Press Ctrl+C here to stop."
echo

# A local run means a single user, so the settings file is safe to use.
export MMC_LOCAL_SETTINGS=1

exec python -m streamlit run app.py
