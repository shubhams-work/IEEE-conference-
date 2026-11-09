"""Raster image analysis: resolution, upscaling/blur, JPEG quality and
"is this picture actually a table / screenshot of text?" heuristics."""

from __future__ import annotations

import io
import math

import numpy as np
from PIL import Image

import pymupdf

from . import spec


def pixmap_to_gray(doc: pymupdf.Document, xref: int, max_side: int = 1600):
    """Return (gray uint8 numpy array, original (w, h)) for an image xref."""
    pix = pymupdf.Pixmap(doc, xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)            # drop alpha
    if pix.n not in (1, 3):                     # CMYK, Lab, indexed ...
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    mode = "L" if pix.n == 1 else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    img = img.convert("L")
    scale = 1.0
    if max(img.size) > max_side:
        scale = max_side / max(img.size)
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))), Image.BOX)
    return np.asarray(img, dtype=np.uint8), scale


def classify_content(gray: np.ndarray) -> str:
    """'lineart' for diagrams / charts / text (mostly flat white + dark),
    'photo' for continuous-tone images."""
    if gray.size == 0:
        return "photo"
    near_white = np.mean(gray > 235)
    near_black = np.mean(gray < 40)
    hist = np.bincount(gray.ravel(), minlength=256) / gray.size
    top_levels = np.sort(hist)[::-1][:8].sum()  # mass in the 8 commonest levels
    if near_white > 0.55 and (near_white + near_black > 0.75 or top_levels > 0.8):
        return "lineart"
    return "photo"


def effective_detail_factor(gray: np.ndarray) -> int:
    """Detect upscaled or blurred images.

    Downscale by f and scale back up; if the result is (almost) identical to
    the original in the non-flat regions, the image carries no real detail at
    full resolution.  Returns the largest such f (1 = image is sharp)."""
    h, w = gray.shape
    if min(h, w) < 120:
        return 1
    img = Image.fromarray(gray)
    a = gray.astype(np.float32)
    # mask of non-flat pixels (edges / texture)
    gx = np.abs(np.diff(a, axis=1, prepend=a[:, :1]))
    gy = np.abs(np.diff(a, axis=0, prepend=a[:1, :]))
    mask = (gx + gy) > 6
    if mask.mean() < 0.005:
        return 1
    best = 1
    for f in (2, 3, 4, 6, 8):
        if min(h, w) // f < 40:
            break
        small = img.resize((w // f, h // f), Image.LANCZOS)
        back = np.asarray(small.resize((w, h), Image.LANCZOS), dtype=np.float32)
        mse = float(np.mean((a[mask] - back[mask]) ** 2))
        psnr = 99.0 if mse < 1e-6 else 10 * math.log10(255.0 ** 2 / mse)
        # sharp images score ~5-15 dB, noisy photos ~25-31 dB, upscaled/blurred > 34 dB
        if psnr >= 34.0:
            best = f
        else:
            break
    return best


def jpeg_quality(raw: bytes) -> int | None:
    """Estimate the JPEG quality (1-100) from its luminance quantisation table."""
    try:
        im = Image.open(io.BytesIO(raw))
        q = getattr(im, "quantization", None)
        if not q:
            return None
        table = q.get(0)
        if not table:
            return None
        # Standard IJG luminance table (zig-zag order not required for mean)
        std = [16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55,
               14, 13, 16, 24, 40, 57, 69, 56, 14, 17, 22, 29, 51, 87, 80, 62,
               18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113, 92,
               49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99]
        scale = 100.0 * sum(table) / sum(std)
        if scale <= 0:
            return 100
        quality = (200 - scale) / 2 if scale <= 100 else 5000 / scale
        return int(max(1, min(100, round(quality))))
    except Exception:
        return None


def _runs(bool_arr: np.ndarray):
    """Return list of (start, length) runs of True values."""
    runs = []
    start = None
    for i, v in enumerate(bool_arr):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - start))
            start = None
    if start is not None:
        runs.append((start, len(bool_arr) - start))
    return runs


def table_likeness(gray: np.ndarray) -> dict:
    """Heuristic detection of a table (or text) pasted as a picture.

    Tables rendered to an image show: a mostly white background, several long
    horizontal rules, and many separate horizontal bands of text."""
    h, w = gray.shape
    res = {"score": 0.0, "hlines": 0, "vlines": 0, "text_bands": 0}
    if h < 40 or w < 60:
        return res
    dark = gray < 140
    whiteness = float(np.mean(gray > 200))
    row_frac = dark.mean(axis=1)
    col_frac = dark.mean(axis=0)
    hline_rows = row_frac > 0.55
    vline_cols = col_frac > 0.55
    hlines = len(_runs(hline_rows))
    vlines = len(_runs(vline_cols))

    # text bands: rows with some ink, not being a rule, separated by white rows
    ink_rows = (row_frac > 0.004) & ~hline_rows
    bands = [r for r in _runs(ink_rows) if r[1] >= 3]
    band_heights = [b[1] for b in bands]
    small_bands = [b for b in band_heights if b < 0.12 * h]
    text_bands = len(small_bands)
    regular = False
    if len(small_bands) >= 4:
        hb = np.array(small_bands, dtype=float)
        regular = hb.std() / max(hb.mean(), 1) < 0.6

    # within text bands, ink should be broken into many glyph-like pieces
    score = 0.0
    if whiteness > 0.6:
        if hlines >= 2:
            score += 0.35
        if hlines >= 3:
            score += 0.15
        if vlines >= 2:
            score += 0.15
        if text_bands >= 4:
            score += 0.2
        if regular:
            score += 0.15
        if text_bands >= 8 and regular:
            score += 0.1
        # A single dominating band = a plot curve, not text rows
        if band_heights and max(band_heights) > 0.5 * h:
            score -= 0.4
    res.update(score=round(max(0.0, min(score, 1.0)), 2), hlines=hlines,
               vlines=vlines, text_bands=text_bands, whiteness=round(whiteness, 2))
    return res
