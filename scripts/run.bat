@echo off
REM Launcher for Broomarr. Offers the two modes broomarr.py supports:
REM   1. --all      scan the whole library
REM   2. one title   explain a single show
REM --no-pause skips the menu (defaults to a full scan) and exits cleanly
REM instead of leaving the window open - see feedback_windows.md.
title Broomarr
set START_TIME=%TIME%
cd /d "%~dp0.."

if not exist "config\config.json" (
    echo [ERROR] config\config.json not found.
    echo Copy config\config.example.json to config\config.json and fill in your Sonarr/Tautulli API keys.
    if not "%1"=="--no-pause" cmd /k
    exit /b 1
)

if "%1"=="--no-pause" (
    set MODE=1
) else (
    echo.
    echo #######################
    echo     Broomarr
    echo #######################
    echo.
    echo   1. Scan whole library  (--all)
    echo   2. Explain one show
    echo.
    set /p MODE="Choose [1/2]: "
    echo.
)

REM The prompt and its use must not share a parenthesised block: batch
REM expands %SHOWTITLE% when it parses the block, which is before set /p
REM has run, so an if/else here would always pass an empty title.
if "%MODE%"=="2" goto explain

python src\broomarr.py --all
goto finished

:explain
set /p SHOWTITLE="Show title: "
python src\broomarr.py "%SHOWTITLE%"

:finished
echo.
echo ============================================================
echo [DONE] Broomarr finished. Start: %START_TIME%  End: %TIME%
echo ============================================================
echo.
if not "%1"=="--no-pause" cmd /k
