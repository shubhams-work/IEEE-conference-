"""Detailed annotated copy of the paper.

* Summary pages in front: verdict, rules, numbered list of every problem with
  page and how to fix it, citation table, PDF eXpress checklist, margins, images.
* Every paper page is widened with a NOTES PANEL on the right. Each problem is
  pinpointed on the page (highlighted words or a coloured frame) and connected by
  a thin line to its numbered note in the panel ("#4 ERROR ..."), so the paper
  text itself stays readable. Numbers match the list on the summary pages.
* The panel also shows required vs measured margins of that page, the dpi of
  every image and whether every table is a real table or a pasted picture.
* Clicking a frame/highlight shows the full explanation (PDF comment).
* Page labels keep the viewer's page numbers equal to the paper's page numbers.
"""

from __future__ import annotations

import datetime as _dt
import html
import io
import os

import pymupdf

from . import spec
from .analyzer import ERROR, INFO, PASS, WARNING, Result

COL = {ERROR: (0.80, 0.08, 0.08), WARNING: (0.82, 0.42, 0.0), INFO: (0.10, 0.40, 0.80),
       "ok": (0.08, 0.50, 0.18), "guide": (0.25, 0.50, 0.90)}
FILL = {ERROR: (1.0, 0.92, 0.92), WARNING: (1.0, 0.95, 0.85), INFO: (0.91, 0.95, 1.0),
        "ok": (0.90, 0.97, 0.91), "guide": (0.93, 0.96, 1.0)}
HIGHLIGHT = {ERROR: (1.0, 0.55, 0.55), WARNING: (1.0, 0.80, 0.35), INFO: (0.60, 0.80, 1.0)}
WORD = {ERROR: "ERROR", WARNING: "WARNING", INFO: "INFO", "ok": "OK", "guide": ""}
TITLE = "IEEE checker"
PANEL_W = 250.0               # width added to every page for the notes
FS_T, FS_B = 7.0, 6.6         # title / body font size in the panel
LINE = 1.22                   # line height factor


_ASCII = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'",
                        "’": "'", "–": "-", "—": "-", "…": "...",
                        "×": "x", "−": "-", " ": " ", "•": "*",
                        "≥": ">=", "≤": "<=", "→": "->"})


def _latin(text):
    """The built-in PDF fonts only cover Latin-1: convert typographic characters."""
    return text.translate(_ASCII).encode("latin-1", "replace").decode("latin-1")


def _wrap(text, width, size, font="helv"):
    """Greedy word wrap using real font metrics."""
    text = _latin(text)
    words, lines, cur = " ".join(text.split()).split(" "), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if pymupdf.get_text_length(trial, fontname=font, fontsize=size) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            while pymupdf.get_text_length(w, fontname=font, fontsize=size) > width:
                cut = max(1, int(len(w) * width / pymupdf.get_text_length(w, fontname=font,
                                                                         fontsize=size)) - 1)
                lines.append(w[:cut])
                w = w[cut:]
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


# --------------------------------------------------------------- notes panel
class Panel:
    """Notes column on the right of one widened page."""

    def __init__(self, page, w0):
        self.page, self.w0 = page, w0
        self.x0 = w0 + 12
        self.width = PANEL_W - 20
        self.header = []          # (kind, text)
        self.items = []           # dicts

    def note(self, kind, title, body="", detail="", anchor=None):
        self.items.append({"kind": kind, "title": title, "body": body, "detail": detail,
                           "anchor": pymupdf.Rect(anchor) if anchor is not None else None})

    def _layout_item(self, it, with_detail):
        tw = self.width - 8
        t = _wrap(it["title"], tw, FS_T, "hebo")
        b = _wrap(it["body"], tw, FS_B) if it["body"] else []
        d = _wrap(it["detail"], tw, FS_B - 0.4) if (with_detail and it["detail"]) else []
        if len(d) > 4:
            d = d[:4]
            d[-1] = d[-1][:-3] + "..."
        h = (len(t) * FS_T + len(b) * FS_B + len(d) * (FS_B - 0.4)) * LINE + 6
        it.update(t_lines=t, b_lines=b, d_lines=d, h=h)

    def render(self):
        page, H = self.page, self.page.rect.height
        page.draw_rect(pymupdf.Rect(self.w0, 0, self.w0 + PANEL_W, H), color=None,
                       fill=(0.965, 0.97, 0.98), overlay=True)
        page.draw_line((self.w0 + 0.5, 0), (self.w0 + 0.5, H), color=(0.75, 0.78, 0.83), width=0.6)
        # header
        y = 14
        page.insert_text((self.x0, y), "IEEE checker notes", fontname="hebo", fontsize=8.5,
                         color=(0.12, 0.24, 0.42))
        y += 4
        for kind, text in self.header:
            for ln in _wrap(text, self.width, FS_B):
                y += FS_B * LINE
                page.insert_text((self.x0, y), ln, fontname="helv", fontsize=FS_B, color=COL[kind])
        y += 6
        top = y
        bottom = H - 6
        avail = bottom - top
        # try with detail, then without, then title + 1 body line
        for mode in ("full", "nodetail", "compact"):
            for it in self.items:
                self._layout_item(it, mode == "full")
                if mode == "compact":
                    it["b_lines"] = it["b_lines"][:1]
                    it["h"] = (len(it["t_lines"]) * FS_T + len(it["b_lines"]) * FS_B) * LINE + 6
            gap = 3 if mode != "compact" else 1.5
            if sum(it["h"] + gap for it in self.items) <= avail:
                break
        # desired positions: next to the anchor
        for it in self.items:
            a = it["anchor"]
            it["want"] = (a.y0 + a.y1) / 2 - it["h"] / 2 if a is not None else top
        self.items.sort(key=lambda it: it["want"])
        yy = top
        for it in self.items:
            it["y"] = max(it["want"], yy)
            yy = it["y"] + it["h"] + gap
        limit = bottom
        for it in reversed(self.items):          # push back up if we ran off the page
            if it["y"] + it["h"] > limit:
                it["y"] = max(top, limit - it["h"])
            limit = it["y"] - gap
        for it in self.items:
            self._draw_item(it)

    def _draw_item(self, it):
        page, kind = self.page, it["kind"]
        box = pymupdf.Rect(self.x0, it["y"], self.x0 + self.width, it["y"] + it["h"])
        if box.y1 > page.rect.height:
            return
        page.draw_rect(box, color=COL[kind], fill=FILL[kind], width=0.6, overlay=True)
        y = box.y0 + 2
        for ln in it["t_lines"]:
            y += FS_T * LINE - 1
            page.insert_text((box.x0 + 4, y), ln, fontname="hebo", fontsize=FS_T, color=COL[kind])
        for ln in it["b_lines"]:
            y += FS_B * LINE
            page.insert_text((box.x0 + 4, y), ln, fontname="helv", fontsize=FS_B,
                             color=(0.13, 0.15, 0.18))
        for ln in it["d_lines"]:
            y += (FS_B - 0.4) * LINE
            page.insert_text((box.x0 + 4, y), ln, fontname="helv", fontsize=FS_B - 0.4,
                             color=(0.38, 0.42, 0.48))
        a = it["anchor"]
        if a is not None:                          # connector: anchor -> page edge -> note
            ay = (a.y0 + a.y1) / 2
            ny = (box.y0 + box.y1) / 2
            pts = [(a.x1 + 1, ay), (self.w0 + 2, ay), (self.x0 - 3, ny), (self.x0, ny)]
            page.draw_polyline(pts, color=COL[kind], width=0.55, overlay=True)
            page.draw_circle((a.x1 + 1, ay), 1.3, color=COL[kind], fill=COL[kind])


def _mark(page, rect, kind, note):
    """Highlight small text, frame larger areas (as clickable PDF comments)."""
    rr = pymupdf.Rect(rect) & page.rect
    if rr.is_empty or rr.width < 0.5:
        return None
    if rr.height <= 16 and kind in HIGHLIGHT:
        a = page.add_highlight_annot(rr)
        a.set_colors(stroke=HIGHLIGHT[kind])
        a.set_info(title=TITLE, content=note)
        a.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
        a.update(opacity=0.55)
        frame = pymupdf.Rect(rr.x0 - 1, rr.y0 - 1, rr.x1 + 1, rr.y1 + 1)
    else:
        frame = pymupdf.Rect(rr.x0 - 2, rr.y0 - 2, rr.x1 + 2, rr.y1 + 2) & page.rect
    b = page.add_rect_annot(frame)
    b.set_colors(stroke=COL[kind])
    b.set_border(width=1.3)
    b.set_info(title=TITLE, content=note)
    b.set_flags(pymupdf.PDF_ANNOT_IS_PRINT)
    b.update()
    return frame


def _guides(page, w0, paper):
    m = spec.MARGINS.get(paper, spec.CONF_MARGINS)
    H = page.rect.height
    area = pymupdf.Rect(m["left"], m["top"], w0 - m["right"], H - m["bottom"])
    a = page.add_rect_annot(area)
    a.set_colors(stroke=COL["guide"])
    a.set_border(width=0.5, dashes=[3, 3])
    a.set_info(title=TITLE, content="Required text area (inside the margins)")
    a.update(opacity=0.7)
    cx = w0 / 2
    for x in (cx - spec.COLUMN_GAP / 2, cx + spec.COLUMN_GAP / 2):
        ln = page.add_line_annot(pymupdf.Point(x, area.y0), pymupdf.Point(x, area.y1))
        ln.set_colors(stroke=COL["guide"])
        ln.set_border(width=0.3, dashes=[1, 3])
        ln.set_info(title=TITLE, content=f"Required column gap {spec.COLUMN_GAP / spec.MM:.2f} mm")
        ln.update(opacity=0.5)


def _short(text, n=200):
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 3] + "..."


# --------------------------------------------------------------- summary pages
CSS = """
* { font-family: sans-serif; }
body { font-size: 8.5pt; color: #1d232b; }
h1 { font-size: 15pt; margin: 0 0 4pt 0; }
h2 { font-size: 11pt; margin: 12pt 0 4pt 0; color: #1f3d6b; }
p { margin: 2pt 0; }
.muted { color: #5f6b7a; }
.verdict { font-size: 11pt; font-weight: bold; padding: 4pt; }
.bad { color: #b71c1c; } .warn { color: #a85d00; } .good { color: #1b6e2a; } .info { color: #1f5fae; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; background-color: #e8edf4; font-size: 7.5pt; padding: 2pt; }
td { border-bottom: 0.5pt solid #d5dbe3; padding: 2pt; font-size: 7.5pt; vertical-align: top; }
"""


def _summary_html(res, n_paper_pages):
    e = html.escape
    errors, warns = res.count(ERROR), res.count(WARNING)
    if errors:
        verdict, vc = f"{errors} error(s) must be fixed before submission", "bad"
    elif warns:
        verdict, vc = "No errors - please review the warnings", "warn"
    else:
        verdict, vc = "Looks ready for submission", "good"
    m = spec.MARGINS.get(res.paper, spec.CONF_MARGINS)
    mm = spec.MM
    rules = (f"Paper {'A4' if spec.REQUIRED_PAPER == 'a4' else spec.REQUIRED_PAPER} on every page; "
             f"margins top {m['top'] / mm:.1f} mm, bottom {m['bottom'] / mm:.1f} mm, left/right "
             f"{m['left'] / mm:.1f} mm; two columns with {spec.COLUMN_GAP / mm:.2f} mm gap; "
             f"{spec.MIN_PAGES or 1}-{spec.MAX_PAGES or 'any'} pages; every reference cited; "
             f"IEEE PDF eXpress / Xplore file rules.")
    out = [f"<h1>IEEE format check - annotated copy</h1>",
           f"<p class='muted'>{e(os.path.basename(res.path))} - checked "
           f"{_dt.datetime.now():%Y-%m-%d %H:%M} - {n_paper_pages} page(s)</p>",
           f"<p class='muted'>Rules: {e(rules)}</p>",
           f"<p class='verdict {vc}'>{e(verdict)}</p>",
           f"<p><b class='bad'>{errors} errors</b> &nbsp; <b class='warn'>{warns} warnings</b> "
           f"&nbsp; <b class='info'>{res.count(INFO)} info</b> &nbsp; "
           f"<b class='good'>{res.count(PASS)} checks passed</b></p>",
           "<h2>How to read this file</h2>",
           "<p>The paper follows these summary pages; the PDF page numbers of the paper pages "
           "match the paper's own page numbers. Each paper page has a <b>notes panel on the "
           "right</b>. Every problem is <b>numbered (#1, #2, ...)</b>: the exact place is "
           "highlighted or framed on the page and a thin line connects it to its note. "
           "<span class='bad'>Red = error (must fix)</span>, <span class='warn'>orange = warning "
           "(check)</span>, <span class='info'>blue = info</span>, <span class='good'>green = "
           "OK</span>. The dashed blue frame is the required text area; the dotted lines mark "
           "the required column gap. Click a highlight or frame for the full explanation.</p>"]
    probs = [f for f in res.findings if f.severity != PASS]
    out.append(f"<h2>Problems found ({len(probs)})</h2>")
    if probs:
        rows = []
        for f in probs:
            sev = {ERROR: "bad", WARNING: "warn", INFO: "info"}[f.severity]
            where = f"p. {f.page}" if f.page else "whole file"
            if f.extra:
                pages = sorted({f.page} | {p for p, _ in f.extra})
                where = "p. " + ", ".join(map(str, pages))
            rows.append(f"<tr><td><b>#{f._num}</b></td><td class='{sev}'><b>"
                        f"{WORD[f.severity]}</b></td><td>{e(where)}</td><td>{e(f.category)}</td>"
                        f"<td>{e(f.message)}" + (f"<br/><span class='muted'>{e(f.detail)}</span>"
                                                  if f.detail else "") + "</td></tr>")
        out.append("<table><tr><th>#</th><th>Severity</th><th>Where</th><th>Area</th>"
                   "<th>Problem / how to fix</th></tr>" + "".join(rows) + "</table>")
    else:
        out.append("<p class='good'>No problems found.</p>")
    passed = [f for f in res.findings if f.severity == PASS]
    if passed:
        out.append("<h2>Checks passed</h2><p class='good'>" +
                   "<br/>".join(e(f"OK - {f.category}: {f.message}") for f in passed) + "</p>")
    if res.citations:
        rows = []
        for c in res.citations:
            cls = "good" if c["status"] == "cited" else "bad"
            rows.append(f"<tr><td>[{c['ref']}]</td><td class='{cls}'><b>{e(c['status'])}</b></td>"
                        f"<td>{c['times']}</td><td>{e(c['pages'])}</td><td>{e(c['text'])}</td></tr>")
        out.append("<h2>Citations (every reference must be cited)</h2><table><tr><th>Ref.</th>"
                   "<th>Status</th><th>Times cited</th><th>Cited on page(s)</th><th>Reference</th>"
                   "</tr>" + "".join(rows) + "</table>")
    if res.crossrefs:
        rows = []
        for x in res.crossrefs:
            eq = x["item"].startswith("Equation")
            cls = "good" if x["times"] else ("muted" if eq else "bad")
            txt = str(x["times"]) if x["times"] else ("0 (optional)" if eq else "NEVER mentioned")
            rows.append(f"<tr><td>{e(x['item'])}</td><td class='{cls}'><b>{e(txt)}</b></td>"
                        f"<td>{e(x['pages'])}</td></tr>")
        out.append("<h2>In-text references to figures, tables and equations</h2><table><tr>"
                   "<th>Item</th><th>Times mentioned in text</th><th>On page(s)</th></tr>"
                   + "".join(rows) + "</table>")
    if res.compliance:
        rows = []
        for c in res.compliance:
            cls = "good" if c["ok"] else ("warn" if c["rule"].startswith(
                ("Fonts subset", "No hyperlinks")) else "bad")
            rows.append(f"<tr><td>{e(c['rule'])}</td><td class='{cls}'><b>"
                        f"{'OK' if c['ok'] else 'CHECK' if cls == 'warn' else 'FAIL'}</b></td>"
                        f"<td>{e(str(c['found']))}</td></tr>")
        out.append("<h2>IEEE PDF eXpress / Xplore file rules</h2><table><tr><th>Rule</th>"
                   "<th>Result</th><th>Found</th></tr>" + "".join(rows) + "</table>")
    if res.margins:
        rows = "".join(
            f"<tr><td>{x['page']}</td><td>{x['top'] * 25.4:.1f}</td><td>{x['bottom'] * 25.4:.1f}</td>"
            f"<td>{x['left'] * 25.4:.1f}</td><td>{x['right'] * 25.4:.1f}</td>"
            f"<td class='{'good' if x['ok'] else 'bad'}'><b>{'OK' if x['ok'] else 'OUTSIDE'}</b></td></tr>"
            for x in res.margins)
        out.append(f"<h2>Measured margins (mm) - required: top {m['top'] / mm:.1f}, bottom "
                   f"{m['bottom'] / mm:.1f}, left {m['left'] / mm:.1f}, right {m['right'] / mm:.1f}</h2>"
                   "<table><tr><th>Page</th><th>Top</th><th>Bottom</th><th>Left</th><th>Right</th>"
                   "<th>Result</th></tr>" + rows + "</table>")
    if res.images:
        rows = "".join(
            f"<tr><td>{i['page']}</td><td>{e(i['size_in'])} in</td><td>{e(i['pixels'])}</td>"
            f"<td>{i['dpi']}</td><td>{i['eff_dpi']}</td><td>{e(i['kind'])}</td>"
            f"<td class='{'good' if i['status'] == 'OK' else 'bad' if i['status'] == 'ERROR' else 'warn'}'>"
            f"<b>{e(i['status'])}</b></td><td>{e(i['notes'])}</td></tr>" for i in res.images)
        out.append("<h2>Images (photos need 300 dpi, diagrams 600 dpi)</h2><table><tr><th>Page</th>"
                   "<th>Size</th><th>Pixels</th><th>dpi</th><th>Real detail</th><th>Type</th>"
                   "<th>Status</th><th>Notes</th></tr>" + rows + "</table>")
    if res.tables:
        rows = "".join(
            f"<tr><td>TABLE {e(str(t['num']))}</td><td>{t['page']}</td>"
            f"<td class='{'good' if t['status'].startswith('real') else 'bad'}'><b>{e(t['status'])}</b></td></tr>"
            for t in res.tables)
        out.append("<h2>Tables (must be real tables, not pictures)</h2><table><tr><th>Table</th>"
                   "<th>Page</th><th>How it is made</th></tr>" + rows + "</table>")
    return "<body>" + "".join(out) + "</body>"


def _summary_pdf(res, page_rect, n_paper_pages):
    story = pymupdf.Story(html=_summary_html(res, n_paper_pages), user_css=CSS)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    where = page_rect + (40, 40, -40, -40)
    more = 1
    while more:
        dev = writer.begin_page(page_rect)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return pymupdf.open("pdf", buf.getvalue())


# ------------------------------------------------------------------- main
def write_annotated_pdf(res: Result, out_path: str, paper: str = "letter"):
    doc = pymupdf.open(res.path)
    n = doc.page_count
    widths = [p.rect.width for p in doc]
    first_rect = pymupdf.Rect(doc[0].rect)

    # widen every page for the notes panel
    panels = []
    for page in doc:
        r = page.rect
        page.set_mediabox(pymupdf.Rect(0, 0, r.width + PANEL_W, r.height))
        panels.append(Panel(page, r.width))
        _guides(page, r.width, paper)

    # number problems (same order as the summary list)
    probs = [f for f in res.findings if f.severity != PASS]
    for i, f in enumerate(probs, 1):
        f._num = i
    for f in res.findings:
        if f.severity == PASS:
            f._num = 0

    # header of every panel: required vs measured margins
    m = spec.MARGINS.get(paper, spec.CONF_MARGINS)
    mm = spec.MM
    meas = {x["page"]: x for x in res.margins}
    for i, pn in enumerate(panels):
        w, h = widths[i], doc[i].rect.height
        pn.header.append(("guide", f"Page {i + 1} - size {w / mm:.0f} x {h / mm:.0f} mm"))
        pn.header.append(("guide", f"Required margins (mm): top {m['top'] / mm:.1f}, bottom "
                                   f"{m['bottom'] / mm:.1f}, left {m['left'] / mm:.1f}, right "
                                   f"{m['right'] / mm:.1f}"))
        x = meas.get(i + 1)
        if x:
            pn.header.append(("ok" if x["ok"] else ERROR,
                              f"Measured (mm): top {x['top'] * 25.4:.1f}, bottom "
                              f"{x['bottom'] * 25.4:.1f}, left {x['left'] * 25.4:.1f}, right "
                              f"{x['right'] * 25.4:.1f} - " + ("OK" if x["ok"] else "OUTSIDE MARGINS")))

    # problems
    for f in probs:
        note = f"#{f._num} {WORD[f.severity]} - {f.category}: {f.message}" + \
               (f"\n\n{f.detail}" if f.detail else "")
        title = f"#{f._num} {WORD[f.severity]} - {f.category}"
        if f.page and f.rect:
            places = [(f.page, f.rect)] + list(f.extra)
            for k, (pg, rect) in enumerate(places):
                if not pg or pg > n:
                    continue
                fr = _mark(doc[pg - 1], rect, f.severity, note)
                if fr is None:
                    continue
                if k == 0:
                    panels[pg - 1].note(f.severity, title, _short(f.message), f.detail, fr)
                else:
                    panels[pg - 1].note(f.severity, f"#{f._num} {WORD[f.severity]} (same problem)",
                                        anchor=fr)
        elif f.page and f.page <= n:
            panels[f.page - 1].note(f.severity, title, _short(f.message), f.detail)

    # images and tables
    for im in res.images:
        st = im["status"]
        kind = "ok" if st == "OK" else (ERROR if st == "ERROR" else WARNING)
        body = f"{im['dpi']} dpi at printed size ({im['size_in']} in, {im['pixels']} px)"
        if im["eff_dpi"] < im["dpi"]:
            body += f"; real detail only ~{im['eff_dpi']} dpi"
        body += f"; {im['kind']}, {im['format']}."
        if st == "OK":
            panels[im["page"] - 1].note("ok", "Image - OK", body,
                                        anchor=pymupdf.Rect(im["rect"]))
    for t in res.tables:
        if t.get("rect") and t["status"].startswith("real"):
            panels[t["page"] - 1].note("ok", f"TABLE {t['num']} - OK", t["status"],
                                       anchor=pymupdf.Rect(t["rect"]))

    for pn in panels:
        pn.render()

    # summary pages in front, page labels so paper pages keep their numbers
    summary = _summary_pdf(res, first_rect, n)
    k = summary.page_count
    doc.insert_pdf(summary, start_at=0)
    try:
        doc.set_page_labels([{"startpage": 0, "prefix": "Summary-", "style": "D", "firstpagenum": 1},
                             {"startpage": k, "prefix": "", "style": "D", "firstpagenum": 1}])
    except Exception:  # noqa: BLE001
        pass
    doc.save(out_path, garbage=3, deflate=True)
    doc.close()
    return out_path
