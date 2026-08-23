#!/usr/bin/env bash
# MMC Delta Scanner - Linux / macOS launcher
# Windows par RUN_MMC_SCANNER.bat use karein.
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================"
echo "  MMC Delta Scanner - starting up"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 nahi mila. Python 3.10+ install karein."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "[1/3] Pehli baar chala rahe hain - virtual environment bana rahe hain..."
    python3 -m venv .venv
else
    echo "[1/3] Virtual environment mil gaya."
fi

# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/3] Libraries check / install kar rahe hain..."
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet

echo "[3/3] Scanner launch kar rahe hain..."
echo
echo "Browser apne aap khulega. Band karne ke liye Ctrl+C dabaiye."
echo

# Local run = ek hi user, isliye settings file safe hai.
export MMC_LOCAL_SETTINGS=1

exec python -m streamlit run app.py
