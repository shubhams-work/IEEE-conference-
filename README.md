# IEEE Paper Format Checker (offline)

Checks an IEEE **conference** paper (PDF) for formatting problems, works fully
offline, and runs on **Windows, macOS and Linux**.

Pick a PDF, press **Check paper**, and you get:

* a list of problems in the window (red = error, orange = warning),
* a full **HTML report** with pictures of every problem region,
* an **annotated copy of the PDF** with coloured boxes and notes on each problem
  and a dashed blue outline of the IEEE text area.

Your paper never leaves the computer.

## Installing

### Option A: installer (recommended, no Python needed)

Each installer contains everything, including its own copy of Python, so the
computer needs nothing else.

| System  | Installer | How to install |
|---------|-----------|----------------|
| Windows 10/11 | `IEEE-Paper-Checker-Setup-1.2.0.exe` | Double-click and follow the wizard. No admin rights needed (you can choose "all users"). Adds Start Menu and desktop shortcuts, a **"Check IEEE format"** entry when you right-click a PDF, and an uninstaller in *Settings → Apps*. If SmartScreen appears: *More info → Run anyway*. |
| macOS   | `IEEE-Paper-Checker-1.2.0-macOS-arm64.dmg` (Apple silicon M1–M4) or `...-x86_64.dmg` (Intel) | Open the .dmg and drag the app onto *Applications*. The app is unsigned, so the first start is blocked: open it once, then go to *System Settings → Privacy & Security* and click **Open Anyway** (on macOS 14 and older you can instead right-click the app → *Open*). Alternative in Terminal: `xattr -dr com.apple.quarantine /Applications/IEEE-Paper-Checker.app`. Uninstall: drag it to the Bin. |
| Ubuntu / Debian / Mint | `ieee-paper-checker_1.2.0_amd64.deb` | Double-click (Software Center) or `sudo apt install ./ieee-paper-checker_1.2.0_amd64.deb`. Uninstall: `sudo apt remove ieee-paper-checker`. |
| Other Linux | `IEEE-Paper-Checker-1.2.0-linux-x64.tar.gz` | Unpack, then run `./install.sh` (no sudo). Uninstall: `./install.sh --uninstall`. |

After installing, open **IEEE Paper Format Checker** from the Start Menu,
Launchpad or applications menu, or right-click a PDF and choose it.

#### Making the installers

* **Automatically on GitHub (all systems at once).** Push this folder to a GitHub
  repository, open *Actions → Build installers → Run workflow*, and download the
  installers from the finished run. Pushing a tag such as `v1.2.0` also publishes
  them as a Release.
* **On your own computer.** A computer can only build its own system's installer:
  * Windows: install Python and [Inno Setup](https://jrsoftware.org/isdl.php) (version 6 or 7), then run `build_windows.bat`
  * macOS: `./build_mac.sh`
  * Linux: `sudo apt install python3-venv python3-tk binutils`, then `./build_linux.sh`

  The installers are written to `dist/`.

### Option B: run from source (needs Python 3.9+)

Double-click `run_windows.bat` (Windows) or `run_mac.command` (macOS), or run
`./run_linux.sh` (Linux). The first run installs three libraries (PyMuPDF,
NumPy, Pillow) and needs internet once. After that it works offline.

On Linux, Tkinter must be installed first: `sudo apt install python3-tk python3-venv`.
On macOS, use the Python installer from python.org, which includes Tkinter.

## Command line

```
ieee-check paper.pdf                          # Windows: ieee-check.exe, or: python ieee_format_checker.py paper.pdf
ieee-check paper.pdf --min-pages 4 --max-pages 6
ieee-check paper.pdf --paper letter           # override the required paper size
ieee-check *.pdf --out reports/ --json        # batch mode, JSON output
```

The exit code is 1 if any error is found, so the command can be used in scripts and CI.

## Conference rules checked (default profile)

| Rule | Requirement | Severity if broken |
|------|-------------|--------------------|
| **Paper size** | A4 (210 x 297 mm) on **every page** | Error |
| **Margins** | Top and bottom 0.75 in (19 mm); left and right 0.625 in (16 mm), on every page | Error (> 3 mm) / Warning |
| **Columns** | Two columns, 4.22 mm between them (4.0-5.8 mm accepted) | Error / Warning |
| **Page count** | 4-6 pages (editable in the app) | Error above max, Warning below min |
| **Citations** | Every reference in the list is cited in the text as [n]; every [n] exists in the list; no duplicate numbers; numbered in order of first citation; no author-year citations | Error (order: Warning) |
| **In-text references** | Every figure and table is referred to in the text; no references to figures, tables, equations or sections that do not exist (e.g. "Fig. 7" when there are 5 figures) | Error |
| **IEEE PDF eXpress** | Whether the PDF carries the IEEE PDF eXpress mark | Warning (see note) |
| **IEEE Xplore file rules** (what PDF eXpress checks) | All fonts embedded and subset, no Type 3 fonts, no password/security, no bookmarks, no hyperlinks, no attachments, not a portfolio, no JavaScript, no form fields, no comments, PDF version 1.3-1.7 | Error (links/subsetting: Warning) |

**About the PDF eXpress check:** a PDF that IEEE PDF eXpress *converted* from
your source files can be recognised. eXpress's *PDF Check* function returns your
own file unchanged, so such a file cannot be told apart from the file itself.
Keep the eXpress approval e-mail. The checker still verifies every Xplore rule
that eXpress tests.

## Other checks

| Area | Checks |
|------|--------|
| **Tables** | Every `TABLE I, II, ...` is a **real drawn table (text + rules), not a pasted image**. Pictures that *look like* a table or a text screenshot are flagged even without a caption. Table captions use upper-case Roman numerals and sit above the table. |
| **Image quality** | Resolution at printed size: photos ≥ 300 dpi, line art/diagrams ≥ 600 dpi (IEEE graphics guidelines). **Upscaled or blurry images**. Diagrams saved as JPEG. Heavy JPEG compression. Images crossing the column gap or overlapping text. The report lists every image with its dpi. |
| **Header/footer** | No page numbers, headers, footers or arXiv stamps. The IEEE copyright line on page 1 is allowed. |
| **Layout** | Column width, last-page column balance, single-column pages. |
| **Fonts** | Times / Times New Roman body text, 10 pt body, 24 pt title, 9 pt abstract, 8 pt captions and references. |
| **Front matter** | Title size and case, `Abstract—` present and 150–250 words with no citations, Index Terms / Keywords present. |
| **Headings** | Roman-numeral section numbering (I. INTRODUCTION) in sequence; "Acknowledgment" spelling. |
| **Figures** | `Fig. N.` caption style, sequential numbering, caption below the figure. |
| **Leftovers** | Template placeholder text ("Paper Title (use style: paper title)", "dept. name of organization", ...), unresolved LaTeX `??` / `[?]`, Word "Error! Reference source not found". |

The **annotated PDF** starts with summary pages (verdict, numbered list of every
problem with how to fix it, citation table, PDF eXpress checklist, measured
margins, images, tables). Every paper page then gets a **notes panel on the
right**: each problem is highlighted or framed at its exact location (the
uncited reference, the wrong citation [8], the "Fig. 5" that does not exist, the
strip of text inside the margin, ...) and connected by a line to its numbered
note. The panel also shows the page's required vs measured margins, the dpi of
every image and whether every table is real. Viewer page numbers still match
the paper's page numbers.

The HTML report contains a **citation table** (each reference, how often and on
which pages it is cited), an **in-text reference table** for figures, tables
and equations, and an **IEEE PDF eXpress / Xplore checklist**.

## Adjusting for another conference

The rules are in the **CONFERENCE PROFILE** block at the top of
`ieee_checker/spec.py`: required paper size, page range, margins, column gap,
whether uncited references are errors, and the PDF eXpress check. Edit the
values there and rebuild the installer. Paper size and page range can also be
changed in the app window for a single check.

Note: the standard IEEEtran LaTeX class with `a4paper` uses about 14.3 mm side
margins, which is narrower than 16 mm. To meet the default profile, add
`\usepackage[a4paper,top=0.75in,bottom=0.75in,left=0.625in,right=0.625in,columnsep=4.22mm]{geometry}`.

## Limits

These are automatic checks based on what can be measured in the PDF. They
complement, and do not replace, the conference's own author instructions and
IEEE PDF eXpress. Table and figure detection uses heuristics, so if something
looks wrong, check the highlighted region in the annotated PDF.
