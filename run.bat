@echo off
REM ============================================================
REM STRAVA WEEKLY MILEAGE COMPILER (Windows)
REM ============================================================
REM Double-click this file every Monday to update the Google Sheet.
REM
REM What happens:
REM   1. Chrome opens to Strava login page
REM   2. You log in (enter email + verification code from your email)
REM   3. Script scrapes the data and updates Google Sheet
REM   4. Done!
REM ============================================================

cd /d "%~dp0"

echo.
echo ==========================================
echo   STRAVA WEEKLY MILEAGE COMPILER
echo ==========================================
echo.

REM Pull latest code from GitHub (if this is a git clone)
git pull origin main 2>nul

REM Install/update dependencies quietly
pip install -r requirements.txt -q 2>nul

echo.
echo   Chrome will open now.
echo   Log in to Strava, then wait here.
echo.
echo ==========================================
echo.

python main.py

echo.
echo ==========================================
if %ERRORLEVEL% EQU 0 (
    echo   DONE! Google Sheet has been updated.
    echo   You can close this window.
) else (
    echo   Something went wrong.
    echo   Take a screenshot and send to the developer.
)
echo ==========================================
echo.
pause
