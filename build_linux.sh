#!/bin/bash
# Builds Linux installers:
#   dist/ieee-paper-checker_<version>_amd64.deb         (Ubuntu, Debian, Mint, Pop!_OS ...)
#   dist/IEEE-Paper-Checker-<version>-linux-x64.tar.gz  (any distro: unpack, run ./install.sh)
# Build needs python3-venv and python3-tk:  sudo apt install python3-venv python3-tk
# People who USE the packages need nothing - Python is bundled inside.
set -e
cd "$(dirname "$0")"
python3 -m venv .buildenv
source .buildenv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt pyinstaller
python installer/make_icons.py
pyinstaller --noconfirm --clean --distpath dist --workpath build installer/ieee_checker.spec
VER=$(python -c "import ieee_checker; print(ieee_checker.__version__)")
bash installer/linux/make_packages.sh "$VER"
