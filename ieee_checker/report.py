"""HTML report + annotated PDF generation (no internet needed)."""

from __future__ import annotations

import base64
import datetime as _dt
import html
import os

import pymupdf

from .analyzer import ERROR, INFO, PASS, WARNING, Result

SEV_LABEL = {ERROR: "Error", WARNING: "Warning", INFO: "Info", PASS: "OK"}
COLORS = {ERROR: (0.85, 0.1, 0.1), WARNING: (0.95, 0.55, 0.0), INFO: (0.1, 0.45, 0.85)}
MAX_THUMBS = 60


def _thumb(doc, page, rect, dpi=110):
    try:
        pg = doc[page - 1]
        r = pymupdf.Rect(rect)
        r = pymupdf.Rect(r.x0 - 8, r.y0 - 8, r.x1 + 8, r.y1 + 8) & pg.rect
        if r.width < 4 or r.height < 4:
            return None
        scale = min(dpi, 520 * 72 / max(r.width, 1))
        pix = pg.get_pixmap(clip=r, dpi=int(max(40, scale)))
        return base64.b64encode(pix.tobytes("png")).decode()
    except Exception:  # noqa: BLE001
        return None


def write_html(res: Result, out_path: str):
    try:
        doc = pymupdf.open(res.path)
    except Exception:  # noqa: BLE001 - unreadable PDF: report without pictures
        doc = None
    e = html.escape
    errors, warns = res.count(ERROR), res.count(WARNING)
    if errors:
        verdict, vcls = f"{errors} error(s) must be fixed before submission", "bad"
    elif warns:
        verdict, vcls = "No errors - please review the warnings", "warn"
    else:
        verdict, vcls = "Looks ready for IEEE submission", "good"

    thumbs = 0
    rows = []
    for f in res.findings:
        img = ""
        if f.thumb and f.rect and f.page and thumbs < MAX_THUMBS:
            b64 = _thumb(doc, f.page, f.rect)
            if b64:
                thumbs += 1
                img = f'<div class="thumb"><img alt="region" src="data:image/png;base64,{b64}"></div>'
        rows.append(
            f'<tr class="{f.severity}"><td><span class="pill {f.severity}">{SEV_LABEL[f.severity]}'
            f'</span></td><td>{e(f.category)}</td><td class="num">{f.page or ""}</td>'
            f'<td>{e(f.message)}' + (f'<div class="detail">{e(f.detail)}</div>' if f.detail else "")
            + img + "</td></tr>")

    def table(headers, data):
        h = "".join(f"<th>{e(x)}</th>" for x in headers)
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in data)
        return f'<div class="tw"><table class="data"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'

    meas = table(["Item", "Value"], [[e(str(k)), e(str(v))] for k, v in res.measurements.items()])

    def status_cell(s):
        bad_words = ("ERROR", "PASTED", "NOT CITED", "MISSING", "FAIL", "NEVER")
        cls = "bad" if any(s.startswith(b) for b in bad_words) else (
            "warn" if s in ("WARNING", "CHECK") or s.startswith("not found") else "good")
        return f'<span class="st {cls}">{e(s)}</span>'

    from . import spec as _spec
    comp = table(["IEEE PDF eXpress / Xplore rule", "Result", "Found"],
                 [[e(c["rule"]), status_cell("OK" if c["ok"] else (
                     "CHECK" if c["rule"].startswith(("Created by", "Fonts subset", "No hyperlinks"))
                     else "FAIL")), e(str(c["found"]))] for c in res.compliance]) \
        if res.compliance else ""
    n_unc = sum(1 for c in res.citations if c["status"] != "cited")
    cits = table(["Ref.", "Status", "Times cited", "Cited on page(s)", "Reference"],
                 [[f"[{c['ref']}]", status_cell(c["status"]), c["times"], e(c["pages"]),
                   e(c["text"])] for c in res.citations]) \
        if res.citations else "<p class='muted'>No numbered reference list found.</p>"
    def xref_cell(x):
        if x["times"]:
            return status_cell(str(x["times"]))
        if x["item"].startswith("Equation"):
            return "0 <span class='muted'>(optional for equations)</span>"
        return status_cell("NEVER referred to")
    n_refs = sum(1 for c in res.citations if not c["status"].startswith("MISSING"))
    xrefs = table(["Item", "Times referred to in text", "On page(s)"],
                  [[e(x["item"]), xref_cell(x), e(x["pages"])] for x in res.crossrefs]) \
        if res.crossrefs else "<p class='muted'>No figures, tables or numbered equations found.</p>"
    m = _spec.MARGINS.get(res.paper, _spec.CONF_MARGINS)
    profile = (f"Paper {'A4 (210 x 297 mm)' if _spec.REQUIRED_PAPER == 'a4' else _spec.REQUIRED_PAPER} on every page"
               f" &middot; margins top {m['top'] / _spec.MM:.1f} mm, bottom {m['bottom'] / _spec.MM:.1f} mm, "
               f"left/right {m['left'] / _spec.MM:.1f} mm &middot; two columns, "
               f"{_spec.COLUMN_GAP / _spec.MM:.2f} mm gap &middot; "
               f"{_spec.MIN_PAGES or 1}-{_spec.MAX_PAGES or 'any'} pages")

    imgs = table(["Page", "Size on page (in)", "Pixels", "Resolution (dpi)", "Real detail (dpi)",
                  "Type", "Compression", "Status", "Notes"],
                 [[i["page"], e(i["size_in"]), e(i["pixels"]), i["dpi"], i["eff_dpi"], e(i["kind"]),
                   e(i["format"]), status_cell(i["status"]), e(i["notes"])] for i in res.images]) \
        if res.images else "<p class='muted'>No raster images found.</p>"
    tabs = table(["Table", "Page", "Caption", "How it is made"],
                 [[e(t["num"]), t["page"], e(t["caption"]), status_cell(t["status"])]
                  for t in res.tables]) if res.tables else "<p class='muted'>No tables found.</p>"
    figs = table(["Fig.", "Page", "Caption", "Caption position", "Cited in text"],
                 [[f["num"], f["page"], e(f["caption"]), e(f["placement"]), e(f["cited"])]
                  for f in res.figures]) if res.figures else "<p class='muted'>No figure captions found.</p>"
    margins = table(["Page", "Top (in)", "Bottom (in)", "Left (in)", "Right (in)", "Inside IEEE margins"],
                    [[m["page"], f"{m['top']:.2f}", f"{m['bottom']:.2f}", f"{m['left']:.2f}",
                      f"{m['right']:.2f}", status_cell("OK" if m["ok"] else "ERROR")]
                     for m in res.margins])
    fonts = table(["Font", "Share of text", "Type", "Embedded", "Times?"],
                  [[e(f["name"]), f["share"], e(str(f["type"])),
                    status_cell("OK" if f["embedded"] == "yes" else "ERROR"), e(f["times"])]
                   for f in res.fonts])

    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IEEE Format Report</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --fg:#1d232b; --muted:#5f6b7a; --line:#e2e6eb;
  --err:#c62828; --errbg:#fdecea; --warn:#b26a00; --warnbg:#fff4e0; --info:#1f5fae; --infobg:#e8f0fb;
  --ok:#2e7d32; --okbg:#e8f5e9; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171c; --card:#1d2128; --fg:#e7eaee;
  --muted:#9aa5b1; --line:#2c323b; --errbg:#3a1d1d; --warnbg:#3a2c12; --infobg:#18283d; --okbg:#173022;
  --err:#ff8a80; --warn:#ffb74d; --info:#90caf9; --ok:#81c784; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif }}
.wrap {{ max-width:1100px; margin:0 auto; padding:24px 16px 60px }}
h1 {{ font-size:24px; margin:0 0 4px }} h2 {{ font-size:18px; margin:32px 0 10px }}
.muted {{ color:var(--muted) }}
.verdict {{ border-radius:10px; padding:16px 18px; margin:18px 0; font-weight:600; font-size:17px }}
.verdict.bad {{ background:var(--errbg); color:var(--err) }} .verdict.warn {{ background:var(--warnbg); color:var(--warn) }}
.verdict.good {{ background:var(--okbg); color:var(--ok) }}
.counts {{ display:flex; gap:10px; flex-wrap:wrap }}
.count {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 16px; min-width:110px }}
.count b {{ display:block; font-size:24px }}
.tw {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px }}
table {{ border-collapse:collapse; width:100% }}
th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top }}
th {{ font-size:13px; color:var(--muted); font-weight:600 }}
td.num {{ text-align:right; white-space:nowrap }}
.pill {{ display:inline-block; font-size:12px; font-weight:700; padding:2px 8px; border-radius:999px; white-space:nowrap }}
.pill.error {{ background:var(--errbg); color:var(--err) }} .pill.warning {{ background:var(--warnbg); color:var(--warn) }}
.pill.info {{ background:var(--infobg); color:var(--info) }} .pill.pass {{ background:var(--okbg); color:var(--ok) }}
.st.bad {{ color:var(--err); font-weight:700 }} .st.warn {{ color:var(--warn); font-weight:700 }} .st.good {{ color:var(--ok) }}
.detail {{ color:var(--muted); font-size:13px; margin-top:3px }}
.thumb img {{ max-width:100%; max-height:260px; margin-top:8px; border:2px solid var(--line); border-radius:6px; background:#fff }}
.filters {{ margin:8px 0 }} .filters label {{ margin-right:14px; font-size:14px }}
</style></head><body><div class="wrap">
<h1>IEEE Conference Paper Format Report</h1>
<div class="muted">{e(os.path.basename(res.path))} &middot; checked {now} &middot; offline check</div>
<div class="muted" style="margin-top:6px">Rules checked: {profile}</div>
<div class="verdict {vcls}">{e(verdict)}</div>
<div class="counts">
 <div class="count"><b style="color:var(--err)">{errors}</b>Errors</div>
 <div class="count"><b style="color:var(--warn)">{warns}</b>Warnings</div>
 <div class="count"><b style="color:var(--info)">{res.count(INFO)}</b>Info</div>
 <div class="count"><b style="color:var(--ok)">{res.count(PASS)}</b>Passed checks</div>
</div>
<h2>Findings</h2>
<div class="filters">
 <label><input type="checkbox" data-s="error" checked> Errors</label>
 <label><input type="checkbox" data-s="warning" checked> Warnings</label>
 <label><input type="checkbox" data-s="info" checked> Info</label>
 <label><input type="checkbox" data-s="pass"> Passed</label>
</div>
<div class="tw"><table id="f"><thead><tr><th>Severity</th><th>Category</th><th>Page</th><th>Finding</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
<h2>Citations: every reference must be cited</h2>
<p class="muted">{n_refs} reference(s) in the list; {n_unc} problem(s). Every entry in the reference list must be cited in the text as [n], and every [n] in the text must exist in the list.</p>
{cits}
<h2>In-text references to figures, tables and equations</h2>{xrefs}
<h2>IEEE PDF eXpress / Xplore file rules</h2>{comp}
<h2>Tables: drawn or pasted as image?</h2>{tabs}
<h2>Image quality</h2>
<p class="muted">IEEE guideline: photos / colour / greyscale images at least 300 dpi, line art (diagrams, charts, text) at least 600 dpi at printed size. Vector figures (PDF/EPS/SVG) are always sharp and are not listed. "Real detail" lower than "Resolution" means the picture was upscaled or is blurry.</p>
{imgs}
<h2>Figures</h2>{figs}
<h2>Measured margins</h2>{margins}
<h2>Fonts</h2>{fonts}
<h2>Summary of measurements</h2>{meas}
<p class="muted" style="margin-top:30px">Automatic checks cannot replace reading the conference's own author kit. Always also run your final PDF through IEEE PDF eXpress if your conference requires it.</p>
</div>
<script>
function apply(){{document.querySelectorAll('.filters input').forEach(function(cb){{
 document.querySelectorAll('#f tr.'+cb.dataset.s).forEach(function(r){{r.style.display=cb.checked?'':'none';}});}});}}
document.querySelectorAll('.filters input').forEach(function(cb){{cb.addEventListener('change',apply);}});apply();
</script></body></html>"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(page)
    if doc is not None:
        doc.close()
    return out_path


def write_annotated_pdf(res: Result, out_path: str, paper: str = "letter"):
    """Detailed annotated copy - see annotate.py."""
    from .annotate import write_annotated_pdf as _write
    return _write(res, out_path, paper)
