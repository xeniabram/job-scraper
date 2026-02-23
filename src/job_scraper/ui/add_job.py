"""Minimal Tkinter form to manually add jobs to the filter queue."""

import tkinter as tk
from tkinter import scrolledtext

from job_scraper.config import settings
from job_scraper.schema import JobData
from job_scraper.storage import ResultsStorage


def run_add_job() -> None:
    results = ResultsStorage(settings.data_dir)
    added_this_session = {"count": 0}

    root = tk.Tk()
    root.title("Add Job Manually")
    root.geometry("580x540")
    root.resizable(True, True)

    pad = {"padx": 14, "pady": (6, 0)}

    def _label(text: str) -> None:
        tk.Label(root, text=text, font=("Helvetica", 10, "bold"), fg="gray", anchor="w").pack(
            fill="x", **pad
        )

    # URL
    _label("JOB URL *")
    url_var = tk.StringVar()
    url_entry = tk.Entry(root, textvariable=url_var, font=("Helvetica", 11), relief="flat", bg="#f7f7f7")
    url_entry.pack(fill="x", padx=14)

    # Title
    _label("TITLE *")
    title_var = tk.StringVar()
    tk.Entry(root, textvariable=title_var, font=("Helvetica", 11), relief="flat", bg="#f7f7f7").pack(
        fill="x", padx=14
    )

    # Company
    _label("COMPANY *")
    company_var = tk.StringVar()
    tk.Entry(root, textvariable=company_var, font=("Helvetica", 11), relief="flat", bg="#f7f7f7").pack(
        fill="x", padx=14
    )

    # Description
    _label("DESCRIPTION (paste full job posting)")
    desc_box = scrolledtext.ScrolledText(
        root, wrap=tk.WORD, height=12, font=("Helvetica", 11), relief="flat", bg="#f7f7f7"
    )
    desc_box.pack(fill="both", expand=True, padx=14, pady=(6, 0))

    # Error / status
    status_var = tk.StringVar()
    status_label = tk.Label(root, textvariable=status_var, font=("Helvetica", 10), anchor="w")
    status_label.pack(fill="x", padx=14, pady=(4, 0))

    # Buttons
    btn_frame = tk.Frame(root)
    btn_frame.pack(pady=12)

    def _clear_form() -> None:
        url_var.set("")
        title_var.set("")
        company_var.set("")
        desc_box.delete("1.0", tk.END)
        url_entry.focus()

    def on_add() -> None:
        url = url_var.get().strip()
        title = title_var.get().strip()
        company = company_var.get().strip()
        description_text = desc_box.get("1.0", tk.END).strip()

        if not url or not title or not company:
            status_var.set("URL, title and company are required.")
            status_label.config(fg="#cc0000")
            return

        job = JobData(
            url=url,
            title=title,
            company=company,
            description={"raw": description_text} if description_text else {},
        )

        if url in results.url_cache:
            status_var.set(f"Already in queue: {url}")
            status_label.config(fg="#cc6600")
            return

        results.save_job(job)
        added_this_session["count"] += 1
        n = added_this_session["count"]
        status_var.set(f"Added! ({n} added this session)  —  run 'filter' to process.")
        status_label.config(fg="#2a7a2a")
        _clear_form()

    tk.Button(
        btn_frame,
        text="Add to Queue",
        font=("Helvetica", 13, "bold"),
        bg="#2a7a2a",
        fg="white",
        activebackground="#1d5c1d",
        activeforeground="white",
        relief="flat",
        padx=20,
        pady=8,
        command=on_add,
    ).pack(side="left", padx=(0, 12))

    tk.Button(
        btn_frame,
        text="Close",
        font=("Helvetica", 13),
        relief="flat",
        bg="#e0e0e0",
        activebackground="#c8c8c8",
        padx=20,
        pady=8,
        command=root.destroy,
    ).pack(side="left")

    url_entry.focus()
    root.mainloop()
