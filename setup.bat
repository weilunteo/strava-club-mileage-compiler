@echo off
REM ============================================================
REM STRAVA MILEAGE COMPILER - DIVISION SETUP (ONE-TIME)
REM ============================================================
REM Run this ONCE when everyone has joined the Strava club.
REM Re-run only if new members join or roster.json changes.
REM ============================================================

cd /d "%~dp0"

echo.
echo ==========================================
echo   DIVISION SETUP (One-Time)
echo ==========================================
echo.

python setup_divisions.py

echo.
echo ==========================================
echo   Setup complete. From now on, run:
echo     run.bat  (or double-click it)
echo ==========================================
echo.
pause
