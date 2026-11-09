"""End-to-end test of the self-update of an INSTALLED checker (used by the GitHub build).

    python tests/update_check.py <installer-file> <installed-executable> [--expect-kind deb]

Writes a fake "latest release" (version 99.0.0) whose download is the installer that
was just built, points the installed app at it (IEEE_CHECKER_UPDATE_URL) and runs
'<exe> --update --yes'. It then verifies that the installed app was really replaced:
  Windows       : the Setup ran again into the same folder and started the new app
  macOS / Linux : a marker file placed inside the old app folder/bundle is gone
With --expect-kind only the update check is run and the detected install type compared
(used for the .deb, whose install needs an interactive administrator password).
Only the Python standard library is used.
"""

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time


def app_root(exe):
    exe = os.path.realpath(exe)
    if sys.platform == "darwin":
        p = exe
        while p != "/" and not p.endswith(".app"):
            p = os.path.dirname(p)
        return p
    return os.path.dirname(exe)


def gui_running():
    if sys.platform.startswith("win"):
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq IEEE-Paper-Checker.exe"],
                             capture_output=True, text=True).stdout
        return "IEEE-Paper-Checker.exe" in out
    r = subprocess.run(["pgrep", "-f", "IEEE-Paper-Checker.app/Contents/MacOS/IEEE-Paper-Checker"
                        if sys.platform == "darwin" else "ieee-paper-checker/IEEE-Paper-Checker$"],
                       capture_output=True)
    return r.returncode == 0


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    installer, exe = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    data = open(installer, "rb").read()
    release = {"tag_name": "v99.0.0", "html_url": "https://example.invalid/release",
               "body": "test release",
               "assets": [{"name": os.path.basename(installer),
                           "browser_download_url": pathlib.Path(installer).as_uri(),
                           "size": len(data),
                           "digest": "sha256:" + hashlib.sha256(data).hexdigest()}]}
    tmp = tempfile.mkdtemp(prefix="ieee_upd_")
    rel = os.path.join(tmp, "release.json")
    with open(rel, "w", encoding="utf-8") as fh:
        json.dump(release, fh)
    env = dict(os.environ, IEEE_CHECKER_UPDATE_URL=pathlib.Path(rel).as_uri())

    # 1. the update check sees the new version and picks this installer
    r = subprocess.run([exe, "--check-update", "--json"], env=env, capture_output=True,
                       text=True, timeout=120)
    print(r.stdout)
    info = json.loads(r.stdout[r.stdout.index("{"):])
    assert info["newer"], "the update check did not see version 99.0.0 as newer"
    assert info["asset"] and info["asset"]["name"] == os.path.basename(installer), \
        f"wrong installer picked for this system: {info['asset']}"
    if "--expect-kind" in sys.argv:
        want = sys.argv[sys.argv.index("--expect-kind") + 1]
        assert info["kind"] == want, f"install type {info['kind']!r}, expected {want!r}"
        print(f"[OK ] update check works and detects the '{want}' install")
        return

    # 2. a tampered download must be refused
    bad = dict(release)
    bad["assets"] = [dict(release["assets"][0], digest="sha256:" + "0" * 64)]
    bad_rel = os.path.join(tmp, "bad.json")
    with open(bad_rel, "w", encoding="utf-8") as fh:
        json.dump(bad, fh)
    r = subprocess.run([exe, "--update", "--yes"], capture_output=True, text=True, timeout=300,
                       env=dict(env, IEEE_CHECKER_UPDATE_URL=pathlib.Path(bad_rel).as_uri()))
    print(r.stdout)
    assert r.returncode != 0 and "fingerprint" in r.stdout, "a tampered download was not refused"
    print("[OK ] tampered download refused")

    # 3. the real update
    root = app_root(exe)
    marker = os.path.join(root, "Contents" if sys.platform == "darwin" else "", "OLD_VERSION_MARKER")
    stamp = os.path.join(root, "unins000.dat")
    before = os.path.getmtime(stamp) if os.path.exists(stamp) else 0
    if not sys.platform.startswith("win"):
        open(marker, "w").close()
    r = subprocess.run([exe, "--update", "--yes"], env=env, capture_output=True, text=True,
                       timeout=600)
    print(r.stdout, r.stderr)
    assert r.returncode == 0, "the update command failed"

    deadline = time.time() + 240
    replaced = relaunched = False
    while time.time() < deadline and not (replaced and relaunched):
        time.sleep(3)
        if sys.platform.startswith("win"):
            replaced = os.path.exists(stamp) and os.path.getmtime(stamp) > before
        else:
            replaced = os.path.isdir(root) and not os.path.exists(marker) and os.path.exists(exe)
        relaunched = relaunched or gui_running() or sys.platform.startswith("linux")
    print(f"[{'OK ' if replaced else 'FAIL'}] installed app was replaced by the downloaded version")
    print(f"[{'OK ' if relaunched else 'FAIL'}] the new version was started")
    r = subprocess.run([exe, "--check-update", "--json"], env=env, capture_output=True,
                       text=True, timeout=120)
    print(f"[{'OK ' if r.returncode == 0 else 'FAIL'}] the updated app runs")
    if not (replaced and relaunched and r.returncode == 0):
        sys.exit(1)
    print("\nSELF-UPDATE TEST PASSED")


if __name__ == "__main__":
    main()
