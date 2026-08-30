@echo off
title MMC Delta Scanner
cd /d "%~dp0"

echo ============================================
echo   MMC Delta Scanner - starting up
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found.
    echo Install Python 3.10 or newer: https://www.python.org/downloads/
    echo During installation, be sure to tick "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/3] First run - creating a virtual environment...
    py -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        echo Check your Python installation.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment found.
)

call ".venv\Scripts\activate.bat"

echo [2/3] Checking and installing libraries...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Libraries could not be installed. Check your internet connection.
    pause
    exit /b 1
)

echo [3/3] Launching the scanner...
echo.
echo Your browser should open automatically. Press Ctrl+C in this window to stop.
echo.

REM A local run means a single user, so the settings file is safe to use.
set MMC_LOCAL_SETTINGS=1

python -m streamlit run app.py

pause
