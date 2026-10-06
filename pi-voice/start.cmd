@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment missing. See README.md.
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
set "HF_HUB_DISABLE_TELEMETRY=1"
set "DO_NOT_TRACK=1"
".venv\Scripts\python.exe" -m pi_voice %*
exit /b %errorlevel%
