@echo off
rem job-hub launcher v6 (portable, auto-detect python, delegates to bootstrap)
setlocal
cd /d "%~dp0"

echo ==========================================
echo   job-hub dashboard launcher
echo ==========================================
echo.

rem --- Detect a usable Python interpreter ---
set "PY="
if exist "C:\Users\12990\.workbuddy\binaries\python\versions\3.13.12\python.exe" set "PY=C:\Users\12990\.workbuddy\binaries\python\versions\3.13.12\python.exe"
if not defined PY for /f "delims=" %%p in ('where python 2^>nul') do if not defined PY set "PY=%%p"
if not defined PY for /f "delims=" %%p in ('where py 2^>nul') do if not defined PY set "PY=%%p"
if not defined PY (
  echo   [FAIL] Python not found. Install Python 3.8+ and add it to PATH.
  pause
  exit /b 1
)
echo   Python  : %PY%

rem --- Delegate to the bootstrap assistant (env check + deps + config + start) ---
"%PY%" "%~dp0jobhub\bootstrap.py" serve

echo.
pause
