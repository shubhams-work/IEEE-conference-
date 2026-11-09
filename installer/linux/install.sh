#!/bin/bash
# Installs IEEE Paper Format Checker for the current user (no sudo needed).
# Uninstall:  ./install.sh --uninstall
set -e
DEST="$HOME/.local/opt/ieee-paper-checker"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/256x256/apps"

if [ "$1" = "--uninstall" ]; then
  rm -rf "$DEST" "$BIN/ieee-paper-checker" "$BIN/ieee-check" \
         "$APPS/ieee-paper-checker.desktop" "$ICONS/ieee-paper-checker.png"
  echo "Uninstalled."
  exit 0
fi

cd "$(dirname "$0")"
mkdir -p "$BIN" "$APPS" "$ICONS" "$(dirname "$DEST")"
rm -rf "$DEST"
cp -a app "$DEST"
ln -sf "$DEST/IEEE-Paper-Checker" "$BIN/ieee-paper-checker"
ln -sf "$DEST/ieee-check" "$BIN/ieee-check"
cp icon.png "$ICONS/ieee-paper-checker.png"
{
  echo "[Desktop Entry]"
  echo "Type=Application"
  echo "Name=IEEE Paper Format Checker"
  echo "Comment=Check an IEEE conference paper PDF for formatting problems (offline)"
  echo "Exec=$DEST/IEEE-Paper-Checker %f"
  echo "Icon=ieee-paper-checker"
  echo "Terminal=false"
  echo "Categories=Office;Education;"
  echo "MimeType=application/pdf;"
} > "$APPS/ieee-paper-checker.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q "$APPS" || true
fi
echo "Installed. Find 'IEEE Paper Format Checker' in your applications menu,"
echo "or run:  ieee-paper-checker      (command line: ieee-check paper.pdf)"
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "Note: add $BIN to your PATH to use the commands from a terminal." ;;
esac
