@echo off
REM Launcher for the Broomarr GUI (docs/design/gui-design.md). Starts the
REM NiceGUI app bound to localhost only - see tests/test_no_gui_dependency.py
REM for the check that keeps it that way. --no-pause exits cleanly instead
REM of leaving the window open - see feedback_windows.md.
title Broomarr GUI
set START_TIME=%TIME%
cd /d "%~dp0.."

if not exist "config\config.json" (
    echo [ERROR] config\config.json not found.
    echo Copy config\config.example.json to config\config.json and fill in your Sonarr/Tautulli API keys.
    if not "%1"=="--no-pause" cmd /k
    exit /b 1
)

python -m gui.main

echo.
echo ============================================================
echo [DONE] Broomarr GUI stopped. Start: %START_TIME%  End: %TIME%
echo ============================================================
echo.
if not "%1"=="--no-pause" cmd /k
