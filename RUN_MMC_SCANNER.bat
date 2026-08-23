@echo off
title MMC Delta Scanner
cd /d "%~dp0"

echo ============================================
echo   MMC Delta Scanner - starting up
echo ============================================
echo.

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python nahi mila.
    echo Python 3.10+ install karein: https://www.python.org/downloads/
    echo Install karte waqt "Add Python to PATH" zaroor tick karein.
    echo.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo [1/3] Pehli baar chala rahe hain - virtual environment bana rahe hain...
    py -m venv .venv
    if errorlevel 1 (
        echo [ERROR] venv nahi bana. Python installation check karein.
        pause
        exit /b 1
    )
) else (
    echo [1/3] Virtual environment mil gaya.
)

call ".venv\Scripts\activate.bat"

echo [2/3] Libraries check / install kar rahe hain...
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Libraries install nahi hui. Internet connection check karein.
    pause
    exit /b 1
)

echo [3/3] Scanner launch kar rahe hain...
echo.
echo Browser apne aap khulega. Band karne ke liye is window mein Ctrl+C dabaiye.
echo.

REM Local run = ek hi user, isliye settings file safe hai.
set MMC_LOCAL_SETTINGS=1

python -m streamlit run app.py

pause
