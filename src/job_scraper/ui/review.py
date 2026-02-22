"""Simple tkinter UI for reviewing and marking matched jobs as applied."""

import tkinter as tk
import webbrowser
from tkinter import scrolledtext

from job_scraper.config import settings
from job_scraper.storage import ResultsStorage


def run_review() -> None:
    results = ResultsStorage(settings.data_dir)
    jobs = results.load_unapplied_matched()

    if not jobs:
        print("No unapplied matched jobs to review.")
        return

    total = len(jobs)
    state = {"index": 0}

    # ------------------------------------------------------------------
    # Build window
    # ------------------------------------------------------------------
    root = tk.Tk()
    root.title("Job Review")
    root.geometry("860x780")
    root.resizable(True, True)

    # -- counter
    counter_var = tk.StringVar()
    tk.Label(root, textvariable=counter_var, font=("Helvetica", 11), fg="gray").pack(anchor="ne", padx=12, pady=(8, 0))

    # -- title / company
    title_var = tk.StringVar()
    tk.Label(root, textvariable=title_var, font=("Helvetica", 15, "bold"), wraplength=820, justify="left").pack(anchor="w", padx=12, pady=(4, 0))

    # -- clickable URL
    url_label = tk.Label(root, text="", font=("Helvetica", 11), fg="#0066cc", cursor="hand2", wraplength=820, justify="left")
    url_label.pack(anchor="w", padx=12, pady=(2, 0))

    # -- match %
    match_var = tk.StringVar()
    tk.Label(root, textvariable=match_var, font=("Helvetica", 11), fg="#2a7a2a").pack(anchor="w", padx=12, pady=(2, 8))

    tk.Frame(root, height=1, bg="#cccccc").pack(fill="x", padx=12)

    # -- about me
    about_header = tk.Frame(root)
    about_header.pack(fill="x", padx=12, pady=(8, 2))
    tk.Label(about_header, text="ABOUT ME", font=("Helvetica", 10, "bold"), fg="gray").pack(side="left")

    def copy_about() -> None:
        text = about_box.get("1.0", tk.END).strip()
        root.clipboard_clear()
        root.clipboard_append(text)

    tk.Button(about_header, text="Copy", font=("Helvetica", 9), relief="flat", bg="#e0e0e0",
              activebackground="#c8c8c8", padx=6, pady=1, command=copy_about).pack(side="left", padx=(8, 0))

    about_box = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=9, font=("Helvetica", 11), relief="flat", bg="#f7f7f7")
    about_box.pack(fill="x", padx=12)

    # -- keywords
    kw_header = tk.Frame(root)
    kw_header.pack(fill="x", padx=12, pady=(10, 2))
    tk.Label(kw_header, text="KEYWORDS", font=("Helvetica", 10, "bold"), fg="gray").pack(side="left")

    def copy_keywords() -> None:
        text = kw_box.get("1.0", tk.END).strip()
        root.clipboard_clear()
        root.clipboard_append(text)

    tk.Button(kw_header, text="Copy", font=("Helvetica", 9), relief="flat", bg="#e0e0e0",
              activebackground="#c8c8c8", padx=6, pady=1, command=copy_keywords).pack(side="left", padx=(8, 0))

    kw_box = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=5, font=("Helvetica", 11), relief="flat", bg="#f7f7f7")
    kw_box.pack(fill="x", padx=12)

    tk.Frame(root, height=1, bg="#cccccc").pack(fill="x", padx=12, pady=(10, 0))

    # -- rejection reason
    tk.Label(root, text="REJECTION REASON", font=("Helvetica", 10, "bold"), fg="gray").pack(anchor="w", padx=12, pady=(8, 2))
    reason_entry = tk.Entry(root, font=("Helvetica", 11), relief="flat", bg="#f7f7f7")
    reason_entry.pack(fill="x", padx=12)

    reason_error_var = tk.StringVar()
    tk.Label(root, textvariable=reason_error_var, font=("Helvetica", 10), fg="#cc0000").pack(anchor="w", padx=12)

    # -- buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)

    def _advance() -> None:
        state["index"] += 1
        if state["index"] >= total:
            root.destroy()
        else:
            _load(state["index"])

    def on_applied() -> None:
        job = jobs[state["index"]]
        results.mark_applied(job["url"])
        reason_error_var.set("")
        _advance()

    def on_reject() -> None:
        reason = reason_entry.get().strip()
        if not reason:
            reason_error_var.set("Reason is required to reject.")
            return
        reason_error_var.set("")
        job = jobs[state["index"]]
        results.reject_manually(job["url"], reason)
        reason_entry.delete(0, tk.END)
        _advance()

    tk.Button(
        btn_frame, text="Applied ✓", font=("Helvetica", 13, "bold"),
        bg="#2a7a2a", fg="white", activebackground="#1d5c1d", activeforeground="white",
        relief="flat", padx=20, pady=8, command=on_applied,
    ).pack(side="left", padx=(0, 16))

    tk.Button(
        btn_frame, text="Reject ✗", font=("Helvetica", 13, "bold"),
        bg="#8b0000", fg="white", activebackground="#5c0000", activeforeground="white",
        relief="flat", padx=20, pady=8, command=on_reject,
    ).pack(side="left")

    # ------------------------------------------------------------------
    # Load job into widgets
    # ------------------------------------------------------------------
    def _load(i: int) -> None:
        job = jobs[i]
        counter_var.set(f"{i + 1} / {total}")
        title_var.set(f"{job.get('title') or '—'}  •  {job.get('company') or '—'}")
        match_var.set(f"Skillset match: {job.get('skillset_match_percent', 0)}%")

        url = job.get("url", "")
        url_label.config(text=url)
        url_label.bind("<Button-1>", lambda _: webbrowser.open(url))

        about_box.config(state="normal")
        about_box.delete("1.0", tk.END)
        about_box.insert(tk.END, job.get("cv_about_me") or "(no CV section)")
        about_box.config(state="disabled")

        kw_box.config(state="normal")
        kw_box.delete("1.0", tk.END)
        kw_box.insert(tk.END, job.get("cv_keywords") or "(no keywords)")
        kw_box.config(state="disabled")

        reason_entry.delete(0, tk.END)
        reason_error_var.set("")

    _load(0)
    root.mainloop()
