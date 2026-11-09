@echo off
REM Run from source (no build). First run installs the libraries (needs internet once).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run: setting up, please wait...
  python -m venv .venv || (echo Install Python 3.9+ from https://www.python.org first & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe ieee_format_checker.py
