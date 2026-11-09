#!/bin/bash
# First run installs the libraries (needs internet once). Needs python3-venv + python3-tk.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up, please wait..."
  python3 -m venv .venv && .venv/bin/python -m pip install -q -r requirements.txt
fi
.venv/bin/python ieee_format_checker.py "$@"
