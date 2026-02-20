"""Tkinter UI for reviewing LLM-rejected jobs and labeling them for LLM tuning.

Layout: split pane — scrollable list of unreviewed rejected jobs on the left,
detail panel with action buttons on the right. Reviewed jobs are saved to the
`learn` table and immediately disappear from the list.
"""

import tkinter as tk
import webbrowser
from tkinter import scrolledtext
from typing import Any

from job_scraper.config import settings
from job_scraper.storage import ResultsStorage


def run_rejected_review() -> None:
    results = ResultsStorage(settings.data_dir)
    all_jobs: list[dict[str, Any]] = results.load_unreviewed_rejected()

    if not all_jobs:
        print("No unreviewed rejected jobs to review.")
        return

    # mutable working lists (filtered by search box)
    filtered_jobs: list[dict[str, Any]] = list(all_jobs)
    selected_job: dict[str, Any] | None = None
    scraped_cache: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Window
    # ------------------------------------------------------------------
    root = tk.Tk()
    root.title("Rejected Jobs Review")
    root.geometry("1200x720")
    root.resizable(True, True)

    main_frame = tk.Frame(root)
    main_frame.pack(fill="both", expand=True)

    # ------------------------------------------------------------------
    # LEFT panel — job list
    # ------------------------------------------------------------------
    left_frame = tk.Frame(main_frame, width=360, bg="#f0f0f0")
    left_frame.pack(side="left", fill="y")
    left_frame.pack_propagate(False)

    tk.Frame(main_frame, width=1, bg="#cccccc").pack(side="left", fill="y")

    counter_var = tk.StringVar()
    tk.Label(
        left_frame, textvariable=counter_var,
        font=("Helvetica", 10), fg="gray", bg="#f0f0f0",
    ).pack(anchor="w", padx=10, pady=(10, 2))

    search_var = tk.StringVar()
    tk.Entry(
        left_frame, textvariable=search_var,
        font=("Helvetica", 11), relief="flat", bg="white",
    ).pack(fill="x", padx=10, pady=(0, 6))

    list_frame = tk.Frame(left_frame, bg="#f0f0f0")
    list_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    scrollbar = tk.Scrollbar(list_frame)
    scrollbar.pack(side="right", fill="y")

    listbox = tk.Listbox(
        list_frame,
        yscrollcommand=scrollbar.set,
        font=("Helvetica", 10),
        selectmode="single",
        relief="flat",
        bg="white",
        activestyle="none",
        selectbackground="#0066cc",
        selectforeground="white",
        bd=0,
    )
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=listbox.yview)

    # ------------------------------------------------------------------
    # RIGHT panel — detail view
    # ------------------------------------------------------------------
    right_frame = tk.Frame(main_frame)
    right_frame.pack(side="left", fill="both", expand=True)

    placeholder = tk.Label(
        right_frame,
        text="← Select a job to review",
        font=("Helvetica", 14), fg="#999999",
    )
    placeholder.pack(expand=True)

    detail_frame = tk.Frame(right_frame)

    title_var = tk.StringVar()
    tk.Label(
        detail_frame, textvariable=title_var,
        font=("Helvetica", 14, "bold"), wraplength=800, justify="left",
    ).pack(anchor="w", padx=16, pady=(14, 0))

    url_label = tk.Label(
        detail_frame, text="",
        font=("Helvetica", 11), fg="#0066cc", cursor="hand2",
        wraplength=800, justify="left",
    )
    url_label.pack(anchor="w", padx=16, pady=(2, 0))

    meta_var = tk.StringVar()
    tk.Label(
        detail_frame, textvariable=meta_var,
        font=("Helvetica", 10), fg="gray",
    ).pack(anchor="w", padx=16, pady=(2, 8))

    tk.Frame(detail_frame, height=1, bg="#cccccc").pack(fill="x", padx=16)

    tk.Label(
        detail_frame, text="TECHNOLOGIES",
        font=("Helvetica", 10, "bold"), fg="gray",
    ).pack(anchor="w", padx=16, pady=(8, 2))
    tech_var = tk.StringVar()
    tk.Label(
        detail_frame, textvariable=tech_var,
        font=("Helvetica", 11), wraplength=800, justify="left",
    ).pack(anchor="w", padx=16)

    tk.Frame(detail_frame, height=1, bg="#cccccc").pack(fill="x", padx=16, pady=(8, 0))

    tk.Label(
        detail_frame, text="REJECTION REASON  (LLM)",
        font=("Helvetica", 10, "bold"), fg="gray",
    ).pack(anchor="w", padx=16, pady=(8, 2))
    reason_box = scrolledtext.ScrolledText(
        detail_frame, wrap=tk.WORD, height=4,
        font=("Helvetica", 11), relief="flat", bg="#f0f0f0", state="disabled",
    )
    reason_box.pack(fill="x", padx=16)

    tk.Frame(detail_frame, height=1, bg="#cccccc").pack(fill="x", padx=16, pady=(8, 0))

    tk.Label(
        detail_frame, text="YOUR NOTE  (why LLM was wrong)",
        font=("Helvetica", 10, "bold"), fg="gray",
    ).pack(anchor="w", padx=16, pady=(8, 2))
    user_note_box = scrolledtext.ScrolledText(
        detail_frame, wrap=tk.WORD, height=3,
        font=("Helvetica", 11), relief="flat", bg="white",
    )
    user_note_box.pack(fill="x", padx=16)

    error_var = tk.StringVar()
    tk.Label(
        detail_frame, textvariable=error_var,
        font=("Helvetica", 10), fg="#cc0000",
    ).pack(anchor="w", padx=16)

    btn_frame = tk.Frame(detail_frame)
    btn_frame.pack(pady=14)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _update_counter() -> None:
        total = len(all_jobs)
        shown = len(filtered_jobs)
        counter_var.set(f"{shown} unreviewed  (of {total} total)")

    def _populate_list() -> None:
        listbox.delete(0, tk.END)
        for job in filtered_jobs:
            role = job.get("role") or "—"
            date = (job.get("rejected_at") or "")[:10]
            listbox.insert(tk.END, f"  {role}   {date}")
        _update_counter()

    def _on_search(*_: Any) -> None:
        nonlocal filtered_jobs
        query = search_var.get().strip().lower()
        filtered_jobs = (
            [j for j in all_jobs if query in (j.get("role") or "").lower()]
            if query else list(all_jobs)
        )
        _populate_list()
        _clear_detail()

    def _clear_detail() -> None:
        nonlocal selected_job
        selected_job = None
        detail_frame.pack_forget()
        placeholder.pack(expand=True)

    def _load_detail(job: dict[str, Any]) -> None:
        nonlocal selected_job
        selected_job = job

        url = job.get("url", "")

        # fetch scraped details once per URL
        if url not in scraped_cache:
            scraped_cache[url] = results.get_scraped_details(url)
        scraped = scraped_cache[url]

        role = job.get("role") or "—"
        company = scraped.get("company") or ""
        header = f"{role}  •  {company}" if company else role
        title_var.set(header)

        url_label.config(text=url)
        url_label.bind("<Button-1>", lambda _e: webbrowser.open(url))

        pct = job.get("skillset_match_percent", 0)
        rejected_at = (job.get("rejected_at") or "")[:10]
        meta_var.set(f"Skillset match: {pct}%   |   Rejected: {rejected_at}")

        techs: list[str] = scraped.get("technologies", [])
        optional: list[str] = scraped.get("technologies_optional", [])
        tech_parts = techs + [f"{t} (optional)" for t in optional]
        tech_var.set(", ".join(tech_parts) if tech_parts else "(no technology data)")

        reason_box.config(state="normal")
        reason_box.delete("1.0", tk.END)
        reason_box.insert(tk.END, job.get("reason") or "")
        reason_box.config(state="disabled")

        user_note_box.delete("1.0", tk.END)
        error_var.set("")

        placeholder.pack_forget()
        detail_frame.pack(fill="both", expand=True)

    def _on_select(_event: Any) -> None:
        sel = listbox.curselection()
        if sel and sel[0] < len(filtered_jobs):
            _load_detail(filtered_jobs[sel[0]])

    def _remove_selected() -> None:
        nonlocal all_jobs, filtered_jobs
        if selected_job is None:
            return
        url = selected_job["url"]
        all_jobs = [j for j in all_jobs if j["url"] != url]
        filtered_jobs = [j for j in filtered_jobs if j["url"] != url]
        _populate_list()
        _clear_detail()

    # ------------------------------------------------------------------
    # Button actions
    # ------------------------------------------------------------------
    def on_approve_rejection() -> None:
        if selected_job is None:
            return
        reason = reason_box.get("1.0", tk.END).strip()
        if not reason:
            error_var.set("Reason is required to approve the rejection.")
            return
        error_var.set("")
        scraped = scraped_cache.get(selected_job["url"], {})
        results.save_to_learn(
            url=selected_job["url"],
            title=selected_job.get("role") or "",
            company=scraped.get("company") or "",
            reason=reason,
            correct_label="rejected",
            skillset_match_percent=selected_job.get("skillset_match_percent", 0),
        )
        _remove_selected()

    def on_rejected_incorrectly() -> None:
        if selected_job is None:
            return
        user_note = user_note_box.get("1.0", tk.END).strip()
        if not user_note:
            error_var.set("Your note is required to mark as incorrectly rejected.")
            return
        error_var.set("")
        llm_reason = reason_box.get("1.0", tk.END).strip()
        scraped = scraped_cache.get(selected_job["url"], {})
        results.promote_to_matched(
            url=selected_job["url"],
            title=selected_job.get("role") or "",
            company=scraped.get("company") or "",
            llm_reason=llm_reason,
            user_note=user_note,
            skillset_match_percent=selected_job.get("skillset_match_percent", 0),
        )
        _remove_selected()

    tk.Button(
        btn_frame, text="Approve Rejection",
        font=("Helvetica", 13, "bold"),
        bg="#8b0000", fg="white", activebackground="#5c0000", activeforeground="white",
        relief="flat", padx=20, pady=8, command=on_approve_rejection,
    ).pack(side="left", padx=(0, 16))

    tk.Button(
        btn_frame, text="Rejected Incorrectly ✓",
        font=("Helvetica", 13, "bold"),
        bg="#2a7a2a", fg="white", activebackground="#1d5c1d", activeforeground="white",
        relief="flat", padx=20, pady=8, command=on_rejected_incorrectly,
    ).pack(side="left")

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------
    listbox.bind("<<ListboxSelect>>", _on_select)
    search_var.trace_add("write", _on_search)
    _populate_list()
    root.mainloop()
