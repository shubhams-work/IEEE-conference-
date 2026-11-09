"""IEEE conference template specification values.

All lengths are in PDF points (1 pt = 1/72 inch).  The values follow the
official IEEE conference templates (Word "conference-template-letter/a4"
and LaTeX IEEEtran in conference mode).  If a particular conference
publishes different numbers, edit them here.
"""

INCH = 72.0
MM = 72.0 / 25.4

# =============================================================================
#  CONFERENCE PROFILE  -  edit this block to match your conference's author kit
# =============================================================================
CONFERENCE = "COSMIC 2026"      # shown in the app and reports
# "review": double-blind review submission (anonymity checks, no PDF eXpress yet)
# "camera-ready": final paper (author names required, PDF eXpress required)
STAGE = "review"
DOUBLE_BLIND = True             # anonymity checks for the review stage
REQUIRED_PAPER = "a4"           # "a4", "letter", or "auto" (accept either)
MIN_PAGES = 4                   # fewer pages -> warning   (None = no minimum)
MAX_PAGES = 6                   # more pages  -> error     (None = no limit)
# Margins = minimum distance from the paper edge to ANY content, on every page
CONF_MARGINS = {"top": 0.75 * INCH, "bottom": 0.75 * INCH,      # 19 mm
                "left": 0.625 * INCH, "right": 0.625 * INCH}    # 16 mm
COLUMN_GAP = 4.22 * MM          # space between the two columns
COLUMN_GAP_RANGE = (4.0 * MM, 5.8 * MM)   # accepted (covers 4.22 mm and 0.22 in)
REQUIRE_PDF_EXPRESS = True      # paper must carry the "Certified by IEEE PDFeXpress" stamp
UNCITED_REFERENCE_IS_ERROR = True   # every reference must be cited in the text
# =============================================================================

# --- Paper sizes -------------------------------------------------------------
PAPER_SIZES = {
    "letter": (612.0, 792.0),   # 8.5 x 11 in
    "a4": (595.28, 841.89),     # 210 x 297 mm
}
PAPER_SIZE_TOL = 3.0            # pt (~1 mm)

# --- Margins -------------------------------------------------------------------
MARGINS = {"letter": dict(CONF_MARGINS), "a4": dict(CONF_MARGINS)}
# Intrusion beyond the margin that is tolerated silently / reported as warning
MARGIN_TOL_SILENT = 2.0         # pt  (~0.7 mm)
MARGIN_TOL_ERROR = 9.0          # pt  (1/8 in) - more than this = error

# --- Columns -------------------------------------------------------------------
# Expected column width = (paper width - left - right - gap) / 2, computed per paper
COLUMN_WIDTH_TOL = 12.0         # pt (~4 mm)
COLUMN_GAP_MIN, COLUMN_GAP_MAX = COLUMN_GAP_RANGE

# --- Font sizes (pt) -------------------------------------------------------
BODY_SIZE = 10.0
BODY_SIZE_TOL = 0.6
TITLE_SIZE = 24.0
TITLE_SIZE_RANGE = (20.0, 26.5)
ABSTRACT_SIZE = 9.0
CAPTION_SIZE = 8.0
REFERENCE_SIZE = 8.0
SMALL_TEXT_MAX = 9.3            # captions / references should not exceed this

# Font names regarded as "Times" (IEEE requires Times / Times New Roman)
TIMES_FONT_PATTERNS = (
    "times", "nimbusrom", "nimbus roman", "termes", "stix", "txr", "ptmr",
    "utm", "nimbusroman", "tinos", "liberationserif", "liberation serif",
)
# Fonts that are fine anywhere because they are math / symbol fonts
MATH_FONT_PATTERNS = (
    "cmmi", "cmsy", "cmex", "msam", "msbm", "symbol", "mtsy", "mtmi",
    "rsfs", "eufm", "stix", "cambria math", "cambriamath", "txsy", "txmi",
    "txex", "zapf", "dingbat", "wasy", "lasy", "esint", "bbm", "dsrom",
    "mathematica", "euclid", "mt extra", "mtextra", "cmbsy", "cmmib",
    "rtxmi", "ntxmi", "ntxsy", "ntxexx", "lmmono", "lmmath",
    "lmsy", "lmmi", "courier", "cmtt", "inconsolata", "consolas",
)

# --- Abstract --------------------------------------------------------------
ABSTRACT_WORDS = (150, 250)     # IEEE recommends 150-250 words

# --- Images ------------------------------------------------------------------
# IEEE Graphics guidelines: colour / greyscale >= 300 dpi, line art >= 600 dpi
PHOTO_DPI_MIN = 300
PHOTO_DPI_ERROR = 150
LINEART_DPI_MIN = 600
LINEART_DPI_ERROR = 300
IGNORE_IMAGE_BELOW_PT = 18.0    # tiny decorations / logos are not checked
JPEG_QUALITY_MIN = 70

# --- Leftover template text --------------------------------------------------
TEMPLATE_LEFTOVERS = (
    "Identify applicable funding agency here",
    "dept. name of organization",
    "name of organization (of Aff.)",
    "Given Name Surname",
    "email address or ORCID",
    "This document is a model and instructions for",
    "use style: paper title",
    "CRITICAL: Do Not Use Symbols",
    "Please number citations consecutively",
    "IEEE conference templates contain guidance text",
    "Lorem ipsum",
    "This demo file is intended to serve as a",
    "The conclusion goes here",
    "Use either SI (MKS) or CGS",
    "Error! Reference source not found",
    "Error! Bookmark not defined",
)
