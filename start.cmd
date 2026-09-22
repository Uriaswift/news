@echo off
cd /d "%~dp0"
if exist ".venv-portable\Scripts\pythonw.exe" (
  start "" ".venv-portable\Scripts\pythonw.exe" hermes.py run
) else if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" hermes.py run
) else (
  echo Run setup_windows.ps1 first.
  pause
  exit /b 1
)
