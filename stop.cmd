@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv-portable\Scripts\python.exe" (
  ".venv-portable\Scripts\python.exe" hermes.py stop
) else (
  ".venv\Scripts\python.exe" hermes.py stop
)
exit /b %ERRORLEVEL%
