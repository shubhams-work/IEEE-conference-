"""Core analysis of an IEEE conference paper PDF (fully offline)."""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import pymupdf

from . import imagecheck, spec

ERROR, WARNING, INFO, PASS = "error", "warning", "info", "pass"
SEV_ORDER = {ERROR: 0, WARNING: 1, INFO: 2, PASS: 3}


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    page: int | None = None            # 1-based
    detail: str = ""
    rect: tuple | None = None          # (x0, y0, x1, y1) in page coords
    thumb: bool = False                # include a picture of the region in report
    extra: list = field(default_factory=list)   # more (page, rect) places, for annotations


@dataclass
class Line:
    page: int                          # 0-based
    block: int
    text: str
    bbox: pymupdf.Rect
    size: float
    font: str
    bold: bool
    horizontal: bool
    first_in_block: bool


@dataclass
class Result:
    path: str
    findings: list = field(default_factory=list)
    measurements: dict = field(default_factory=dict)
    images: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    figures: list = field(default_factory=list)
    margins: list = field(default_factory=list)
    fonts: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    crossrefs: list = field(default_factory=list)
    compliance: list = field(default_factory=list)
    paper: str = "letter"

    def count(self, sev):
        return sum(1 for f in self.findings if f.severity == sev)


ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(s: str) -> int | None:
    s = s.upper()
    if not s or any(c not in ROMAN for c in s):
        return None
    total = 0
    for i, c in enumerate(s):
        v = ROMAN[c]
        if i + 1 < len(s) and ROMAN[s[i + 1]] > v:
            total -= v
        else:
            total += v
    return total


def clean_font(name: str) -> str:
    return name.split("+", 1)[-1] if "+" in name[:8] else name


def is_times(font: str) -> bool:
    f = font.lower().replace("-", "").replace(" ", "")
    return any(p.replace(" ", "") in f for p in spec.TIMES_FONT_PATTERNS)


def is_math(font: str) -> bool:
    f = font.lower().replace("-", "")
    return any(p.replace(" ", "") in f.replace(" ", "") for p in spec.MATH_FONT_PATTERNS)


def fmt_in(pt: float) -> str:
    return f"{pt / 72:.2f} in ({pt / spec.MM:.1f} mm)"


def rect_t(r) -> tuple:
    return (float(r[0]), float(r[1]), float(r[2]), float(r[3]))


FIG_RE = re.compile(r"^\s*(Fig\.?|Figure|FIGURE|FIG\.?)\s*(\d+)\s*([.:\-–—|])")
TAB_RE = re.compile(r"^\s*(TABLE|Table)\s+([IVXLC]+|\d+)\b\s*([.:\-–—]?)(.*)$")
ROMAN_HEAD_RE = re.compile(r"^\s*([IVXL]+)\.\s+(\S.{1,70})$")
ARABIC_HEAD_RE = re.compile(r"^\s*(\d{1,2})\.?\s+([A-Z][A-Za-z ,&:\-]{2,60})$")
COMMON_HEADINGS = ("introduction", "related work", "background", "methodology", "method",
                   "methods", "proposed", "results", "experiments", "experimental",
                   "discussion", "conclusion", "conclusions", "literature", "evaluation",
                   "system", "future work", "materials")


class Analyzer:
    def __init__(self, path: str, paper: str | None = None, max_pages: int | None = -1,
                 progress=None, min_pages: int | None = -1):
        self.path = path
        self.paper_pref = spec.REQUIRED_PAPER if paper is None else paper
        # -1 = use the conference profile in spec.py; None/0 = no limit
        self.max_pages = spec.MAX_PAGES if max_pages == -1 else (max_pages or None)
        self.min_pages = spec.MIN_PAGES if min_pages == -1 else (min_pages or None)
        self.progress = progress or (lambda frac, msg: None)
        self.res = Result(path=path)

    # ------------------------------------------------------------------ utils
    def add(self, *a, **k):
        self.res.findings.append(Finding(*a, **k))

    # -------------------------------------------------------------------- run
    def run(self) -> Result:
        self.progress(0.02, "Opening PDF")
        try:
            doc = pymupdf.open(self.path)
        except Exception as e:  # noqa: BLE001
            self.add(ERROR, "File", f"Cannot open PDF: {e}")
            return self.res
        self.doc = doc
        if doc.needs_pass:
            self.add(ERROR, "File", "PDF is password protected. IEEE PDF eXpress / "
                     "Xplore require PDFs without passwords or security.")
            return self.res
        if doc.page_count == 0:
            self.add(ERROR, "File", "PDF has no pages.")
            return self.res

        self.res.measurements["File"] = os.path.basename(self.path)
        self.res.measurements["Pages"] = doc.page_count
        self.res.measurements["PDF producer"] = (doc.metadata.get("producer") or "-")[:80]

        self.progress(0.06, "Extracting text")
        self._extract()
        steps = [
            ("Checking paper size", self.check_paper_size),
            ("Checking page count", self.check_page_count),
            ("Checking fonts", self.check_fonts),
            ("Checking font sizes", self.check_font_sizes),
            ("Checking column layout", self.check_columns),
            ("Checking margins", self.check_margins),
            ("Checking title & abstract", self.check_front_matter),
            ("Checking section headings", self.check_headings),
            ("Checking figures & tables", self.check_captions),
            ("Checking tables (drawn vs pasted image)", self.check_tables),
            ("Checking image quality", self.check_images),
            ("Checking references & citations", self.check_references),
            ("Checking leftover template text", self.check_leftovers),
            ("Checking PDF eXpress / IEEE Xplore rules", self.check_xplore),
            ("Checking misc. items", self.check_misc),
        ]
        for i, (msg, fn) in enumerate(steps):
            self.progress(0.1 + 0.85 * i / len(steps), msg)
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - never crash the whole report
                self.add(INFO, "Internal", f"Check '{msg}' could not run: {e}")
        self.res.findings.sort(key=lambda f: (SEV_ORDER[f.severity], f.page or 0))
        self.progress(1.0, "Done")
        return self.res

    # -------------------------------------------------------------- extraction
    def _extract(self):
        flags = (pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
                 & ~pymupdf.TEXT_PRESERVE_LIGATURES)
        self.lines: list[Line] = []
        self.spans: list[list] = []        # per page: (rect, text, size, font)
        self.page_rects = []
        self.drawings = []                 # per page: list of Rect
        self.page_images = []              # per page: get_image_info list
        for pno, page in enumerate(self.doc):
            self.page_rects.append(page.rect)
            d = page.get_text("dict", flags=flags)
            pspans = []
            for bno, b in enumerate(d["blocks"]):
                if b.get("type") != 0:
                    continue
                for li, ln in enumerate(b["lines"]):
                    spans = [s for s in ln["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    text = "".join(s["text"] for s in ln["spans"]).strip()
                    weights = Counter()
                    fonts = Counter()
                    bold_chars = 0
                    for s in spans:
                        n = len(s["text"].strip())
                        weights[round(s["size"] * 2) / 2] += n
                        fonts[clean_font(s["font"])] += n
                        if s["flags"] & 16 or "bold" in s["font"].lower():
                            bold_chars += n
                        pspans.append((pymupdf.Rect(s["bbox"]), s["text"], s["size"],
                                       clean_font(s["font"])))
                    total = sum(weights.values())
                    dirx, diry = ln.get("dir", (1, 0))
                    self.lines.append(Line(
                        page=pno, block=bno, text=text, bbox=pymupdf.Rect(ln["bbox"]),
                        size=weights.most_common(1)[0][0], font=fonts.most_common(1)[0][0],
                        bold=bold_chars > 0.6 * total,
                        horizontal=abs(dirx - 1) < 0.01 and abs(diry) < 0.01,
                        first_in_block=(li == 0)))
            self.spans.append(pspans)
            drs = []
            try:
                for dr in page.get_drawings():
                    r = pymupdf.Rect(dr["rect"])
                    if r.is_empty and r.width < 0.1 and r.height < 0.1:
                        continue
                    fill, stroke = dr.get("fill"), dr.get("color")
                    white_fill = fill is None or all(c > 0.97 for c in fill)
                    if white_fill and stroke is None:
                        continue                      # invisible / white box
                    if r.get_area() > 0.85 * page.rect.get_area():
                        continue                      # page background
                    drs.append(r)
            except Exception:  # noqa: BLE001
                pass
            self.drawings.append(drs)
            try:
                self.page_images.append(page.get_image_info(xrefs=True))
            except Exception:  # noqa: BLE001
                self.page_images.append([])

        sizes = Counter()
        for ln in self.lines:
            if ln.horizontal and len(ln.text) >= 20:
                sizes[ln.size] += len(ln.text)
        self.body_size = sizes.most_common(1)[0][0] if sizes else spec.BODY_SIZE
        self.body_lines = [ln for ln in self.lines if ln.horizontal and len(ln.text) >= 25
                           and abs(ln.size - self.body_size) <= 0.6]

    # --------------------------------------------------------------- paper size
    @staticmethod
    def _size_name(r):
        for name, (pw, ph) in spec.PAPER_SIZES.items():
            if abs(r.width - pw) <= spec.PAPER_SIZE_TOL and abs(r.height - ph) <= spec.PAPER_SIZE_TOL:
                return name
        return None

    def check_paper_size(self):
        label = {"a4": "A4 (210 x 297 mm)", "letter": "US Letter (8.5 x 11 in)"}
        names = [self._size_name(r) for r in self.page_rects]
        r0 = self.page_rects[0]
        detected = names[0]
        if self.paper_pref in spec.PAPER_SIZES:
            self.paper = self.paper_pref
            wrong = [i + 1 for i, n in enumerate(names) if n != self.paper]
            if wrong:
                sizes = sorted({f"{self.page_rects[i - 1].width / spec.MM:.0f} x "
                                f"{self.page_rects[i - 1].height / spec.MM:.0f} mm" for i in wrong})
                every = len(wrong) == len(names)
                self.add(ERROR, "Page setup",
                         ("The paper is not " if every else f"{len(wrong)} page(s) are not ")
                         + f"{label[self.paper]}. Every page must be {label[self.paper]}.",
                         page=wrong[0],
                         detail=f"Found: {', '.join(sizes)}. Pages: {', '.join(map(str, wrong))}. "
                                + ("Word: Layout > Size > A4. LaTeX: \\documentclass[conference,"
                                   "a4paper]{IEEEtran}, and check that the PDF viewer/printer "
                                   "did not rescale to Letter." if self.paper == "a4" else
                                   "Word: Layout > Size > Letter. LaTeX: letterpaper option."))
            else:
                self.add(PASS, "Page setup", f"All {len(names)} pages are {label[self.paper]}.")
        else:
            self.paper = detected or "letter"
            if detected is None:
                self.add(ERROR, "Page setup", f"Paper size {r0.width / spec.MM:.0f} x "
                         f"{r0.height / spec.MM:.0f} mm is neither A4 nor US Letter.", page=1)
            else:
                self.add(PASS, "Page setup", f"Paper size is {label[detected]}.")
            if len(set(names)) > 1:
                odd = [i + 1 for i, n in enumerate(names) if n != detected]
                self.add(ERROR, "Page setup", "Pages have different sizes.",
                         detail="Pages differing from page 1: " + ", ".join(map(str, odd)))
        rot = [i + 1 for i, p in enumerate(self.doc) if p.rotation]
        if rot:
            self.add(WARNING, "Page setup", "Some pages are rotated (landscape).",
                     detail="Pages: " + ", ".join(map(str, rot)))
        self.res.paper = self.paper
        self.res.measurements["Paper size"] = (
            f"{r0.width / spec.MM:.0f} x {r0.height / spec.MM:.0f} mm "
            f"({ {'letter': 'US Letter', 'a4': 'A4'}.get(detected, 'non-standard') })")

    def check_page_count(self):
        n = self.doc.page_count
        lo, hi = self.min_pages, self.max_pages
        limit = (f"{lo}-{hi}" if lo and hi else f"at most {hi}" if hi else f"at least {lo}")
        if hi and n > hi:
            self.add(ERROR, "Page setup", f"Paper has {n} pages; the page limit is {hi}.",
                     detail=f"Allowed: {limit} pages (set in the app or in spec.py).")
        elif lo and n < lo:
            self.add(WARNING, "Page setup", f"Paper has only {n} page(s); the expected length "
                     f"is {limit} pages.")
        elif lo or hi:
            self.add(PASS, "Page setup", f"Page count {n} is within the limit ({limit} pages).")
        blank = []
        for i in range(n):
            if not self.spans[i] and not self.page_images[i] and not self.drawings[i]:
                blank.append(i + 1)
        if blank:
            self.add(WARNING, "Page setup", "Blank page(s) found.",
                     detail="Pages: " + ", ".join(map(str, blank)))

    # -------------------------------------------------------------------- fonts
    def check_fonts(self):
        fonts = {}
        for pno, page in enumerate(self.doc):
            try:
                for xref, ext, ftype, basefont, *_ in page.get_fonts():
                    key = xref
                    if key not in fonts:
                        fonts[key] = {"name": clean_font(basefont) or "(unnamed)",
                                      "type": ftype, "ext": ext, "pages": set()}
                    fonts[key]["pages"].add(pno + 1)
            except Exception:  # noqa: BLE001
                continue
        not_emb = sorted({f["name"] for f in fonts.values()
                          if f["ext"] == "n/a" and f["type"] != "Type3"})
        type3 = [f for f in fonts.values() if f["type"] == "Type3"]
        if not_emb:
            self.add(ERROR, "Fonts", f"{len(not_emb)} font(s) are NOT embedded. IEEE PDF "
                     "eXpress requires all fonts to be embedded.",
                     detail="Fonts: " + ", ".join(not_emb) +
                     ". Fix: Word -> File > Options > Save > 'Embed fonts in the file', then "
                     "Save as PDF; LaTeX -> use pdflatex, or ps2pdf with -dEmbedAllFonts=true.")
            self._fonts_reported = True
        if type3:
            pages = sorted({p for f in type3 for p in f["pages"]})
            self.res.measurements["Type 3 fonts on pages"] = ", ".join(map(str, pages))
        # character-weighted font usage
        usage = Counter()
        for pspans in self.spans:
            for _, text, _, font in pspans:
                usage[font] += len(text.strip())
        total = sum(usage.values()) or 1
        emb = {f["name"]: f for f in fonts.values()}
        for name, n in usage.most_common(25):
            f = emb.get(name, {})
            self.res.fonts.append({
                "name": name, "share": f"{100 * n / total:.1f}%",
                "type": f.get("type", "?"),
                "embedded": "no" if f.get("ext") == "n/a" and f.get("type") != "Type3" else "yes",
                "times": "yes" if is_times(name) else ("math/mono" if is_math(name) else "no"),
            })
        # body text font
        body = Counter()
        for ln in self.body_lines:
            body[ln.font] += len(ln.text)
        btotal = sum(body.values())
        if btotal:
            times = sum(n for fnt, n in body.items() if is_times(fnt))
            nonmath = sum(n for fnt, n in body.items() if not is_math(fnt) or is_times(fnt)) or 1
            top = ", ".join(f"{k} ({100 * v / btotal:.0f}%)" for k, v in body.most_common(3))
            self.res.measurements["Body font"] = top
            if times / nonmath < 0.75:
                self.add(ERROR, "Fonts", "Body text is not set in Times / Times New Roman, "
                         "as required by the IEEE template.", detail="Body fonts found: " + top)
            else:
                self.add(PASS, "Fonts", "Body text uses a Times font.", detail=top)

    def check_font_sizes(self):
        bs = self.body_size
        self.res.measurements["Body font size"] = f"{bs:g} pt"
        if abs(bs - spec.BODY_SIZE) > spec.BODY_SIZE_TOL:
            self.add(ERROR, "Fonts", f"Body text size is {bs:g} pt; IEEE conference papers "
                     f"use {spec.BODY_SIZE:g} pt.")
        else:
            self.add(PASS, "Fonts", f"Body text size is {bs:g} pt.")

    # ------------------------------------------------------------------ columns
    def _column_stats(self, pno):
        r = self.page_rects[pno]
        cx = r.width / 2
        lines = [ln for ln in self.body_lines if ln.page == pno]
        left = [ln for ln in lines if ln.bbox.x1 <= cx + 3]
        right = [ln for ln in lines if ln.bbox.x0 >= cx - 3]
        span = [ln for ln in lines if ln.bbox.x0 < cx - 20 and ln.bbox.x1 > cx + 20]
        return lines, left, right, span

    def check_columns(self):
        self.two_col_pages = set()
        single = []
        lx0, lx1, rx0, rx1 = [], [], [], []
        for pno in range(self.doc.page_count):
            lines, left, right, span = self._column_stats(pno)
            if len(lines) < 12:
                continue
            if len(span) > 0.5 * len(lines):
                single.append(pno + 1)
            elif left and right:
                self.two_col_pages.add(pno)
                lx0 += [ln.bbox.x0 for ln in left]
                lx1 += [ln.bbox.x1 for ln in left]
                rx0 += [ln.bbox.x0 for ln in right]
                rx1 += [ln.bbox.x1 for ln in right]
        n_checked = len(single) + len(self.two_col_pages)
        if n_checked == 0:
            self.add(INFO, "Layout", "Not enough body text to determine the column layout.")
            return
        if len(single) > len(self.two_col_pages):
            self.add(ERROR, "Layout", "Paper is in single-column format. IEEE conference "
                     "papers must use the two-column format.",
                     detail="Single-column pages: " + ", ".join(map(str, single)))
            self.res.measurements["Layout"] = "single column"
            return
        if single:
            self.add(WARNING, "Layout", "Some pages are single-column.",
                     detail="Pages: " + ", ".join(map(str, single)))
        self.res.measurements["Layout"] = "two columns"

        def pct(vals, q):
            vals = sorted(vals)
            return vals[min(len(vals) - 1, int(q * len(vals)))]
        if lx0 and rx0:
            lw = pct(lx1, 0.9) - pct(lx0, 0.1)
            rw = pct(rx1, 0.9) - pct(rx0, 0.1)
            gap = pct(rx0, 0.1) - pct(lx1, 0.9)
            m = spec.MARGINS[self.paper]
            pw = self.page_rects[0].width
            exp_w = (pw - m["left"] - m["right"] - spec.COLUMN_GAP) / 2
            mm = spec.MM
            self.res.measurements["Column width"] = (f"{lw / mm:.1f} mm / {rw / mm:.1f} mm "
                                                     f"(expected {exp_w / mm:.1f} mm)")
            self.res.measurements["Column gap"] = (f"{gap / mm:.2f} mm = {gap / 72:.3f} in "
                                                   f"(expected {spec.COLUMN_GAP / mm:.2f} mm)")
            bad = [w for w in (lw, rw) if abs(w - exp_w) > spec.COLUMN_WIDTH_TOL]
            if bad:
                self.add(WARNING, "Layout",
                         f"Column width is {lw / mm:.1f} mm / {rw / mm:.1f} mm; with the required "
                         f"margins and a {spec.COLUMN_GAP / mm:.2f} mm gap each column should be "
                         f"about {exp_w / mm:.1f} mm wide.")
            else:
                self.add(PASS, "Layout", f"Two-column layout, columns {lw / mm:.1f} mm wide.")
            if gap < spec.COLUMN_GAP_MIN or gap > spec.COLUMN_GAP_MAX:
                self.add(ERROR if gap < spec.COLUMN_GAP_MIN - 1.5 * mm or
                         gap > spec.COLUMN_GAP_MAX + 3 * mm else WARNING, "Layout",
                         f"Space between columns is {gap / mm:.2f} mm ({gap / 72:.3f} in); "
                         f"required {spec.COLUMN_GAP / mm:.2f} mm "
                         f"(accepted {spec.COLUMN_GAP_MIN / mm:.1f}-{spec.COLUMN_GAP_MAX / mm:.1f} mm).")
            else:
                self.add(PASS, "Layout", f"Space between columns is {gap / mm:.2f} mm.")

        # last page column balance
        last = self.doc.page_count - 1
        if last in self.two_col_pages and last > 0:
            r = self.page_rects[last]
            cx = r.width / 2
            lb = [ln.bbox.y1 for ln in self.lines if ln.page == last and ln.horizontal
                  and ln.bbox.x1 <= cx + 3]
            rb = [ln.bbox.y1 for ln in self.lines if ln.page == last and ln.horizontal
                  and ln.bbox.x0 >= cx - 3]
            m = spec.MARGINS[self.paper]
            th = r.height - m["top"] - m["bottom"]
            if lb and rb:
                diff = max(lb) - max(rb)
                if abs(diff) > 0.2 * th:
                    self.add(WARNING, "Layout", "Columns on the last page are not balanced "
                             f"(heights differ by {abs(diff) / 72:.1f} in). IEEE asks for "
                             "equal-length columns on the last page.", page=last + 1)

    # ------------------------------------------------------------------ margins
    def check_margins(self):
        m = spec.MARGINS[self.paper]
        page_numbers, headers = [], []
        hits = defaultdict(list)
        for pno in range(self.doc.page_count):
            r = self.page_rects[pno]
            top_lim, bot_lim = m["top"], r.height - m["bottom"]
            left_lim, right_lim = m["left"], r.width - m["right"]
            elems = []                       # (rect, kind, text)
            for rect, text, size, font in self.spans[pno]:
                # measure text at its baseline: descenders (g, p, y) may hang below the
                # text block in every template, so ignore ~22% of the font size
                rr = pymupdf.Rect(rect.x0, rect.y0, rect.x1, max(rect.y0, rect.y1 - 0.22 * size))
                elems.append((rr, "text", text.strip()))
            for info in self.page_images[pno]:
                elems.append((pymupdf.Rect(info["bbox"]) & r, "image", ""))
            for dr in self.drawings[pno]:
                elems.append((dr & r if not (dr & r).is_empty else dr, "drawing", ""))
            # header / footer text = lines entirely outside text block vertically
            keep = []
            page_lines = [ln for ln in self.lines if ln.page == pno]
            margin_lines = set()
            for ln in page_lines:
                outside_top = ln.bbox.y1 <= top_lim + 1
                outside_bot = ln.bbox.y0 >= bot_lim - 1
                outside_side = ln.bbox.x1 <= left_lim + 1 or ln.bbox.x0 >= right_lim - 1
                if not (outside_top or outside_bot or outside_side):
                    continue
                t = ln.text.strip()
                key = (round(ln.bbox.x0), round(ln.bbox.y0))
                if re.search(r"arXiv:\d{4}\.\d{4,5}", t):
                    self.add(WARNING, "Margins", "arXiv identifier stamp found in the margin. "
                             "Remove it for IEEE submission.", page=pno + 1, rect=rect_t(ln.bbox))
                    margin_lines.add(key)
                elif re.fullmatch(r"(page\s*)?[-–]?\s*\d{1,4}\s*[-–]?(\s*(of|/)\s*\d+)?", t,
                                  re.I):
                    page_numbers.append(pno + 1)
                    margin_lines.add(key)
                elif pno == 0 and outside_bot and re.search(
                        r"(©|\(c\)|copyright|IEEE|\$\d|97[89]-|DOI|ISBN|\d{4}\s*IEEE)", t, re.I):
                    self.add(INFO, "Margins", "Copyright / ISBN notice found at the bottom of "
                             "page 1 (allowed when inserted as instructed by the conference).",
                             page=1, detail=t[:120])
                    margin_lines.add(key)
                elif outside_top or outside_bot:
                    headers.append((pno + 1, t, ln.bbox))
                    margin_lines.add(key)
            margin_line_rects = [ln.bbox for ln in page_lines
                                 if (round(ln.bbox.x0), round(ln.bbox.y0)) in margin_lines]

            def in_margin_line(rect):
                return any(mr.contains(rect.tl + (0.5, 0.5)) or mr.intersects(rect)
                           and rect.width < mr.width + 2 for mr in margin_line_rects)

            content = pymupdf.Rect()
            worst = {"left": (0, None, ""), "right": (0, None, ""), "top": (0, None, ""),
                     "bottom": (0, None, "")}
            offenders = defaultdict(list)
            for rect, kind, text in elems:
                if rect.is_empty or rect.is_infinite:
                    continue
                if kind == "text" and in_margin_line(rect):
                    continue
                content |= rect
                intr = {"left": left_lim - rect.x0, "right": rect.x1 - right_lim,
                        "top": top_lim - rect.y0, "bottom": rect.y1 - bot_lim}
                for side, v in intr.items():
                    if v > spec.MARGIN_TOL_SILENT:
                        offenders[side].append(rect)
                        if v > worst[side][0]:
                            worst[side] = (v, rect, kind)
            for side, (v, rect, kind) in worst.items():
                if rect is None:
                    continue
                union = pymupdf.Rect()
                for o in offenders[side]:
                    union |= o
                hits[side].append((pno + 1, v, rect_t(union), kind))
            if not content.is_empty:
                self.res.margins.append({
                    "page": pno + 1,
                    "top": content.y0 / 72, "bottom": (r.height - content.y1) / 72,
                    "left": content.x0 / 72, "right": (r.width - content.x1) / 72,
                    "ok": not any(w[1] is not None for w in worst.values())})
        for side, lst in hits.items():
            worst = max(lst, key=lambda x: x[1])
            sev = ERROR if worst[1] > spec.MARGIN_TOL_ERROR else WARNING
            pages = [x[0] for x in lst]
            kinds = sorted({x[3] for x in lst})
            self.add(sev, "Margins", f"Content ({'/'.join(kinds)}) extends up to "
                     f"{fmt_in(worst[1])} into the {side} margin on {len(pages)} page(s).",
                     page=worst[0], rect=worst[2], thumb=True,
                     extra=[(x[0], x[2]) for x in lst if x is not worst],
                     detail=f"Required minimum {side} margin is {fmt_in(m[side])}. Pages: "
                            + ", ".join(map(str, pages)) + f". Worst on page {worst[0]}.")
        if page_numbers:
            self.add(WARNING, "Margins", "Page numbers found. IEEE conference camera-ready "
                     "papers must not contain page numbers (they are added by IEEE).",
                     detail="Pages: " + ", ".join(map(str, sorted(set(page_numbers)))))
        if headers:
            pages = sorted({h[0] for h in headers})
            self.add(WARNING, "Margins", "Header/footer text found in the margins. IEEE "
                     "conference papers must not have headers or footers.",
                     detail="Pages: " + ", ".join(map(str, pages)) + ". Example: \"" +
                     headers[0][1][:80] + "\"", page=headers[0][0], rect=rect_t(headers[0][2]))
        if self.res.margins and all(x["ok"] for x in self.res.margins):
            self.add(PASS, "Margins", "All content is inside the required margins on every "
                     f"page (top {m['top'] / spec.MM:.1f} mm, bottom {m['bottom'] / spec.MM:.1f} mm, "
                     f"left {m['left'] / spec.MM:.1f} mm, right {m['right'] / spec.MM:.1f} mm).")

    # ---------------------------------------------------------- front matter
    def check_front_matter(self):
        p1 = [ln for ln in self.lines if ln.page == 0 and ln.horizontal]
        if not p1:
            return
        r = self.page_rects[0]
        top = [ln for ln in p1 if ln.bbox.y0 < 0.45 * r.height]
        if top:
            tsize = max(ln.size for ln in top)
            title_lines = [ln for ln in top if ln.size >= tsize - 0.6]
            title = " ".join(ln.text for ln in title_lines)
            self.res.measurements["Title"] = title[:150]
            self.res.measurements["Title font size"] = f"{tsize:g} pt"
            lo, hi = spec.TITLE_SIZE_RANGE
            if not (lo <= tsize <= hi):
                self.add(WARNING, "Title", f"Title font size is {tsize:g} pt; the IEEE template "
                         f"uses {spec.TITLE_SIZE:g} pt.", page=1,
                         rect=rect_t(title_lines[0].bbox))
            else:
                self.add(PASS, "Title", f"Title font size is {tsize:g} pt.")
            letters = [c for c in title if c.isalpha()]
            if len(letters) > 10 and sum(c.isupper() for c in letters) / len(letters) > 0.9:
                self.add(WARNING, "Title", "Title is in ALL CAPS. IEEE titles use Title Case.",
                         page=1)
            if re.search(r"\b(paper title|use style)\b", title, re.I):
                self.add(ERROR, "Title", "Title still contains template placeholder text.",
                         page=1)

        text1 = "\n".join(ln.text for ln in p1)
        ab = re.search(r"(?im)^\s*(Abstract|ABSTRACT)\s*([—–\-:.]*)\s*", text1)
        if not ab:
            self.add(ERROR, "Abstract", "No 'Abstract' found on page 1.", page=1)
        else:
            sep = ab.group(2)
            if sep not in ("—", "–", "— ", "-", "--"):
                self.add(INFO, "Abstract", "IEEE style is 'Abstract—' (bold italic, em "
                         "dash) followed by the text on the same line.", page=1)
            rest = text1[ab.end():]
            end = re.search(r"(?i)(Index\s*Terms|Key\s*words|Keywords)|^\s*I\.\s+I\s?NTRODUCTION|"
                            r"^\s*1\.?\s+Introduction", rest, re.M)
            body = rest[:end.start()] if end else rest[:2500]
            words = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", body))
            self.res.measurements["Abstract words"] = words
            lo, hi = spec.ABSTRACT_WORDS
            if words < lo or words > hi:
                self.add(WARNING, "Abstract", f"Abstract has about {words} words; IEEE "
                         f"recommends {lo}-{hi} words.", page=1)
            else:
                self.add(PASS, "Abstract", f"Abstract length is about {words} words.")
            if re.search(r"\[\d+([,–\-]\s*\d+)*\]", body):
                self.add(WARNING, "Abstract", "Abstract contains citations. IEEE abstracts "
                         "should not cite references.", page=1)
            # size of abstract text
            abl = [ln for ln in p1 if ln.text.lstrip().lower().startswith("abstract")]
            if abl:
                blk = [ln for ln in p1 if ln.block == abl[0].block]
                sz = Counter()
                for ln in blk:
                    sz[ln.size] += len(ln.text)
                asz = sz.most_common(1)[0][0]
                self.res.measurements["Abstract font size"] = f"{asz:g} pt"
                if asz > spec.ABSTRACT_SIZE + 0.6:
                    self.add(WARNING, "Abstract", f"Abstract text is {asz:g} pt; the IEEE "
                             f"template uses {spec.ABSTRACT_SIZE:g} pt bold.", page=1,
                             rect=rect_t(abl[0].bbox))
            if not re.search(r"(?i)(Index\s*Terms|Key\s*words|Keywords)", text1):
                self.add(WARNING, "Abstract", "No 'Index Terms' / 'Keywords' found after the "
                         "abstract.", page=1)

    # --------------------------------------------------------------- headings
    def check_headings(self):
        roman = []
        intro = None
        for ln in self.lines:
            if not ln.horizontal or len(ln.text) > 75:
                continue
            m = ROMAN_HEAD_RE.match(ln.text)
            if m:
                rest = m.group(2)
                letters = [c for c in rest if c.isalpha()]
                if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6 and \
                        roman_to_int(m.group(1)):
                    roman.append((roman_to_int(m.group(1)), rest.strip(), ln))
            low = re.sub(r"\s+", "", ln.text.lower())
            if intro is None and re.fullmatch(r"([ivx]+\.|\d+\.?)?introduction", low):
                intro = ln
        if roman:
            nums = [n for n, _, _ in roman]
            # keep longest increasing run starting at 1 to ignore stray matches
            expected = 1
            seq_ok = True
            for n, t, ln in roman:
                if n == expected:
                    expected += 1
                elif n > expected:
                    seq_ok = False
                    self.add(WARNING, "Headings", f"Section numbering jumps to {n} "
                             f"(expected {expected}).", page=ln.page + 1, rect=rect_t(ln.bbox))
                    expected = n + 1
            self.res.measurements["Sections"] = len(set(nums))
            self.sections = set(nums)
            if seq_ok:
                self.add(PASS, "Headings", f"{len(set(nums))} sections numbered with Roman "
                         "numerals (I, II, III, ...).")
        elif intro is not None:
            if re.match(r"^\s*\d", intro.text):
                self.add(WARNING, "Headings", "Section headings use Arabic numbers (1, 2, 3). "
                         "IEEE uses Roman numerals in small caps (I. INTRODUCTION).",
                         page=intro.page + 1, rect=rect_t(intro.bbox))
            else:
                self.add(WARNING, "Headings", "Section headings are not numbered. IEEE uses "
                         "Roman numerals (I. INTRODUCTION, II. ...).",
                         page=intro.page + 1, rect=rect_t(intro.bbox))
        else:
            self.add(WARNING, "Headings", "Could not find an 'Introduction' section heading.")
        for ln in self.lines:
            t = ln.text.strip().lower()
            if len(t) < 30 and re.fullmatch(r"([ivx]+\.\s*)?acknowledgements?", t):
                self.add(INFO, "Headings", "IEEE spells it 'Acknowledgment' (no 'e' after "
                         "'g', singular).", page=ln.page + 1)

    # --------------------------------------------------------------- captions
    def _graphics(self, pno):
        g = [pymupdf.Rect(i["bbox"]) for i in self.page_images[pno]]
        g += [d for d in self.drawings[pno] if d.width > 1 or d.height > 1]
        return g

    def check_captions(self):
        figs, tabs = [], []
        for ln in self.lines:
            if not ln.horizontal or not ln.first_in_block:
                continue
            m = FIG_RE.match(ln.text)
            if m:
                figs.append({"num": int(m.group(2)), "label": m.group(1), "sep": m.group(3),
                             "line": ln})
                continue
            m = TAB_RE.match(ln.text)
            if m:
                label, num, sep, rest = m.groups()
                if label == "Table" and not sep and len(ln.text.strip()) > 12:
                    continue                          # "Table 2 shows ..." in body text
                if label == "Table" and not sep and ln.size >= self.body_size - 0.3 \
                        and len(ln.text.strip()) > 9:
                    continue
                n = roman_to_int(num) if not num.isdigit() else int(num)
                tabs.append({"num": n, "raw": num, "label": label, "line": ln})
        self.figs, self.tabs = figs, tabs
        self.res.measurements["Figures (captions)"] = len(figs)
        self.res.measurements["Tables (captions)"] = len(tabs)

        # label style
        bad_fig = [f for f in figs if f["label"].rstrip(".").lower() != "fig"]
        if bad_fig:
            self.add(WARNING, "Figures", "Figure captions should start with 'Fig. N.' "
                     f"(found '{bad_fig[0]['label']} {bad_fig[0]['num']}').",
                     page=bad_fig[0]["line"].page + 1, rect=rect_t(bad_fig[0]["line"].bbox),
                     detail="Pages: " + ", ".join(sorted({str(f['line'].page + 1) for f in bad_fig})))
        bad_tab = [t for t in tabs if t["label"] != "TABLE" or t["raw"].isdigit()]
        if bad_tab:
            t = bad_tab[0]
            self.add(WARNING, "Tables", "Table captions should be 'TABLE I', 'TABLE II', ... "
                     f"(upper case, Roman numerals); found '{t['label']} {t['raw']}'.",
                     page=t["line"].page + 1, rect=rect_t(t["line"].bbox))
        # numbering
        for kind, items in (("Figure", figs), ("Table", tabs)):
            nums = [i["num"] for i in items if i["num"]]
            dup = [n for n, c in Counter(nums).items() if c > 1]
            if dup:
                self.add(WARNING, kind + "s", f"{kind} number(s) used more than once: "
                         + ", ".join(map(str, dup)) + " (may be sub-captions).")
            if nums and sorted(set(nums)) != list(range(1, max(nums) + 1)):
                missing = sorted(set(range(1, max(nums) + 1)) - set(nums))
                self.add(WARNING, kind + "s", f"{kind} numbering has gaps; missing: "
                         + ", ".join(map(str, missing)))
            if nums and nums != sorted(nums):
                self.add(WARNING, kind + "s", f"{kind}s are not numbered in order of "
                         "appearance.")
        # caption sizes
        big = [i for i in figs + tabs if i["line"].size > spec.SMALL_TEXT_MAX]
        if big:
            self.add(WARNING, "Captions", f"{len(big)} caption(s) are larger than "
                     f"{spec.SMALL_TEXT_MAX:g} pt; IEEE captions are {spec.CAPTION_SIZE:g} pt.",
                     page=big[0]["line"].page + 1, rect=rect_t(big[0]["line"].bbox))
        # figure caption placement (below figure)
        for f in figs:
            ln = f["line"]
            g = self._graphics(ln.page)

            def hov(a):
                ov = min(a.x1, ln.bbox.x1) - max(a.x0, ln.bbox.x0)
                return ov > 0.3 * min(a.width, ln.bbox.width)
            above = any(hov(a) and a.y1 <= ln.bbox.y0 + 4 and ln.bbox.y0 - a.y1 < 60 for a in g)
            below = any(hov(a) and a.y0 >= ln.bbox.y1 - 4 and a.y0 - ln.bbox.y1 < 25 for a in g)
            f["placement"] = "below figure" if above else ("above figure?" if below else "-")
            if below and not above:
                self.add(WARNING, "Figures", f"Caption of Fig. {f['num']} seems to be ABOVE "
                         "the figure. IEEE places figure captions below figures.",
                         page=ln.page + 1, rect=rect_t(ln.bbox))
        # ---- in-text references to figures / tables (both directions)
        caption_blocks = {(i["line"].page, i["line"].block) for i in figs + tabs}
        text, pages_at = self._text_with_pages(
            lambda ln: (ln.page, ln.block) not in caption_blocks)
        fig_refs = defaultdict(list)            # num -> [pages]
        for m in re.finditer(r"\b(?:Figs?\.?|Figures?|FIGS?\.?|FIGURES?)\s*~?(\d+(?:\s*\(?[a-z]?\)?"
                             r"\s*(?:,|and|&|–|-|—|to)\s*\d+)*)", text):
            for n in self._expand_nums(m.group(1)):
                fig_refs[n].append(pages_at(m.start()))
        tab_refs = defaultdict(list)
        for m in re.finditer(r"\b(?:Tables?|TABLES?|Tabs?\.)\s*~?((?:[IVXLC]+|\d+)(?:\s*(?:,|and|&|"
                             r"–|-|to)\s*(?:[IVXLC]+|\d+))*)\b", text):
            parts = re.split(r"\s*(?:,|and|&|–|-|to)\s*", m.group(1))
            nums = [roman_to_int(p) if not p.isdigit() else int(p) for p in parts]
            nums = [n for n in nums if n]
            if len(nums) == 2 and re.search(r"–|-|to", m.group(1)) and 0 < nums[1] - nums[0] < 30:
                nums = list(range(nums[0], nums[1] + 1))
            for n in nums:
                tab_refs[n].append(pages_at(m.start()))
        self.fig_refs, self.tab_refs = fig_refs, tab_refs
        fig_nums = {f["num"] for f in figs}
        tab_nums = {t["num"] for t in tabs if t["num"]}
        raw = {t["num"]: t["raw"] for t in tabs}
        unref_f = sorted(fig_nums - set(fig_refs))
        unref_t = sorted(tab_nums - set(tab_refs))
        if unref_f:
            self.add(ERROR, "In-text references", "Figure(s) never referred to in the text: "
                     + ", ".join(f"Fig. {n}" for n in unref_f) + ". Every figure must be "
                     "cited in the text (e.g. \"as shown in Fig. 1\").")
        if unref_t:
            self.add(ERROR, "In-text references", "Table(s) never referred to in the text: "
                     + ", ".join(f"TABLE {raw.get(n, n)}" for n in unref_t) + ". Every table "
                     "must be cited in the text (e.g. \"Table I lists ...\").")
        if figs:
            bad = sorted(n for n in fig_refs if n not in fig_nums and n < 100)
            if bad:
                self.add(ERROR, "In-text references", "The text refers to figure(s) that do not "
                         "exist: " + ", ".join(f"Fig. {n} (p. {fig_refs[n][0]})" for n in bad) + ".",
                         detail=f"The paper has {len(fig_nums)} figure caption(s): "
                                + ", ".join(map(str, sorted(fig_nums))))
        if tabs:
            bad = sorted(n for n in tab_refs if n not in tab_nums and n < 100)
            if bad:
                self.add(ERROR, "In-text references", "The text refers to table(s) that do not "
                         "exist: " + ", ".join(f"Table {self._roman(n)} (p. {tab_refs[n][0]})"
                                               for n in bad) + ".")
        if (figs or tabs) and not unref_f and not unref_t:
            self.add(PASS, "In-text references", "Every figure and table is referred to in "
                     "the text.")
        for f in figs:
            self.res.figures.append({"num": f["num"], "page": f["line"].page + 1,
                                     "caption": f["line"].text[:90],
                                     "placement": f.get("placement", "-"),
                                     "cited": "yes" if f["num"] in fig_refs else "NO"})
        for kind, items, refs, lab in (("Figure", sorted(fig_nums), fig_refs, "Fig. {}"),
                                       ("Table", sorted(tab_nums), tab_refs, "TABLE {}")):
            for n in items:
                self.res.crossrefs.append({
                    "item": lab.format(raw.get(n, n) if kind == "Table" else n),
                    "exists": "yes", "times": len(refs.get(n, [])),
                    "pages": ", ".join(map(str, sorted(set(refs.get(n, []))))) or "-"})
        self.check_equations_sections(text, pages_at)

    def check_equations_sections(self, text, pages_at):
        """Equation numbers '(n)' at the right edge of a column, and 'Eq. (n)' /
        'Section III' references pointing at things that do not exist."""
        eqs = set()
        for pno, pspans in enumerate(self.spans):
            r = self.page_rects[pno]
            m = spec.MARGINS[self.paper]
            cx = r.width / 2
            edges = (cx - spec.COLUMN_GAP / 2, r.width - m["right"])
            for rect, t, size, font in pspans:
                mm = re.fullmatch(r"\s*\((\d{1,3})\)\s*", t)
                if mm and any(abs(rect.x1 - e) < 8 for e in edges):
                    eqs.add(int(mm.group(1)))
        eq_refs = defaultdict(list)
        for mt in re.finditer(r"\b(?:Eqs?\.|Equations?|equations?|Eqn\.?)\s*~?\(?(\d{1,3})\)?"
                              r"(?:\s*(?:and|,|–|-|to)\s*\(?(\d{1,3})\)?)?", text):
            for g in mt.groups():
                if g:
                    eq_refs[int(g)].append(pages_at(mt.start()))
        if eqs:
            self.res.measurements["Numbered equations"] = len(eqs)
            bad = sorted(n for n in eq_refs if n not in eqs)
            if bad:
                self.add(ERROR, "In-text references", "The text refers to equation(s) that do not "
                         "exist: " + ", ".join(f"({n}) on p. {eq_refs[n][0]}" for n in bad) + ".",
                         detail="Equation numbers found: " + ", ".join(map(str, sorted(eqs))))
            if sorted(eqs) != list(range(1, max(eqs) + 1)):
                missing = sorted(set(range(1, max(eqs) + 1)) - eqs)
                if len(missing) <= 10:
                    self.add(WARNING, "In-text references", "Equation numbering has gaps: missing "
                             + ", ".join(f"({n})" for n in missing) + ".")
            for n in sorted(eqs):
                self.res.crossrefs.append({"item": f"Equation ({n})", "exists": "yes",
                                           "times": len(eq_refs.get(n, [])),
                                           "pages": ", ".join(map(str, sorted(set(eq_refs.get(n, []))))) or "-"})
        secs = getattr(self, "sections", set())
        if secs:
            bad = []
            for mt in re.finditer(r"\b(?:Sections?|Sec\.|SECTION)\s*~?([IVXL]+)\b", text):
                n = roman_to_int(mt.group(1))
                if n and n not in secs:
                    bad.append((mt.group(1), pages_at(mt.start())))
            if bad:
                self.add(ERROR, "In-text references", "The text refers to section(s) that do not "
                         "exist: " + ", ".join(f"Section {s} (p. {p})" for s, p in bad[:10]) + ".",
                         detail=f"The paper has sections I-{self._roman(max(secs))}.")

    def _text_with_pages(self, keep=lambda ln: True, before=None):
        """Join text lines (de-hyphenated) and return (text, page_at(offset))."""
        import bisect
        chunks, starts, pages = [], [], []
        length = 0
        for ln in self.lines:
            if not ln.horizontal or not keep(ln):
                continue
            if before is not None and self._after(ln, before):
                continue
            t = ln.text
            if chunks and chunks[-1].endswith("-") and t[:1].islower():
                chunks[-1] = chunks[-1][:-1]        # re-join a word hyphenated at line end
                length -= 1
            elif chunks:
                chunks.append(" ")
                length += 1
            starts.append(length)
            pages.append(ln.page + 1)
            chunks.append(t)
            length += len(t)
        text = "".join(chunks)

        def page_at(offset):
            i = bisect.bisect_right(starts, offset) - 1
            return pages[max(0, i)] if pages else None
        return text, page_at

    @staticmethod
    def _roman(n):
        vals = [(100, "C"), (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                (5, "V"), (4, "IV"), (1, "I")]
        out = ""
        for v, s in vals:
            while n >= v:
                out += s
                n -= v
        return out

    @staticmethod
    def _expand_nums(s):
        out = set()
        s = re.sub(r"\([a-z]\)", "", s)
        for part in re.split(r"\s*(?:,|and|&)\s*", s):
            rng = re.split(r"\s*(?:–|-|—|to)\s*", part)
            nums = [int(x) for x in rng if x.strip().isdigit()]
            if len(nums) == 2 and 0 < nums[1] - nums[0] < 50:
                out |= set(range(nums[0], nums[1] + 1))
            else:
                out |= set(nums)
        return out

    def _body_text(self, exclude=()):
        ex = {id(x) for x in exclude}
        parts = []
        for ln in self.lines:
            if id(ln) in ex:
                continue
            t = ln.text
            if parts and parts[-1].endswith("-") and t[:1].islower():
                parts[-1] = parts[-1][:-1] + t
            else:
                parts.append(t)
        return " ".join(parts)

    # ------------------------------------------------------------------ tables
    def check_tables(self):
        for t in self.tabs:
            ln = t["line"]
            pno = ln.page
            r = self.page_rects[pno]
            cx = r.width / 2
            bx = pymupdf.Rect(ln.bbox)
            # include the rest of the caption block (title line(s))
            for o in self.lines:
                if o.page == pno and o.block == ln.block:
                    bx |= o.bbox
            m = spec.MARGINS[self.paper]
            if pno in self.two_col_pages and abs((bx.x0 + bx.x1) / 2 - cx) > 20:
                xr = (m["left"] - 10, cx + 5) if bx.x1 <= cx + 5 else (cx - 5, r.width - m["right"] + 10)
            else:
                xr = (m["left"] - 10, r.width - m["right"] + 10)
            entry = {"num": t["raw"], "page": pno + 1, "caption": ln.text[:80],
                     "status": "", "rect": None}
            # images just below the caption
            cand = []
            for info in self.page_images[pno]:
                ib = pymupdf.Rect(info["bbox"])
                inside = (min(ib.x1, xr[1]) - max(ib.x0, xr[0])) / max(ib.width, 1)
                if inside > 0.5 and bx.y1 - 6 <= ib.y0 <= bx.y1 + 90 and ib.height > 15:
                    cand.append(ib)
            cand.sort(key=lambda b: b.y0)
            if cand:
                ib = cand[0]
                chars = sum(len(tx.strip()) for rc, tx, _, _ in self.spans[pno]
                            if ib.contains((rc.tl + rc.br) / 2))
                if chars < 15:
                    entry["status"] = "PASTED IMAGE"
                    entry["rect"] = rect_t(ib)
                    self.add(ERROR, "Tables", f"TABLE {t['raw']} is a pasted picture, not a "
                             "real table. IEEE requires tables to be created with the table "
                             "tool (text with rules), not inserted as images.", page=pno + 1,
                             rect=rect_t(ib), thumb=True,
                             detail="Re-create it with Word Insert > Table or LaTeX "
                                    "tabular; screenshots blur in print and are not searchable.")
                    self.res.tables.append(entry)
                    continue
            # real table?
            region = pymupdf.Rect(xr[0], bx.y1 - 2, xr[1], min(bx.y1 + 120, r.height))
            vec = None
            try:
                tf = self.doc[pno].find_tables(clip=pymupdf.Rect(xr[0], bx.y1 - 4, xr[1],
                                                                 r.height))
                for tb in tf.tables:
                    tr = pymupdf.Rect(tb.bbox)
                    if tr.y0 - bx.y1 < 90:
                        vec = tr
                        break
            except Exception:  # noqa: BLE001
                pass
            chars = sum(len(tx.strip()) for rc, tx, _, _ in self.spans[pno]
                        if region.contains((rc.tl + rc.br) / 2) and not bx.contains(rc))
            rules = sum(1 for d in self.drawings[pno] if d.height < 2.5 and d.width > 40
                        and region.intersects(d))
            if vec is not None:
                entry["status"] = "real table (ruled grid)"
                entry["rect"] = rect_t(vec)
            elif chars >= 20:
                entry["status"] = "real table (text" + (" + rules)" if rules else ")")
                entry["rect"] = rect_t(region)
            else:
                # maybe the caption is below the table (wrong) - look above
                above_imgs = [pymupdf.Rect(i["bbox"]) for i in self.page_images[pno]
                              if 0 <= bx.y0 - pymupdf.Rect(i["bbox"]).y1 < 30]
                entry["status"] = "not found below caption"
                if above_imgs:
                    entry["status"] = "PASTED IMAGE (caption below)"
                    self.add(ERROR, "Tables", f"TABLE {t['raw']} appears to be an image placed "
                             "above its caption. Tables must be real tables, and IEEE table "
                             "captions go ABOVE the table.", page=pno + 1,
                             rect=rect_t(above_imgs[0]), thumb=True)
                else:
                    self.add(WARNING, "Tables", f"Could not find the body of TABLE {t['raw']} "
                             "directly below its caption (IEEE table captions go above the "
                             "table). Please check it manually.", page=pno + 1,
                             rect=rect_t(bx))
            if entry["status"].startswith("real"):
                pass
            self.res.tables.append(entry)
        real = [t for t in self.res.tables if t["status"].startswith("real")]
        if self.tabs and len(real) == len(self.tabs):
            self.add(PASS, "Tables", f"All {len(real)} table(s) are real (drawn) tables, not "
                     "images.")
        if not self.tabs:
            self.add(INFO, "Tables", "No table captions (TABLE I, ...) found.")

    # ------------------------------------------------------------------ images
    def check_images(self):
        cache = {}
        table_img_rects = {(t["page"], t["rect"]) for t in self.res.tables
                           if t["status"].startswith("PASTED")}
        n_checked = 0
        worst_counts = Counter()
        grouped = {}
        for pno, infos in enumerate(self.page_images):
            r = self.page_rects[pno]
            for info in infos:
                bbox = pymupdf.Rect(info["bbox"]) & r
                if bbox.is_empty:
                    continue
                if bbox.width < spec.IGNORE_IMAGE_BELOW_PT or bbox.height < spec.IGNORE_IMAGE_BELOW_PT:
                    continue
                wpx, hpx = info.get("width", 0), info.get("height", 0)
                a, b, c, d = info["transform"][:4]
                disp_w = math.hypot(a, b) or bbox.width
                disp_h = math.hypot(c, d) or bbox.height
                dpi_x = wpx / (disp_w / 72) if disp_w else 0
                dpi_y = hpx / (disp_h / 72) if disp_h else 0
                dpi = min(dpi_x, dpi_y)
                xref = info.get("xref", 0)
                n_checked += 1
                rec = {"page": pno + 1, "size_in": f"{bbox.width / 72:.2f} x {bbox.height / 72:.2f}",
                       "pixels": f"{wpx} x {hpx}", "dpi": round(dpi), "eff_dpi": round(dpi),
                       "kind": "-", "format": "-", "notes": [], "status": "OK",
                       "rect": rect_t(bbox)}
                ana = None
                if xref:
                    if xref not in cache:
                        cache[xref] = self._analyze_image(xref)
                    ana = cache[xref]
                if ana:
                    rec["kind"] = "line art / diagram" if ana["kind"] == "lineart" else "photo / colour"
                    rec["format"] = ana["format"]
                    if ana["factor"] > 1:
                        rec["eff_dpi"] = round(dpi * ana["scale"] / ana["factor"])
                kind = ana["kind"] if ana else "photo"
                need, err = ((spec.LINEART_DPI_MIN, spec.LINEART_DPI_ERROR) if kind == "lineart"
                             else (spec.PHOTO_DPI_MIN, spec.PHOTO_DPI_ERROR))
                sev = None
                if dpi < err:
                    sev = ERROR
                    rec["notes"].append(f"{round(dpi)} dpi is far below the IEEE minimum "
                                        f"({need} dpi for {'line art' if kind == 'lineart' else 'photos'})")
                elif dpi < need:
                    sev = WARNING
                    rec["notes"].append(f"{round(dpi)} dpi is below the recommended {need} dpi")
                if ana and ana["factor"] > 1 and rec["eff_dpi"] < need:
                    sev = sev or WARNING
                    rec["notes"].append(f"image was upscaled or is blurred: its real detail is "
                                        f"only about {rec['eff_dpi']} dpi (enlarging a small "
                                        "picture does not add detail - use the original)")
                if ana and ana["format"] == "JPEG" and kind == "lineart":
                    sev = sev or WARNING
                    rec["notes"].append("diagram/text saved as JPEG (lossy, blurry edges); "
                                        "use vector PDF/EPS or PNG")
                if ana and ana.get("jpeg_q") and ana["jpeg_q"] < spec.JPEG_QUALITY_MIN:
                    sev = sev or WARNING
                    rec["notes"].append(f"heavy JPEG compression (quality ~{ana['jpeg_q']})")
                is_table_img = (pno + 1, rect_t(info["bbox"])) in table_img_rects or any(
                    t["page"] == pno + 1 and t["rect"] and
                    pymupdf.Rect(t["rect"]).intersects(bbox) for t in self.res.tables
                    if t["status"].startswith("PASTED"))
                if ana and ana["table_score"] >= 0.7 and not is_table_img:
                    self.add(WARNING, "Tables", "This image looks like a table or text "
                             "screenshot. Tables must be typed as real tables, not pasted as "
                             "pictures.", page=pno + 1, rect=rect_t(bbox), thumb=True,
                             detail=f"{ana['hlines']} horizontal rules, {ana['text_bands']} "
                                    "text rows detected inside the picture.")
                    rec["notes"].append("looks like a table/text screenshot")
                    sev = sev or WARNING
                if is_table_img:
                    rec["notes"].append("pasted table image")
                    sev = ERROR
                if sev:
                    rec["status"] = sev.upper()
                    worst_counts[sev] += 1
                    if not is_table_img:
                        notes = [n for n in rec["notes"] if "screenshot" not in n]
                        if notes:
                            key = (xref or id(info), sev, tuple(notes))
                            grouped.setdefault(key, (rec, []))[1].append((pno + 1, rect_t(bbox)))
                rec["notes"] = "; ".join(rec["notes"])
                self.res.images.append(rec)
                # text overlapping image
                for ln in self.body_lines:
                    if ln.page == pno and len(ln.text) > 30:
                        ov = ln.bbox & bbox
                        if not ov.is_empty and ov.width > 6 and ov.height > 0.5 * ln.bbox.height:
                            self.add(WARNING, "Layout", "Body text overlaps an image.",
                                     page=pno + 1, rect=rect_t(ln.bbox), thumb=True)
                            break
        for (xref, sev, notes), (rec, places) in grouped.items():
            pages = sorted({p for p, _ in places})
            where = "" if len(pages) == 1 else f" (same image on {len(pages)} pages: " + \
                ", ".join(map(str, pages)) + ")"
            self.add(sev, "Image quality", f"Image ({rec['size_in']} in, {rec['pixels']} px): "
                     + "; ".join(notes) + "." + where, page=places[0][0], rect=places[0][1],
                     thumb=True, extra=places[1:])
        self.res.measurements["Raster images"] = n_checked
        if n_checked and not worst_counts:
            self.add(PASS, "Image quality", f"All {n_checked} raster image(s) meet the IEEE "
                     "resolution guidelines.")
        if not n_checked:
            self.add(INFO, "Image quality", "No raster images found (vector figures only, "
                     "which is ideal).")

    def _analyze_image(self, xref):
        try:
            gray, scale = imagecheck.pixmap_to_gray(self.doc, xref)
        except Exception:  # noqa: BLE001
            return None
        fmt = "-"
        jq = None
        try:
            filt = self.doc.xref_get_key(xref, "Filter")[1]
            if "DCT" in filt:
                fmt = "JPEG"
                raw = self.doc.xref_stream_raw(xref)
                jq = imagecheck.jpeg_quality(raw)
            elif "JPX" in filt:
                fmt = "JPEG2000"
            elif "Flate" in filt:
                fmt = "lossless (PNG-like)"
            elif "CCITT" in filt or "JBIG2" in filt:
                fmt = "bilevel (fax)"
        except Exception:  # noqa: BLE001
            pass
        tl = imagecheck.table_likeness(gray)
        return {"kind": imagecheck.classify_content(gray), "scale": scale,
                "factor": imagecheck.effective_detail_factor(gray),
                "format": fmt, "jpeg_q": jq, "table_score": tl["score"],
                "hlines": tl["hlines"], "text_bands": tl["text_bands"]}

    # -------------------------------------------------------------- references
    def _after(self, ln, ref):
        """Is line `ln` after line `ref` in reading order?"""
        if ln.page != ref.page:
            return ln.page > ref.page
        cx = self.page_rects[ln.page].width / 2
        col = lambda l: 0 if l.bbox.x1 <= cx + 3 else 1  # noqa: E731
        if ln.page in getattr(self, "two_col_pages", set()):
            if col(ln) != col(ref):
                return col(ln) > col(ref)
        return ln.bbox.y0 >= ref.bbox.y0 - 1

    def check_references(self):
        self.refs_line = None
        for ln in self.lines:
            t = re.sub(r"\s+", "", ln.text).lower()
            if t in ("references", "reference", "bibliography", "referencesandnotes") \
                    or re.fullmatch(r"([ivx]+\.|\d+\.?)(references|bibliography)", t):
                self.refs_line = ln
        if self.refs_line is None:
            self.add(ERROR, "References", "No 'REFERENCES' section heading found.")
            return
        if "bibliography" in self.refs_line.text.lower():
            self.add(INFO, "References", "IEEE uses the heading 'REFERENCES'.",
                     page=self.refs_line.page + 1)
        if re.match(r"^\s*([IVX]+|\d+)\.", self.refs_line.text):
            self.add(INFO, "References", "The REFERENCES heading should not be numbered.",
                     page=self.refs_line.page + 1)
        ref_lines = [ln for ln in self.lines if ln is not self.refs_line and
                     self._after(ln, self.refs_line) and ln.horizontal]
        nums, entries = [], {}
        current = None
        for ln in ref_lines:
            m = re.match(r"^\s*\[(\d{1,3})\]\s*(.*)$", ln.text)
            if m:
                current = int(m.group(1))
                nums.append(current)
                entries.setdefault(current, {"text": m.group(2), "page": ln.page + 1})
            elif current is not None and len(entries[current]["text"]) < 300:
                entries[current]["text"] += " " + ln.text
        if not nums:
            self.add(ERROR, "Citations", "References are not numbered [1], [2], ... "
                     "IEEE uses numbered references in square brackets (not author-year).",
                     page=self.refs_line.page + 1)
            return
        self.res.measurements["References"] = len(set(nums))
        dups = sorted(n for n, c in Counter(nums).items() if c > 1)
        if dups:
            self.add(ERROR, "Citations", "Reference number(s) used twice in the reference "
                     "list: " + ", ".join(f"[{n}]" for n in dups) + ".")
        if nums != list(range(1, len(nums) + 1)) and not dups:
            self.add(WARNING, "Citations", "Reference list numbering is not 1, 2, 3, ... "
                     "in sequence.", detail="Found: " + ", ".join(map(str, nums[:40])))
        sz = Counter()
        for ln in ref_lines:
            sz[ln.size] += len(ln.text)
        rsize = sz.most_common(1)[0][0]
        self.res.measurements["Reference font size"] = f"{rsize:g} pt"
        if rsize > spec.SMALL_TEXT_MAX:
            self.add(WARNING, "References", f"References are set in {rsize:g} pt; the IEEE "
                     f"template uses {spec.REFERENCE_SIZE:g} pt.", page=self.refs_line.page + 1)
        # ---- citations in the text (everything before the REFERENCES heading)
        text, page_at = self._text_with_pages(before=self.refs_line)
        maxref = max(nums)
        cites = defaultdict(list)          # ref number -> [pages]
        order = []
        pat = re.compile(r"\[(\d{1,3})\]\s*[–\-—]\s*\[(\d{1,3})\]"          # [2]–[5]
                         r"|\[(\d{1,3}(?:\s*[,;–\-—]\s*\d{1,3})*)\]")       # [1], [1, 3–5]
        for m in pat.finditer(text):
            if m.group(1):
                a, b = int(m.group(1)), int(m.group(2))
                group = list(range(a, b + 1)) if 0 < b - a < 60 else [a, b]
            else:
                group = sorted(self._expand_nums(m.group(3).replace("—", "-").replace(";", ",")))
            if any(n > maxref + 60 for n in group):
                continue                          # e.g. [2048] or a year - not a citation
            for n in group:
                if n == 0:
                    continue
                if n not in cites:
                    order.append(n)
                cites[n].append(page_at(m.start()))
        uncited = sorted(set(nums) - set(cites))
        missing = sorted(n for n in cites if n not in set(nums) and n <= maxref + 60)
        n_cit = sum(len(v) for v in cites.values())
        self.res.measurements["In-text citations"] = n_cit

        if not cites:
            self.add(ERROR, "Citations", "No in-text citations like [1] were found. Every "
                     "reference must be cited in the text in IEEE style: [1], [2]-[4].")
        if uncited:
            sev = ERROR if spec.UNCITED_REFERENCE_IS_ERROR else WARNING
            self.add(sev, "Citations", f"{len(uncited)} of {len(set(nums))} reference(s) are "
                     "never cited in the text. Every reference must be cited.",
                     page=entries[uncited[0]]["page"] if uncited[0] in entries else None,
                     detail="Not cited: " + "; ".join(
                         f"[{n}] {entries.get(n, {}).get('text', '')[:70]}" for n in uncited[:30]))
        if missing:
            self.add(ERROR, "Citations", "The text cites reference number(s) that are not in "
                     "the reference list: " + ", ".join(f"[{n}] (p. {cites[n][0]})"
                                                       for n in missing) + ".",
                     page=cites[missing[0]][0])
        mx, bad = 0, []
        for n in order:
            if n in set(nums) and n > mx + 1:
                bad.append(n)
            mx = max(mx, n if n in set(nums) else mx)
        if bad:
            self.add(WARNING, "Citations", "References are not numbered in order of first "
                     "citation (IEEE numbers references in the order they are first cited).",
                     detail=f"[{bad[0]}] is cited before some lower-numbered references "
                            f"(first on page {cites[bad[0]][0]}).")
        # author-year style citations are not IEEE style
        ay = re.findall(r"\([A-Z][A-Za-z\-]+(?: et al\.?| and [A-Z][A-Za-z\-]+)?,? "
                        r"(?:19|20)\d{2}[a-z]?\)|[A-Z][a-z]+ et al\. \((?:19|20)\d{2}\)", text)
        if len(ay) >= 2:
            self.add(WARNING, "Citations", f"{len(ay)} author-year citations found (e.g. "
                     f"\"{ay[0]}\"). IEEE uses numbered citations [1].")
        if cites and not uncited and not missing:
            self.add(PASS, "Citations", f"All {len(set(nums))} references are cited in the text "
                     f"({n_cit} citations) and every citation has a reference.")
        for n in sorted(set(nums) | set(missing)):
            pg = sorted(set(cites.get(n, [])))
            self.res.citations.append({
                "ref": n, "times": len(cites.get(n, [])),
                "pages": ", ".join(map(str, pg)) or "-",
                "status": ("MISSING FROM LIST" if n in missing else
                           "NOT CITED" if n not in cites else "cited"),
                "text": entries.get(n, {}).get("text", "")[:110]})

    # --------------------------------------------------------------- leftovers
    def check_leftovers(self):
        found = False
        for pno, page in enumerate(self.doc):
            for phrase in spec.TEMPLATE_LEFTOVERS:
                hits = page.search_for(phrase)
                if hits:
                    found = True
                    sev = ERROR
                    self.add(sev, "Template text", f"Leftover template / error text: "
                             f"\"{phrase}\"", page=pno + 1, rect=rect_t(hits[0]))
            text = page.get_text("text")
            for m in re.finditer(r"(?<!\?)\?\?(?!\?)|\[\?\]|\[\?+\s*,", text):
                hits = page.search_for(m.group(0))
                self.add(ERROR, "Cross references", "Unresolved reference or citation "
                         f"('{m.group(0)}'): run LaTeX/BibTeX again or fix the label.",
                         page=pno + 1, rect=rect_t(hits[0]) if hits else None)
                found = True
                break
        if not found:
            self.add(PASS, "Template text", "No leftover template text or unresolved "
                     "references ('??').")

    # ------------------------------------------------- PDF eXpress / IEEE Xplore
    def check_xplore(self):
        """IEEE PDF eXpress origin + the IEEE Xplore PDF rules that eXpress enforces
        (PDF Specification for IEEE Xplore: fonts embedded & subset, no security,
        no bookmarks, no links, no attachments / portfolios, no JavaScript)."""
        doc = self.doc
        md = doc.metadata or {}
        producer, creator = md.get("producer") or "-", md.get("creator") or "-"
        try:
            xmp = doc.get_xml_metadata() or ""
        except Exception:  # noqa: BLE001
            xmp = ""
        version = md.get("format") or "-"
        self.res.measurements["PDF creator"] = creator[:80]
        self.res.measurements["PDF version"] = version
        comp = self.res.compliance

        def item(rule, ok, found, sev=ERROR, fix=""):
            comp.append({"rule": rule, "ok": ok, "found": found})
            if not ok:
                self.add(sev, "PDF eXpress / Xplore", f"{rule}: {found}", detail=fix)

        # 1. created / converted by IEEE PDF eXpress?
        hay = " ".join([producer, creator, md.get("subject") or "", md.get("keywords") or "",
                        md.get("title") or "", xmp])
        express = re.search(r"pdf\s*-?\s*e?xpress|pdfexpress", hay, re.I)
        if express:
            comp.append({"rule": "Created by IEEE PDF eXpress", "ok": True,
                         "found": f"yes (Producer: {producer})"})
            self.add(PASS, "PDF eXpress / Xplore", "The PDF carries the IEEE PDF eXpress mark.",
                     detail=f"Producer: {producer}; Creator: {creator}")
        elif spec.REQUIRE_PDF_EXPRESS:
            comp.append({"rule": "Created by IEEE PDF eXpress", "ok": False,
                         "found": f"no eXpress mark (Producer: {producer[:50]})"})
            self.add(WARNING, "PDF eXpress / Xplore",
                     "No IEEE PDF eXpress mark found in this PDF. It appears to be made by: "
                     f"{producer[:60]}" + (f" / {creator[:40]}" if creator != "-" else "") + ".",
                     detail="Convert the paper with IEEE PDF eXpress (ieee-pdf-express.org, "
                            "use your conference ID) and submit the PDF it e-mails back. Note: "
                            "eXpress's 'PDF Check' returns your own file unchanged, so a checked "
                            "PDF cannot be recognised from the file itself - keep the eXpress "
                            "approval e-mail as proof.")
        # 2. fonts embedded and subset
        not_sub, t3, not_emb = set(), set(), set()
        for page in doc:
            for xref, ext, ftype, basefont, *_ in page.get_fonts():
                name = clean_font(basefont) or "(unnamed)"
                if ftype == "Type3":
                    t3.add(name)
                elif ext == "n/a":
                    not_emb.add(name)
                elif not re.match(r"^[A-Z]{6}\+", basefont or ""):
                    not_sub.add(name)
        comp.append({"rule": "All fonts embedded", "ok": not not_emb,
                     "found": ", ".join(sorted(not_emb)) or "yes"})   # finding added in Fonts
        item("Fonts subset (not fully embedded)", not not_sub,
             ("not subset: " + ", ".join(sorted(not_sub)[:8])) if not_sub else "yes", WARNING,
             "IEEE Xplore asks for embedded *subset* fonts. Word: File > Options > Save > "
             "'Embed fonts' (untick 'embed all characters'); LaTeX/pdflatex subsets by default.")
        item("No Type 3 (bitmap) fonts", not t3, ", ".join(sorted(t3)[:8]) or "none", ERROR,
             "Usually from matplotlib figures: set matplotlib.rcParams['pdf.fonttype'] = 42 and "
             "re-export the figures; or from old dvips builds - use pdflatex.")
        # 3. security
        sec = bool(doc.is_encrypted or md.get("encryption"))
        item("No password / security settings", not sec,
             md.get("encryption") or "none", ERROR, "Save the PDF again without security.")
        # 4. bookmarks
        try:
            toc = doc.get_toc()
        except Exception:  # noqa: BLE001
            toc = []
        item("No bookmarks", not toc, f"{len(toc)} bookmark(s)" if toc else "none", ERROR,
             "LaTeX: \\usepackage[bookmarks=false]{hyperref} or remove hyperref. Word: "
             "Save as PDF > Options > untick 'Create bookmarks'.")
        # 5. links
        nlinks = sum(len(p.get_links()) for p in doc)
        item("No hyperlinks", nlinks == 0, f"{nlinks} link(s)" if nlinks else "none", WARNING,
             "IEEE Xplore PDFs must not contain links. LaTeX: remove \\usepackage{hyperref} or "
             "use \\usepackage[draft]{hyperref}. Word: Save as PDF without hyperlinks.")
        # 6. attachments / portfolio / JavaScript / forms / comments
        try:
            nemb = doc.embfile_count()
        except Exception:  # noqa: BLE001
            nemb = 0
        item("No file attachments", nemb == 0, f"{nemb} attachment(s)" if nemb else "none")
        try:
            cat = doc.pdf_catalog()
            portfolio = doc.xref_get_key(cat, "Collection")[0] != "null"
            js = (doc.xref_get_key(cat, "Names/JavaScript")[0] != "null" or
                  "JavaScript" in (doc.xref_get_key(cat, "OpenAction")[1] or ""))
        except Exception:  # noqa: BLE001
            portfolio, js = False, False
        item("Not a PDF portfolio / merged package", not portfolio,
             "PDF portfolio" if portfolio else "single PDF")
        item("No JavaScript", not js, "contains JavaScript" if js else "none")
        item("No form fields", not doc.is_form_pdf, "form fields present" if doc.is_form_pdf
             else "none", ERROR, "LaTeX hyperref can create form fields; remove hyperref.")
        ann_pages = []
        for pno, page in enumerate(doc):
            n = sum(1 for a in page.annots() if a.type[1] not in ("Link", "Widget", "Popup"))
            if n:
                ann_pages.append(pno + 1)
        item("No comments / annotations", not ann_pages,
             ("on pages " + ", ".join(map(str, ann_pages))) if ann_pages else "none", ERROR,
             "Delete all comments and markups, then save the PDF again.")
        # 7. PDF version (Xplore accepts up to PDF 1.7 / Acrobat 9)
        mv = re.search(r"(\d+)\.(\d+)", version)
        okv = True
        if mv:
            major, minor = int(mv.group(1)), int(mv.group(2))
            okv = (major, minor) <= (1, 7) and (major, minor) >= (1, 3)
        item("PDF version 1.3-1.7", okv, version, ERROR,
             "Save as PDF 1.4-1.7 (Acrobat 5-9 compatible); PDF 2.0 is not accepted.")
        if all(c["ok"] for c in comp if c["rule"] != "Created by IEEE PDF eXpress"):
            self.add(PASS, "PDF eXpress / Xplore", "PDF meets the IEEE Xplore file rules "
                     "(fonts, security, bookmarks, links, attachments, version).")

    # -------------------------------------------------------------------- misc
    def check_misc(self):
        # figures straddling the column gap with text beside them
        for pno in self.two_col_pages:
            r = self.page_rects[pno]
            cx = r.width / 2
            for info in self.page_images[pno]:
                ib = pymupdf.Rect(info["bbox"])
                if ib.x0 < cx - 8 and ib.x1 > cx + 8 and ib.height > 20:
                    beside = [ln for ln in self.body_lines if ln.page == pno and
                              ln.bbox.y0 < ib.y1 - 2 and ln.bbox.y1 > ib.y0 + 2 and
                              not ib.contains(ln.bbox)]
                    if beside:
                        self.add(ERROR, "Layout", "Figure crosses the column gap while text "
                                 "runs beside it. Use a full-width figure (figure* / section "
                                 "break) or shrink it to one column.", page=pno + 1,
                                 rect=rect_t(ib), thumb=True)
