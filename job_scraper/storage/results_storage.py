"""SQLite-based storage for filter results (matched and rejected jobs)."""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

_DDL = """
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
"""


class ResultsStorage:
    """Stores LLM filter results (matched + rejected) in SQLite."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = data_dir / "results.db"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)
            columns = [row[1] for row in conn.execute("PRAGMA table_info(matched_jobs)")]
            for col in ("optimized_at", "applied_at"):
                if col not in columns:
                    conn.execute(f"ALTER TABLE matched_jobs ADD COLUMN {col} TEXT")
            rejected_columns = [row[1] for row in conn.execute("PRAGMA table_info(rejected_jobs)")]
            if "role" not in rejected_columns:
                conn.execute("ALTER TABLE rejected_jobs ADD COLUMN role TEXT")

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
            conn.execute(
                """
                INSERT OR REPLACE INTO matched_jobs
                  (url, title, company, skillset_match_percent, matched_at,
                   cv_about_me, cv_keywords)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    title,
                    company,
                    skillset_match_percent,
                    datetime.now().isoformat(),
                    cv.get("about_me", ""),
                    cv.get("keywords", ""),
                ),
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
        """Move a matched job to rejected_manually and delete it from matched_jobs."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title, company, skillset_match_percent FROM matched_jobs WHERE url = ?",
                (url,),
            ).fetchone()
            conn.execute(
                """
                INSERT OR REPLACE INTO rejected_manually
                  (url, title, company, skillset_match_percent, reason, rejected_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    url,
                    row["title"] if row else "",
                    row["company"] if row else "",
                    row["skillset_match_percent"] if row else 0,
                    reason,
                    datetime.now().isoformat(),
                ),
            )
            conn.execute("DELETE FROM matched_jobs WHERE url = ?", (url,))

    def get_stats(self) -> dict[str, Any]:
        """Return matched/rejected counts."""
        with self._connect() as conn:
            matched = conn.execute("SELECT COUNT(*) FROM matched_jobs").fetchone()[0]
            rejected = conn.execute("SELECT COUNT(*) FROM rejected_jobs").fetchone()[0]
        return {"matched": matched, "rejected": rejected, "total": matched + rejected}
