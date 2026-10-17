@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Existing AURA .venv not found. No packages were installed.
  pause
  exit /b 1
)
set AURA_WORKSPACE=1
".venv\Scripts\python.exe" run_aura_body.py
pause
