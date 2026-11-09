"""End-to-end test of an INSTALLED / BUILT checker (used by the GitHub build on
Windows, macOS and Linux).

    python tests/ci_check.py <path-to-checker-executable> [extra args...]

Runs the checker on two sample papers and verifies that
  * it finds exactly the problems planted in tests/samples/sample_errors.pdf,
  * the clean sample only fails the "not certified by IEEE PDF eXpress" rule,
  * the HTML report and the annotated PDF are written and look valid.
Only the Python standard library is used, so it runs anywhere.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")

EXPECTED_ERRORS = {               # substring that must appear in some ERROR finding
    "paper size not A4": "not A4",
    "uncited references [4], [5]": "never cited",
    "citation [8] missing from list": "[8]",
    "mention of non-existent Fig. 5": "Fig. 5",
    "mention of non-existent Eq. (9)": "(9)",
    "mention of non-existent Section VII": "Section VII",
    "Fig. 2 never mentioned": "Fig. 2",
    "bookmarks present": "bookmark",
    "not certified by PDF eXpress": "not certified",
}


def run(exe, pdf, out):
    cmd = list(exe) + [pdf, "--json", "--out", out]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300)
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        print("Could not read JSON output. Command:", cmd)
        print("STDOUT:", p.stdout[-3000:])
        print("STDERR:", p.stderr[-3000:])
        raise
    return p.returncode, data


def check_outputs(out, name, failures):
    html = os.path.join(out, name + "_IEEE_report.html")
    pdf = os.path.join(out, name + "_IEEE_annotated.pdf")
    for path, head in ((html, b"<!doctype html"), (pdf, b"%PDF")):
        if not os.path.isfile(path):
            failures.append(f"missing output file {os.path.basename(path)}")
            continue
        with open(path, "rb") as fh:
            start = fh.read(64)
        if not start.lower().startswith(head.lower()) or os.path.getsize(path) < 5000:
            failures.append(f"output file looks invalid: {os.path.basename(path)}")
    src = os.path.join(SAMPLES, name + ".pdf")
    if os.path.isfile(pdf) and os.path.getsize(pdf) <= os.path.getsize(src) // 2:
        failures.append("annotated PDF is suspiciously small")


def main():
    exe = sys.argv[1:]
    if not exe:
        sys.exit(__doc__)
    if os.path.isfile(exe[0]):
        exe[0] = os.path.abspath(exe[0])
    failures = []
    out = tempfile.mkdtemp(prefix="ieee_ci_")

    code, data = run(exe, os.path.join(SAMPLES, "sample_errors.pdf"), out)
    errors = [f["message"] for f in data["findings"] if f["severity"] == "error"]
    print(f"sample_errors.pdf: exit code {code}, {len(errors)} error(s)")
    for label, needle in EXPECTED_ERRORS.items():
        ok = any(needle.lower() in m.lower() for m in errors)
        print(f"  [{'OK ' if ok else 'FAIL'}] detects {label}")
        if not ok:
            failures.append(f"did not detect: {label}")
    if code != 1:
        failures.append(f"exit code should be 1 when errors are found, got {code}")
    if len(data.get("citations", [])) < 5:
        failures.append("citation table missing")
    check_outputs(out, "sample_errors", failures)

    code, data = run(exe, os.path.join(SAMPLES, "sample_ok.pdf"), out)
    errors = [f["message"] for f in data["findings"] if f["severity"] == "error"]
    print(f"sample_ok.pdf: exit code {code}, {len(errors)} error(s)")
    unexpected = [m for m in errors if "not certified" not in m.lower()]
    for m in unexpected:
        print("  [FAIL] unexpected error:", m[:150])
    if unexpected:
        failures.append(f"{len(unexpected)} unexpected error(s) on the clean sample")
    else:
        print("  [OK ] clean sample only lacks the PDF eXpress stamp")
    check_outputs(out, "sample_ok", failures)

    if failures:
        print("\nFAILED:\n  - " + "\n  - ".join(failures))
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
