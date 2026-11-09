#!/bin/bash
# Builds the macOS installer disk image:  dist/IEEE-Paper-Checker-<version>-macOS-<arch>.dmg
# Run on a Mac (Apple-silicon Mac -> arm64 build, Intel Mac -> x86_64 build).
# People who USE the .dmg need nothing - Python is bundled inside the app.
set -e
cd "$(dirname "$0")"
python3 -m venv .buildenv
source .buildenv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt pyinstaller
python installer/make_icons.py
pyinstaller --noconfirm --clean --distpath dist --workpath build installer/ieee_checker.spec
VER=$(python -c "import ieee_checker; print(ieee_checker.__version__)")
ARCH=$(uname -m)
STAGE=build/dmg
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/IEEE-Paper-Checker.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
DMG="dist/IEEE-Paper-Checker-$VER-macOS-$ARCH.dmg"
rm -f "$DMG"
hdiutil create -volname "IEEE Paper Checker" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo
echo "Installer ready: $DMG"
echo "Open it and drag 'IEEE-Paper-Checker' onto 'Applications'."
