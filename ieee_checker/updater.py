"""Self-update from the GitHub Releases of the project.

Only runs when the user asks for it (the checker itself stays fully offline).

    info = check()                 # {"current", "latest", "newer", "asset", ...}
    path = download(info["asset"], progress)
    restart_needed = install(path) # True -> the caller must quit now

How each platform updates itself
  Windows : runs the new Setup.exe silently into the same folder; it closes this
            app, replaces the files and starts the new version (/RELAUNCH=1).
  macOS   : mounts the new .dmg, swaps the .app bundle in place, starts it.
  Linux   : .deb install (/opt, owned by root) -> "pkexec dpkg -i" (asks for the
            password in a normal system dialog); per-user install from the
            .tar.gz (~/.local/opt) -> swaps the app folder, no password.
Every download is checked against the SHA-256 digest GitHub publishes for it.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request

from . import __version__

REPO = "shubhams-work/IEEE-conference-"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
# IEEE_CHECKER_UPDATE_URL lets the tests point the updater at a local release description
API_URL = os.environ.get("IEEE_CHECKER_UPDATE_URL",
                         f"https://api.github.com/repos/{REPO}/releases/latest")
APP_EXE = "IEEE-Paper-Checker"


class UpdateError(Exception):
    pass


# ----------------------------------------------------------------- helpers
def _ssl_context():
    """HTTPS context that also works inside the frozen app (macOS has no system
    certificates for the bundled OpenSSL, so use certifi when it is bundled)."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


def _open(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"IEEE-Paper-Checker/{__version__}",
        "Accept": "application/vnd.github+json"})
    if url.startswith("file:") and API_URL.startswith("file:"):    # test mode only
        return urllib.request.urlopen(req, timeout=timeout)
    if not url.startswith("https://"):
        raise UpdateError(f"refusing to download from a non-HTTPS address: {url}")
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())


def parse_version(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def install_kind() -> str:
    """windows | mac | deb | linux-user | source"""
    if not getattr(sys, "frozen", False):
        return "source"
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    d = app_dir()
    if d.startswith("/opt/") and not os.access(d, os.W_OK):
        return "deb"
    return "linux-user"


def app_dir() -> str:
    """Folder of the installed app (Windows/Linux) or the .app bundle (macOS)."""
    exe = os.path.realpath(sys.executable)
    if sys.platform == "darwin":
        p = exe
        while p and p != "/" and not p.endswith(".app"):
            p = os.path.dirname(p)
        return p if p.endswith(".app") else os.path.dirname(exe)
    return os.path.dirname(exe)


def _pick_asset(assets, kind):
    def find(pred):
        for a in assets:
            if pred(a["name"]):
                return a
        return None
    if kind == "windows":
        return find(lambda n: n.lower().endswith(".exe") and "setup" in n.lower())
    if kind == "mac":
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
        return find(lambda n: n.endswith(f"macOS-{arch}.dmg"))
    if kind == "deb":
        return find(lambda n: n.endswith("_amd64.deb"))
    if kind == "linux-user":
        return find(lambda n: n.endswith("-linux-x64.tar.gz"))
    return None


# ------------------------------------------------------------------- check
def check(timeout=20) -> dict:
    """Ask GitHub for the latest release. Raises UpdateError when offline etc."""
    try:
        with _open(API_URL, timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except UpdateError:
        raise
    except Exception as e:  # noqa: BLE001
        raise UpdateError("Could not reach GitHub to look for updates. Check your internet "
                          f"connection and try again.\n\n({e})") from e
    latest = (data.get("tag_name") or "").lstrip("vV")
    if not latest:
        raise UpdateError("GitHub did not return a release version.")
    kind = install_kind()
    asset = _pick_asset(data.get("assets") or [], kind)
    notes = (data.get("body") or "").strip()
    return {"current": __version__, "latest": latest,
            "newer": parse_version(latest) > parse_version(__version__),
            "kind": kind, "page": data.get("html_url") or RELEASES_PAGE,
            "notes": notes[:1500],
            "asset": None if not asset else {
                "name": asset["name"], "url": asset["browser_download_url"],
                "size": asset.get("size") or 0, "digest": asset.get("digest") or ""}}


# ---------------------------------------------------------------- download
def download(asset: dict, progress=None) -> str:
    """Download the installer to a temp folder and verify its SHA-256. Returns the path."""
    folder = tempfile.mkdtemp(prefix="ieee_checker_update_")
    path = os.path.join(folder, os.path.basename(asset["name"]))
    h = hashlib.sha256()
    total = asset.get("size") or 0
    got = 0
    try:
        with _open(asset["url"], 60) as r, open(path, "wb") as fh:
            total = total or int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress and total:
                    progress(min(got / total, 1.0))
    except Exception as e:  # noqa: BLE001
        raise UpdateError(f"The download failed: {e}") from e
    if total and got != total:
        raise UpdateError(f"The download is incomplete ({got} of {total} bytes). Try again.")
    want = (asset.get("digest") or "").lower()
    if want.startswith("sha256:") and h.hexdigest() != want.split(":", 1)[1]:
        os.remove(path)
        raise UpdateError("The downloaded file does not match the fingerprint (SHA-256) "
                          "published on GitHub, so it was not installed. Try again later.")
    return path


# ----------------------------------------------------------------- install
def install(path: str) -> bool:
    """Install the downloaded file. True = this process must exit now (the new
    version is started automatically)."""
    kind = install_kind()
    if kind == "windows":
        return _install_windows(path)
    if kind == "mac":
        return _install_mac(path)
    if kind == "deb":
        return _install_deb(path)
    if kind == "linux-user":
        return _install_linux_user(path)
    raise UpdateError("This copy runs from the source code; update it with 'git pull'.")


def _install_windows(setup: str) -> bool:
    d = app_dir()
    scope = "/CURRENTUSER" if os.access(d, os.W_OK) else "/ALLUSERS"  # all-users asks for admin
    args = [setup, "/SILENT", "/SP-", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
            scope, f"/DIR={d}", "/RELAUNCH=1"]
    flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=flags, close_fds=True)
    return True


def _relaunch_later(cmd):
    """Start the new version a moment after this process has gone."""
    subprocess.Popen(["/bin/sh", "-c", 'sleep 1.5; exec "$@"', "relaunch"] + cmd,
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _install_mac(dmg: str) -> bool:
    app = app_dir()
    if not app.endswith(".app"):
        raise UpdateError("Could not find the installed app bundle.")
    parent = os.path.dirname(app)
    if not os.access(parent, os.W_OK):
        subprocess.Popen(["open", dmg])
        raise UpdateError(f"No permission to replace the app in {parent}. The new version "
                          "has been opened - drag it onto Applications to finish.")
    mnt = tempfile.mkdtemp(prefix="ieee_dmg_")
    r = subprocess.run(["hdiutil", "attach", dmg, "-nobrowse", "-noautoopen", "-quiet",
                        "-mountpoint", mnt], capture_output=True, text=True)
    if r.returncode:
        raise UpdateError(f"Could not open the downloaded disk image: {r.stderr.strip()}")
    new_tmp, old_tmp = app + ".new", app + ".old"
    try:
        src = os.path.join(mnt, os.path.basename(app))
        if not os.path.isdir(src):
            src = next((os.path.join(mnt, n) for n in os.listdir(mnt) if n.endswith(".app")), "")
        if not src:
            raise UpdateError("The disk image does not contain the app.")
        shutil.rmtree(new_tmp, ignore_errors=True)
        r = subprocess.run(["ditto", src, new_tmp], capture_output=True, text=True)
        if r.returncode:
            raise UpdateError(f"Copying the new version failed: {r.stderr.strip()}")
    finally:
        subprocess.run(["hdiutil", "detach", mnt, "-quiet", "-force"], capture_output=True)
    shutil.rmtree(old_tmp, ignore_errors=True)
    os.rename(app, old_tmp)            # the running app keeps working from the old files
    try:
        os.rename(new_tmp, app)
    except OSError:
        os.rename(old_tmp, app)
        raise
    shutil.rmtree(old_tmp, ignore_errors=True)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", app], capture_output=True)
    _relaunch_later(["open", "-n", app])
    return True


def _install_deb(deb: str) -> bool:
    if not shutil.which("pkexec"):
        raise UpdateError("Installing needs administrator rights. Open a terminal and run:\n\n"
                          f"    sudo apt install '{deb}'")
    r = subprocess.run(["pkexec", "dpkg", "-i", deb], capture_output=True, text=True)
    if r.returncode in (126, 127):
        raise UpdateError("The update was cancelled (no administrator password given).")
    if r.returncode:
        raise UpdateError(f"Installing the update failed:\n{(r.stderr or r.stdout)[-800:]}")
    _relaunch_later([os.path.join(app_dir(), APP_EXE)])
    return True


def _install_linux_user(tgz: str) -> bool:
    import tarfile
    dest = app_dir()
    if not os.path.isfile(os.path.join(dest, APP_EXE)):
        raise UpdateError(f"Unexpected install folder: {dest}")
    work = tempfile.mkdtemp(prefix="ieee_tgz_")
    with tarfile.open(tgz) as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(work, filter="data")
        else:
            for m in tf.getmembers():
                if m.name.startswith("/") or ".." in m.name.split("/"):
                    raise UpdateError("Unsafe path in the downloaded archive.")
            tf.extractall(work)
    new = next((os.path.join(work, n, "app") for n in os.listdir(work)
                if os.path.isfile(os.path.join(work, n, "app", APP_EXE))), "")
    if not new:
        raise UpdateError("The downloaded archive does not contain the app.")
    old = dest + ".old"
    shutil.rmtree(old, ignore_errors=True)
    os.rename(dest, old)               # Linux keeps the running files alive
    try:
        shutil.move(new, dest)
    except OSError:
        os.rename(old, dest)
        raise
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    _relaunch_later([os.path.join(dest, APP_EXE)])
    return True


# --------------------------------------------------------------------- CLI
def cli(argv) -> int:
    """ieee-check --check-update      : print whether a newer version exists
       ieee-check --update [--yes]    : download and install it"""
    try:
        info = check()
    except UpdateError as e:
        print(f"ERROR: {e}")
        return 2
    if "--json" in argv:
        print(json.dumps(info, indent=2))
    else:
        print(f"Installed version: {info['current']}   Latest version: {info['latest']}")
    if "--check-update" in argv:
        return 0
    if not info["newer"] and "--force" not in argv:
        print("You already have the latest version.")
        return 0
    if not info["asset"]:
        print(f"No installer for this system in the release. Download it from {info['page']}")
        return 2
    if "--yes" not in argv:
        if input(f"Install version {info['latest']} now? [y/N] ").strip().lower() not in ("y", "yes"):
            return 0
    try:
        print(f"Downloading {info['asset']['name']} ...")
        path = download(info["asset"])
        print("Verified. Installing ...")
        install(path)
    except UpdateError as e:
        print(f"ERROR: {e}")
        return 2
    print(f"Updated to {info['latest']}. The new version starts on its own.")
    return 0
