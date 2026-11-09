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


EXPECTED_REVIEW = {               # double-blind review stage: substring in an error/warning
    "author block on title page": "author names / affiliations",
    "e-mail address": "e-mail address",
    "acknowledgment section": "acknowledgment section",
    "funding information": "funding",
    "author name in PDF properties": "properties contain an author",
    "first-person self-citation": "previous work",
    "code repository link": "code repository",
}

EXPECTED_TEMPLATE = {             # IEEE template rules: substring in any finding
    "1.6x line spacing": "not single-spaced",
    "math / footnote in title": "title contains",
    "math in abstract": "abstract contains math",
    "coloured body text": "coloured",
    "'Figure 1' instead of 'Fig. 1'": '"figure" is written out',
    "'Ref. [2]'": "ref. [2]",
    "'.25' without leading zero": "leading zero",
    "text smaller than 6 pt": "smaller than 6 pt",
    "reference without a year": "have no year",
    "'et al.' in the reference list": "et al.",
}


def run(exe, pdf, out, stage="camera-ready"):
    cmd = list(exe) + [pdf, "--json", "--out", out, "--stage", stage]
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

    # real-world eXpress stamp format ("Certified by IEEE PDFExpress at October 28, 2026 16:40:27")
    code, data = run(exe, os.path.join(SAMPLES, "express_certified.pdf"), out)
    errors = [f["message"] for f in data["findings"] if f["severity"] == "error"]
    ok = not any("certified" in m.lower() for m in errors) and any(
        f["severity"] == "pass" and "certified by ieee pdf express" in f["message"].lower()
        for f in data["findings"])
    print(f"  [{'OK ' if ok else 'FAIL'}] accepts a genuine eXpress stamp (date written out)")
    if not ok:
        failures.append("genuine eXpress stamp not accepted: " + "; ".join(errors)[:300])
    code, data = run(exe, os.path.join(SAMPLES, "express_modified.pdf"), out)
    errors = [f["message"] for f in data["findings"] if f["severity"] == "error"]
    ok = any("changed after ieee pdf express certified" in m.lower() for m in errors)
    print(f"  [{'OK ' if ok else 'FAIL'}] detects a PDF edited after eXpress certification")
    if not ok:
        failures.append("PDF edited after certification not detected")

    # double-blind review stage (anonymity)
    code, data = run(exe, os.path.join(SAMPLES, "review_identifying.pdf"), out, "review")
    msgs = [f["message"] for f in data["findings"] if f["severity"] in ("error", "warning")]
    print(f"review_identifying.pdf (review stage): {len(msgs)} error(s)/warning(s)")
    for label, needle in EXPECTED_REVIEW.items():
        ok = any(needle.lower() in m.lower() for m in msgs)
        print(f"  [{'OK ' if ok else 'FAIL'}] detects {label}")
        if not ok:
            failures.append(f"review stage did not detect: {label}")
    code, data = run(exe, os.path.join(SAMPLES, "review_anonymous.pdf"), out, "review")
    errors = [f["message"] for f in data["findings"] if f["severity"] == "error"]
    print(f"review_anonymous.pdf (review stage): {len(errors)} error(s)")
    for m in errors:
        print("  [FAIL] unexpected error:", m[:150])
    if errors:
        failures.append(f"{len(errors)} unexpected error(s) on the anonymous review sample")
    else:
        print("  [OK ] anonymous paper passes the review stage")
    code, data = run(exe, os.path.join(SAMPLES, "review_anonymous.pdf"), out, "camera-ready")
    errors = [f["message"] for f in data["findings"] if f["severity"] == "error"]
    ok = any("must list all authors" in m for m in errors)
    print(f"  [{'OK ' if ok else 'FAIL'}] camera-ready stage requires author names")
    if not ok:
        failures.append("camera-ready stage did not require author names")

    # IEEE template rules
    code, data = run(exe, os.path.join(SAMPLES, "template_rules_broken.pdf"), out)
    msgs = [f["message"].lower() for f in data["findings"]]
    print("template_rules_broken.pdf:")
    for label, needle in EXPECTED_TEMPLATE.items():
        ok = any(needle.lower() in m for m in msgs)
        print(f"  [{'OK ' if ok else 'FAIL'}] detects {label}")
        if not ok:
            failures.append(f"template rule not detected: {label}")

    if failures:
        print("\nFAILED:\n  - " + "\n  - ".join(failures))
        sys.exit(1)
    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
