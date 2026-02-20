"""SQLite-based storage for all job data."""

import dbm
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from job_scraper.schema import JobData

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    url         TEXT PRIMARY KEY,
    title       TEXT,
    company     TEXT,
    description TEXT,
    scraped_at  TEXT NOT NULL DEFAULT (datetime('now')),
    filtered_at TEXT DEFAULT NULL
);

CREATE TABLE IF NOT EXISTS failed_jobs (
    url        TEXT PRIMARY KEY,
    failed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matched_jobs (
    url                    TEXT PRIMARY KEY,
    title                  TEXT,
    company                TEXT,
    skillset_match_percent INTEGER,
    matched_at             TEXT,
    cv_about_me            TEXT,
    cv_keywords            TEXT,
    optimized_at           TEXT,
    applied_at             TEXT
);

CREATE TABLE IF NOT EXISTS rejected_jobs (
    url                    TEXT PRIMARY KEY,
    role                   TEXT,
    reason                 TEXT,
    skillset_match_percent INTEGER,
    rejected_at            TEXT
);

CREATE TABLE IF NOT EXISTS rejected_manually (
    url                    TEXT PRIMARY KEY,
    title                  TEXT,
    company                TEXT,
    skillset_match_percent INTEGER,
    reason                 TEXT,
    rejected_at            TEXT
);

CREATE TABLE IF NOT EXISTS learn (
    url                    TEXT PRIMARY KEY,
    title                  TEXT,
    company                TEXT,
    reason                 TEXT,
    user_note              TEXT,
    correct_label          TEXT,
    skillset_match_percent INTEGER,
    reviewed_at            TEXT
);
"""


class UrlCache:
    """Persistent set of seen URLs backed by a disk-based hash table (dbm).

    Lookups and inserts are O(1) without loading the full dataset into memory.
    Survives across sessions.
    """

    def __init__(self, data_dir: Path):
        self._db_path = str(data_dir / ".url_cache_db")

    @staticmethod
    def _key(url: str) -> bytes:
        return hashlib.sha256(url.encode()).digest()

    def __contains__(self, url: str) -> bool:
        with dbm.open(self._db_path, "c") as db:
            return self._key(url) in db

    def add(self, url: str) -> None:
        with dbm.open(self._db_path, "c") as db:
            db[self._key(url)] = b""

    def __len__(self) -> int:
        with dbm.open(self._db_path, "c") as db:
            return len(db)


class ResultsStorage:
    """SQLite-backed storage for all job data: scraping queue, filter results, and training data."""

    def __init__(self, data_dir: Path):
        data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = data_dir / "results.db"
        self.url_cache = UrlCache(data_dir)
        self._init_db()

    # ------------------------------------------------------------------
    # Infrastructure
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        raw = d.get("description")
        d["description"] = json.loads(raw) if raw else {}
        return d

    # ------------------------------------------------------------------
    # Scraping queue
    # ------------------------------------------------------------------

    def save_job(self, job_data: JobData) -> None:
        """Insert a scraped job. Skips if URL already in cache."""
        url = job_data.url
        if url in self.url_cache:
            logger.debug(f"URL already seen, skipping: {url}")
            return
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO jobs (url, title, company, description) VALUES (?, ?, ?, ?)",
                job_data.row,
            )
        self.url_cache.add(url)
        logger.info(f"Saved scraped job: {job_data.title or url}")

    def load_pending_jobs(self) -> list[dict[str, Any]]:
        """Return jobs that have not been filtered yet."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs WHERE filtered_at IS NULL").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def load_all_jobs(self) -> list[dict[str, Any]]:
        """Return all jobs regardless of filtered status."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def mark_processed(self, url: str) -> None:
        """Stamp filtered_at on a job."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE jobs SET filtered_at = ? WHERE url = ?",
                (datetime.now().isoformat(), url),
            )

    def reset_processed(self) -> int:
        """Clear filtered_at on all jobs so they can be reprocessed. Returns count reset."""
        with self._connect() as conn:
            cur = conn.execute("UPDATE jobs SET filtered_at = NULL WHERE filtered_at IS NOT NULL")
        return cur.rowcount

    def pending_count(self) -> int:
        """Return number of jobs not yet filtered."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs WHERE filtered_at IS NULL").fetchone()
        return row[0]

    def save_failed_job(self, url: str) -> None:
        """Record a URL that could not be fetched."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO failed_jobs (url, failed_at) VALUES (?, ?)",
                (url, datetime.now().isoformat()),
            )
        logger.warning(f"Recorded failed job URL: {url}")

    def get_scraped_details(self, url: str) -> dict[str, Any]:
        """Fetch scraped details for a URL from the jobs table."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT company, description FROM jobs WHERE url = ?",
                (url,),
            ).fetchone()
        if not row:
            return {}
        desc = json.loads(row["description"] or "{}") if row["description"] else {}
        return {"company": row["company"] or "", **desc}

    # ------------------------------------------------------------------
    # Filter results
    # ------------------------------------------------------------------

    async def save_matched_job(
        self,
        url: str,
        title: str = "",
        company: str = "",
        skillset_match_percent: int = 0,
        cv: dict[str, str] | None = None,
    ) -> None:
        """Insert or replace a matched job with optional optimized CV sections."""
        cv = cv or {}
        with self._connect() as conn:
            if company and title:
                count = conn.execute(
                    "SELECT COUNT(*) FROM matched_jobs WHERE LOWER(company) = LOWER(?) AND LOWER(title) = LOWER(?)",
                    (company, title),
                ).fetchone()[0]
                if count:
                    logger.warning(
                        f"Duplicate detected (company+title match), skipping: '{company}' / '{title}' ({url})"
                    )
                    return
            conn.execute(
                """
                INSERT OR REPLACE INTO matched_jobs
                  (url, title, company, skillset_match_percent, matched_at, cv_about_me, cv_keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (url, title, company, skillset_match_percent, datetime.now().isoformat(),
                 cv.get("about_me", ""), cv.get("keywords", "")),
            )
        logger.info(f"Saved matched job: {title or url}")

    async def save_rejected_job(
        self,
        url: str,
        role: str = "",
        reason: str = "",
        skillset_match_percent: int = 0,
    ) -> None:
        """Insert or replace a rejected job."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO rejected_jobs
                  (url, role, reason, skillset_match_percent, rejected_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (url, role, reason, skillset_match_percent, datetime.now().isoformat()),
            )
        logger.debug(f"Saved rejected job: {url}")

    def load_unoptimized_matched_urls(self) -> list[str]:
        """Return URLs of matched jobs that have not been CV-optimized yet."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT url FROM matched_jobs WHERE optimized_at IS NULL"
            ).fetchall()
        return [row["url"] for row in rows]

    def update_cv(self, url: str, about_me: str, keywords: str) -> None:
        """Write optimized CV sections and stamp optimized_at."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE matched_jobs
                SET cv_about_me = ?, cv_keywords = ?, optimized_at = ?
                WHERE url = ?
                """,
                (about_me, keywords, datetime.now().isoformat(), url),
            )

    def load_unapplied_matched(self) -> list[dict[str, Any]]:
        """Return matched jobs that have not been marked as applied."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM matched_jobs WHERE applied_at IS NULL ORDER BY matched_at"
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_applied(self, url: str) -> None:
        """Stamp applied_at on a matched job."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE matched_jobs SET applied_at = ? WHERE url = ?",
                (datetime.now().isoformat(), url),
            )

    def reject_manually(self, url: str, reason: str) -> None:
        """Move a matched job to rejected_manually + learn, delete from matched_jobs."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title, company, skillset_match_percent FROM matched_jobs WHERE url = ?",
                (url,),
            ).fetchone()
            title = row["title"] if row else ""
            company = row["company"] if row else ""
            pct = row["skillset_match_percent"] if row else 0
            conn.execute(
                """
                INSERT OR REPLACE INTO rejected_manually
                  (url, title, company, skillset_match_percent, reason, rejected_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (url, title, company, pct, reason, now),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO learn
                  (url, title, company, reason, correct_label, skillset_match_percent, reviewed_at)
                VALUES (?, ?, ?, ?, 'rejected', ?, ?)
                """,
                (url, title, company, reason, pct, now),
            )
            conn.execute("DELETE FROM matched_jobs WHERE url = ?", (url,))

    def load_unreviewed_rejected(self) -> list[dict[str, Any]]:
        """Return LLM-rejected jobs not yet in the learn table, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT rj.url, COALESCE(rj.role, j.title) AS role,
                       rj.reason, rj.skillset_match_percent, rj.rejected_at
                FROM rejected_jobs rj
                LEFT JOIN jobs j ON rj.url = j.url
                WHERE rj.url NOT IN (SELECT url FROM learn)
                ORDER BY rj.rejected_at DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def promote_to_matched(
        self,
        url: str,
        title: str,
        company: str,
        llm_reason: str,
        user_note: str,
        skillset_match_percent: int,
    ) -> None:
        """Insert into matched_jobs and record in learn as correctly matched."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO matched_jobs
                  (url, title, company, skillset_match_percent, matched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (url, title, company, skillset_match_percent, now),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO learn
                  (url, title, company, reason, user_note, correct_label, skillset_match_percent, reviewed_at)
                VALUES (?, ?, ?, ?, ?, 'matched', ?, ?)
                """,
                (url, title, company, llm_reason, user_note, skillset_match_percent, now),
            )
        logger.info(f"Promoted incorrectly-rejected to matched: {title or url}")

    def save_to_learn(
        self,
        url: str,
        title: str,
        company: str,
        reason: str,
        correct_label: str,
        skillset_match_percent: int,
        user_note: str = "",
    ) -> None:
        """Insert or replace a labeled training example in the learn table."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO learn
                  (url, title, company, reason, user_note, correct_label, skillset_match_percent, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (url, title, company, reason, user_note, correct_label,
                 skillset_match_percent, datetime.now().isoformat()),
            )
        logger.debug(f"Saved to learn ({correct_label}): {url}")

    def get_stats(self) -> dict[str, Any]:
        """Return matched/rejected counts."""
        with self._connect() as conn:
            matched = conn.execute("SELECT COUNT(*) FROM matched_jobs").fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM rejected_jobs").fetchone()[0]
        return {"matched": matched, "rejected": rejected, "total": matched + rejected}
