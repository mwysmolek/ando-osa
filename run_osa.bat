@echo off
REM kayEi SpectrumStudio launcher (Windows): creates a local venv on first run.
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\pip install -q -r requirements-desktop.txt
)
.venv\Scripts\python -m osa_qt.app %*
