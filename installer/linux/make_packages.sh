#!/bin/bash
# Wraps dist/IEEE-Paper-Checker/ (PyInstaller folder build) into a .deb and a .tar.gz
set -e
VER="$1"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
APP=dist/IEEE-Paper-Checker
[ -x "$APP/IEEE-Paper-Checker" ] || { echo "Run the PyInstaller build first."; exit 1; }

# ---------------------------------------------------------------- .deb
PKG="build/deb/ieee-paper-checker_${VER}_amd64"
rm -rf "$PKG"
mkdir -p "$PKG/DEBIAN" "$PKG/opt/ieee-paper-checker" "$PKG/usr/bin" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"
cp -a "$APP/." "$PKG/opt/ieee-paper-checker/"
ln -s /opt/ieee-paper-checker/IEEE-Paper-Checker "$PKG/usr/bin/ieee-paper-checker"
ln -s /opt/ieee-paper-checker/ieee-check "$PKG/usr/bin/ieee-check"
cp installer/assets/icon_256.png "$PKG/usr/share/icons/hicolor/256x256/apps/ieee-paper-checker.png"
cp installer/linux/ieee-paper-checker.desktop "$PKG/usr/share/applications/"
SIZE=$(du -sk "$PKG/opt" | cut -f1)
GLIBC=$(ldd --version | head -1 | grep -oE "[0-9]+\.[0-9]+$")   # binaries need this glibc or newer
{
  echo "Package: ieee-paper-checker"
  echo "Version: $VER"
  echo "Section: utils"
  echo "Priority: optional"
  echo "Architecture: amd64"
  echo "Installed-Size: $SIZE"
  echo "Depends: libc6 (>= $GLIBC), libx11-6, libxft2, libxss1, libfontconfig1"
  echo "Maintainer: IEEE Paper Format Checker <noreply@example.org>"
  echo "Description: Offline IEEE conference paper format checker"
  echo " Checks an IEEE conference paper PDF for formatting problems: margins,"
  echo " two-column layout, fonts, captions, references, tables pasted as images"
  echo " and image resolution. Produces an HTML report and an annotated PDF."
} > "$PKG/DEBIAN/control"
cp installer/linux/postinst "$PKG/DEBIAN/postinst"
chmod 755 "$PKG/DEBIAN/postinst"
dpkg-deb --build --root-owner-group "$PKG" "dist/ieee-paper-checker_${VER}_amd64.deb"

# ------------------------------------------------- .tar.gz for any distro
TGZ="build/tgz/IEEE-Paper-Checker-$VER"
rm -rf build/tgz && mkdir -p "$TGZ"
cp -a "$APP" "$TGZ/app"
cp installer/assets/icon_256.png "$TGZ/icon.png"
cp installer/linux/install.sh "$TGZ/install.sh"
chmod +x "$TGZ/install.sh"
tar -C build/tgz -czf "dist/IEEE-Paper-Checker-$VER-linux-x64.tar.gz" "IEEE-Paper-Checker-$VER"

echo
echo "Installers ready:"
echo "  dist/ieee-paper-checker_${VER}_amd64.deb      ->  sudo apt install ./ieee-paper-checker_${VER}_amd64.deb"
echo "  dist/IEEE-Paper-Checker-$VER-linux-x64.tar.gz  ->  unpack, then ./install.sh"
