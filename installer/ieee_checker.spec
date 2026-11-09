# PyInstaller spec used by the installer builds (all platforms).
# Produces a folder build (fast start-up) with:
#   IEEE-Paper-Checker(.exe)  - desktop app
#   ieee-check(.exe)          - command-line tool   (Windows / Linux)
# and on macOS an app bundle IEEE-Paper-Checker.app
import os
import sys

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ASSETS = os.path.join(ROOT, "installer", "assets")
sys.path.insert(0, ROOT)
from ieee_checker import __version__  # noqa: E402

is_mac = sys.platform == "darwin"
is_win = sys.platform.startswith("win")
icon = os.path.join(ASSETS, "icon.icns" if is_mac else "icon.ico")

a = Analysis(
    [os.path.join(ROOT, "ieee_format_checker.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ASSETS, "icon_256.png"), "assets"),
           (os.path.join(ASSETS, "logo_banner.png"), "assets")],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "torch",
              "tensorflow", "cv2", "sklearn", "notebook", "jupyter", "lxml"],
)
pyz = PYZ(a.pure)

gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="IEEE-Paper-Checker",
          console=False, icon=icon, argv_emulation=is_mac, upx=False)
exes = [gui]
if not is_mac:
    cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ieee-check",
              console=True, icon=icon, upx=False)
    exes.append(cli)

coll = COLLECT(*exes, a.binaries, a.datas, name="IEEE-Paper-Checker", upx=False)

if is_mac:
    app = BUNDLE(
        coll,
        name="IEEE-Paper-Checker.app",
        icon=icon,
        bundle_identifier="org.ieeepaperchecker.app",
        version=__version__,
        info_plist={
            "CFBundleDisplayName": "IEEE Paper Checker",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PDF document",
                "CFBundleTypeRole": "Viewer",
                "LSItemContentTypes": ["com.adobe.pdf"],
                "LSHandlerRank": "Alternate",
            }],
        },
    )
