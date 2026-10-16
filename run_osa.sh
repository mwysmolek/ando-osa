#!/usr/bin/env bash
# kayEi SpectrumStudio launcher (Linux / macOS): creates a local venv on first run.
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements-desktop.txt
fi
exec .venv/bin/python -m osa_qt.app "$@"
