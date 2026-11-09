"""Entry points: desktop GUI (default) and command line (when arguments given)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading

from . import __version__, spec
from .analyzer import ERROR, INFO, PASS, WARNING, Analyzer
from .report import write_annotated_pdf, write_html


def output_paths(pdf_path, out_dir=None):
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    folder = out_dir or os.path.dirname(os.path.abspath(pdf_path))
    if not os.access(folder, os.W_OK):
        folder = tempfile.gettempdir()
    return (os.path.join(folder, base + "_IEEE_report.html"),
            os.path.join(folder, base + "_IEEE_annotated.pdf"))


def check_pdf(pdf_path, paper=None, max_pages=-1, out_dir=None, annotate=True,
              progress=None, min_pages=-1, stage=None):
    """paper/max_pages/min_pages/stage default to the conference profile in spec.py."""
    res = Analyzer(pdf_path, paper=paper, max_pages=max_pages, progress=progress,
                   min_pages=min_pages, stage=stage).run()
    html_path, pdf_out = output_paths(pdf_path, out_dir)
    write_html(res, html_path)
    if annotate and not any(f.category == "File" and f.severity == ERROR for f in res.findings):
        try:
            write_annotated_pdf(res, pdf_out, paper=getattr(res, "paper", "letter"))
        except Exception:  # noqa: BLE001
            pdf_out = None
    else:
        pdf_out = None
    return res, html_path, pdf_out


def open_file(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001
        import webbrowser
        webbrowser.open("file://" + os.path.abspath(path))


# ------------------------------------------------------------------------ CLI
def cli(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(prog="ieee-check",
                                description="Offline IEEE conference paper format checker")
    p.add_argument("pdf", nargs="+", help="PDF file(s) to check")
    p.add_argument("--paper", choices=["auto", "letter", "a4"], default=spec.REQUIRED_PAPER,
                   help=f"required paper size (default: {spec.REQUIRED_PAPER})")
    p.add_argument("--min-pages", type=int, default=spec.MIN_PAGES,
                   help=f"minimum pages, 0 = none (default: {spec.MIN_PAGES})")
    p.add_argument("--max-pages", type=int, default=spec.MAX_PAGES,
                   help=f"page limit, 0 = none (default: {spec.MAX_PAGES})")
    p.add_argument("--stage", choices=["review", "camera-ready"], default=spec.STAGE,
                   help="review = double-blind review submission (anonymity checks); "
                        f"camera-ready = final paper (default: {spec.STAGE})")
    p.add_argument("--out", help="folder for the reports (default: next to the PDF)")
    p.add_argument("--no-annotate", action="store_true", help="skip the annotated PDF")
    p.add_argument("--json", action="store_true", help="print findings as JSON")
    p.add_argument("--open", action="store_true", help="open the HTML report when done")
    a = p.parse_args(argv)
    worst = 0
    for pdf in a.pdf:
        if not os.path.isfile(pdf):
            print(f"\n=== {pdf} ===\n[ERROR  ] File not found.")
            worst = 1
            continue
        res, html_path, pdf_out = check_pdf(pdf, a.paper, a.max_pages or None, a.out,
                                            not a.no_annotate, min_pages=a.min_pages or None,
                                            stage=a.stage)
        if a.json:
            print(json.dumps({"file": pdf, "findings": [f.__dict__ for f in res.findings],
                              "measurements": res.measurements, "images": res.images,
                              "tables": res.tables, "citations": res.citations,
                              "crossrefs": res.crossrefs, "compliance": res.compliance},
                             indent=2, default=str))
        else:
            print(f"\n=== {pdf} ===")
            for f in res.findings:
                if f.severity == PASS:
                    continue
                pg = f"p.{f.page}" if f.page else "    "
                print(f"[{f.severity.upper():7}] {pg:5} {f.category}: {f.message}")
                if f.detail:
                    print(f"                {f.detail}")
            print(f"\n{res.count(ERROR)} error(s), {res.count(WARNING)} warning(s), "
                  f"{res.count(PASS)} check(s) passed.")
            print(f"Report:        {html_path}")
            if pdf_out:
                print(f"Annotated PDF: {pdf_out}")
        if a.open:
            open_file(html_path)
        worst = max(worst, 1 if res.count(ERROR) else 0)
    return worst


# ------------------------------------------------------------------------ GUI
def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title(f"IEEE Paper Format Checker {__version__}")
    root.geometry("1120x680")
    root.minsize(760, 480)
    try:  # window / taskbar icon (bundled by the installer build)
        base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "..", "installer"))
        for cand in (os.path.join(base, "assets", "icon_256.png"),):
            if os.path.isfile(cand):
                root.iconphoto(True, tk.PhotoImage(file=cand))
    except Exception:  # noqa: BLE001
        pass
    try:
        ttk.Style().theme_use("clam" if sys.platform.startswith("linux") else ttk.Style().theme_use())
    except Exception:  # noqa: BLE001
        pass

    state = {"html": None, "pdf": None}
    pdf_var = tk.StringVar()
    paper_names = {"a4": "A4", "letter": "US Letter", "auto": "Auto-detect"}
    paper_var = tk.StringVar(value=paper_names.get(spec.REQUIRED_PAPER, "A4"))
    stage_names = {"review": "Review (double-blind)", "camera-ready": "Camera-ready"}
    stage_var = tk.StringVar(value=stage_names.get(spec.STAGE, "Review (double-blind)"))
    minp_var = tk.StringVar(value=str(spec.MIN_PAGES or ""))
    pages_var = tk.StringVar(value=str(spec.MAX_PAGES or ""))
    annot_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="Choose your paper (PDF) and press Check.")

    # header: logo + app name
    head = ttk.Frame(root, padding=(12, 10, 12, 0))
    head.pack(fill="x")
    try:
        base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                    "..", "installer"))
        logo_file = os.path.join(base, "assets", "logo_banner.png")
        if os.path.isfile(logo_file):
            img = tk.PhotoImage(file=logo_file)
            factor = max(1, round(img.height() / 44))      # about 44 px high
            img = img.subsample(factor, factor)
            root._logo_img = img                           # keep a reference
            ttk.Label(head, image=img).pack(side="left", padx=(0, 12))
    except Exception:  # noqa: BLE001
        pass
    titles = ttk.Frame(head)
    titles.pack(side="left")
    ttk.Label(titles, text="IEEE Paper Format Checker",
              font=("TkDefaultFont", 14, "bold")).pack(anchor="w")
    ttk.Label(titles, text=f"{spec.CONFERENCE} rules - version {__version__} - works offline",
              foreground="#666").pack(anchor="w")

    top = ttk.Frame(root, padding=12)
    top.pack(fill="x")
    ttk.Label(top, text="Paper (PDF):").grid(row=0, column=0, sticky="w")
    ent = ttk.Entry(top, textvariable=pdf_var)
    ent.grid(row=0, column=1, sticky="ew", padx=6)

    def browse():
        f = filedialog.askopenfilename(title="Select IEEE paper PDF",
                                       filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if f:
            pdf_var.set(f)
    ttk.Button(top, text="Browse...", command=browse).grid(row=0, column=2)
    top.columnconfigure(1, weight=1)

    opts = ttk.Frame(root, padding=(12, 0))
    opts.pack(fill="x")
    ttk.Label(opts, text="Stage:").pack(side="left")
    ttk.Combobox(opts, textvariable=stage_var, width=20, state="readonly",
                 values=list(stage_names.values())).pack(side="left", padx=(4, 16))
    ttk.Label(opts, text="Paper size:").pack(side="left")
    ttk.Combobox(opts, textvariable=paper_var, width=11, state="readonly",
                 values=["A4", "US Letter", "Auto-detect"]).pack(side="left", padx=(4, 16))
    ttk.Label(opts, text="Pages: min").pack(side="left")
    ttk.Entry(opts, textvariable=minp_var, width=4).pack(side="left", padx=(4, 4))
    ttk.Label(opts, text="max").pack(side="left")
    ttk.Entry(opts, textvariable=pages_var, width=4).pack(side="left", padx=(4, 16))
    ttk.Checkbutton(opts, text="Annotated PDF", variable=annot_var).pack(side="left")
    check_btn = ttk.Button(opts, text="Check paper")
    check_btn.pack(side="right")

    prog = ttk.Progressbar(root, mode="determinate", maximum=100)
    prog.pack(fill="x", padx=12, pady=(10, 2))
    ttk.Label(root, textvariable=status_var, padding=(12, 0)).pack(fill="x")

    mid = ttk.Frame(root, padding=12)
    mid.pack(fill="both", expand=True)
    cols = ("sev", "page", "cat", "msg")
    tree = ttk.Treeview(mid, columns=cols, show="headings")
    for c, t, w in (("sev", "Severity", 80), ("page", "Page", 50), ("cat", "Category", 120),
                    ("msg", "Finding", 680)):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w", stretch=(c == "msg"))
    sb = ttk.Scrollbar(mid, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    tree.tag_configure(ERROR, foreground="#c62828")
    tree.tag_configure(WARNING, foreground="#b26a00")
    tree.tag_configure(INFO, foreground="#1f5fae")
    tree.tag_configure(PASS, foreground="#2e7d32")
    details = {}

    def show_detail(_e=None):
        sel = tree.selection()
        if sel and details.get(sel[0]):
            messagebox.showinfo("Details", details[sel[0]])
    tree.bind("<Double-1>", show_detail)

    bottom = ttk.Frame(root, padding=12)
    bottom.pack(fill="x")
    b_html = ttk.Button(bottom, text="Open full report", state="disabled",
                        command=lambda: open_file(state["html"]))
    b_pdf = ttk.Button(bottom, text="Open annotated PDF", state="disabled",
                       command=lambda: open_file(state["pdf"]))
    b_dir = ttk.Button(bottom, text="Open folder", state="disabled",
                       command=lambda: open_file(os.path.dirname(state["html"])))
    for b in (b_html, b_pdf, b_dir):
        b.pack(side="left", padx=(0, 8))
    ttk.Label(bottom, text="Double-click a row for details. Works fully offline.",
              foreground="#777").pack(side="right")

    def set_progress(frac, msg):
        root.after(0, lambda: (prog.configure(value=frac * 100), status_var.set(msg + "...")))

    def done(res, html_path, pdf_out, err=None):
        check_btn.configure(state="normal")
        if err:
            status_var.set("Failed.")
            messagebox.showerror("Error", str(err))
            return
        tree.delete(*tree.get_children())
        details.clear()
        for f in res.findings:
            iid = tree.insert("", "end", values=(
                {"error": "Error", "warning": "Warning", "info": "Info", "pass": "OK"}[f.severity],
                f.page or "", f.category, f.message), tags=(f.severity,))
            details[iid] = f.message + ("\n\n" + f.detail if f.detail else "")
        state.update(html=html_path, pdf=pdf_out)
        b_html.configure(state="normal")
        b_dir.configure(state="normal")
        b_pdf.configure(state="normal" if pdf_out else "disabled")
        prog.configure(value=100)
        status_var.set(f"{res.count(ERROR)} error(s), {res.count(WARNING)} warning(s), "
                       f"{res.count(PASS)} passed.  Report saved: {html_path}")

    def run_check():
        path = pdf_var.get().strip().strip('"')
        if not path or not os.path.isfile(path):
            messagebox.showwarning("No file", "Please choose a PDF file first.")
            return
        mp = pages_var.get().strip()
        mn = minp_var.get().strip()
        if (mp and not mp.isdigit()) or (mn and not mn.isdigit()):
            messagebox.showwarning("Pages", "Page numbers must be whole numbers "
                                   "(leave empty for no limit).")
            return
        paper = {"Auto-detect": "auto", "US Letter": "letter", "A4": "a4"}[paper_var.get()]
        stage = {v: k for k, v in stage_names.items()}[stage_var.get()]
        check_btn.configure(state="disabled")
        prog.configure(value=0)

        def work():
            try:
                res, h, p = check_pdf(path, paper, int(mp) if mp else None, None,
                                      annot_var.get(), progress=set_progress,
                                      min_pages=int(mn) if mn else None, stage=stage)
                root.after(0, lambda: done(res, h, p))
            except Exception as e:  # noqa: BLE001
                root.after(0, lambda: done(None, None, None, e))
        threading.Thread(target=work, daemon=True).start()

    check_btn.configure(command=run_check)
    if len(sys.argv) == 2 and sys.argv[1].lower().endswith(".pdf"):
        pdf_var.set(sys.argv[1])      # opened via right-click / "Open with" / drop on icon
        root.after(400, run_check)    # start checking straight away
    root.mainloop()


def main():
    args = sys.argv[1:]
    # A single PDF path (e.g. drag-and-drop onto the icon) opens the GUI pre-filled.
    if args and not (len(args) == 1 and args[0].lower().endswith(".pdf")
                     and getattr(sys, "frozen", False)):
        sys.exit(cli(args))
    gui()


if __name__ == "__main__":
    main()
