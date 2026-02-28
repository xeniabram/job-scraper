"""SQLite-based storage for all job data."""

import dbm
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from loguru import logger

from job_scraper.exceptions import JobNotFound
from job_scraper.llm.filter import CvOptimized
from job_scraper.schema import (
    DailyStatEntry,
    DailyStats,
    Event,
    JobData,
    JobEvent,
    JobWithEvents,
    MatchedJob,
    RejectedJob,
)
from job_scraper.storage.DDL import _DDL


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

    def __contains__(self, url: object) -> bool:
        if not isinstance(url, str):
            return False
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

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)
            # Add scraped_at to existing tables that pre-date this column.
            for table in ("jobs", "matched", "rejected"):
                cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if "scraped_at" not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN scraped_at TEXT")

    def _update_daily(
        self,
        conn: sqlite3.Connection,
        *,
        date: str,
        scraped: int = 0,
        matched: int = 0,
        rejected: int = 0,
    ) -> None:
        """Upsert the row for *date* in daily_stats and apply the given deltas.

        Uses the job's scraped_at date so that reviewing a job scraped yesterday
        adjusts yesterday's counters, not today's.
        Runs inside the caller's transaction so the update is atomic with the data mutation.
        """
        conn.execute(
            "INSERT INTO daily_stats (date, scraped, matched, rejected)"
            " VALUES (?, 0, 0, 0)"
            " ON CONFLICT(date) DO NOTHING",
            (date,),
        )
        conn.execute(
            "UPDATE daily_stats"
            " SET scraped = scraped + ?, matched = matched + ?, rejected = rejected + ?"
            " WHERE date = ?",
            (scraped, matched, rejected, date),
        )

    # ------------------------------------------------------------------
    # Scraping queue
    # ------------------------------------------------------------------

    def save_job(self, job_data: JobData, source: str = "") -> None:
        """Insert a scraped job into the queue and increment today's scraped count.

        No-ops silently if the URL was already seen. The URL cache is updated only
        after the transaction commits so a failed write never poisons the cache.
        """
        url = job_data.url
        with self._connect() as conn:
            today = conn.execute("SELECT date('now')").fetchone()[0]
            cursor = conn.execute(
                "INSERT OR IGNORE INTO jobs (url, title, company, description, source, scraped_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (*job_data.row, source, today),
            )
            if cursor.rowcount == 0:
                return
            self._update_daily(conn, date=today, scraped=1)
            self.url_cache.add(url)
        logger.info(f"Saved scraped job: {job_data.title}")

    def load_pending_jobs(self, limit: int | None) -> list[JobData]:
        """Return all jobs in the scraping queue that have not been filtered yet."""
        with self._connect() as conn:
            stmt = "SELECT url, title, company, description FROM jobs"
            if limit:
                stmt += f" LIMIT {limit}"
            rows = conn.execute(stmt).fetchall()
        return [JobData.model_validate(dict(r)) for r in rows]

    def pending_count(self) -> int:
        """Return number of jobs in the scraping queue waiting to be filtered."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return row[0]

    # ------------------------------------------------------------------
    # Filter results
    # ------------------------------------------------------------------

    def save_matched_job(
        self,
        job: JobData,
        cv: CvOptimized | None,
        match_pct: int = 0,
    ) -> None:
        """Move a job from the scraping queue to matched and increment today's matched count.

        cv may be None when CV optimization is skipped; cv_about and cv_keywords are then
        stored as NULL and can be filled later via update_cv().
        """
        cv_about = cv.about_me if cv is not None else None
        cv_keywords = cv.keywords if cv is not None else None
        with self._connect() as conn:
            scraped_row = conn.execute("SELECT scraped_at FROM jobs WHERE url = ?", (job.url,)).fetchone()
            scraped_at = (scraped_row[0] if scraped_row and scraped_row[0]
                          else conn.execute("SELECT date('now')").fetchone()[0])
            cursor = conn.execute(
                "INSERT OR IGNORE INTO matched"
                " (url, title, company, description, match_pct, cv_about, cv_keywords, scraped_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job.url, job.title, job.company, json.dumps(job.description),
                 match_pct, cv_about, cv_keywords, scraped_at),
            )
            conn.execute("DELETE FROM jobs WHERE url = ?", (job.url,))
            if cursor.rowcount > 0:
                self._update_daily(conn, date=scraped_at, matched=1)
        logger.info(f"Saved matched job: {job.title}")

    def save_rejected_job(
        self,
        job: JobData,
        match_pct: int = 0,
        reason: str = "",
    ) -> None:
        """Move a job from the scraping queue to rejected and increment today's rejected count."""
        with self._connect() as conn:
            scraped_row = conn.execute("SELECT scraped_at FROM jobs WHERE url = ?", (job.url,)).fetchone()
            scraped_at = (scraped_row[0] if scraped_row and scraped_row[0]
                          else conn.execute("SELECT date('now')").fetchone()[0])
            conn.execute(
                "INSERT INTO rejected (url, title, company, description, match_pct, reason, scraped_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*job.row, match_pct, reason, scraped_at),
            )
            conn.execute("DELETE FROM jobs WHERE url = ?", (job.url,))
            self._update_daily(conn, date=scraped_at, rejected=1)
        logger.debug(f"Saved rejected job: {job.url}")

    def save_manual_job(self, job: JobData, destination: str) -> None:
        """Manually insert a job into jobs queue or matched table.
            Args:
                job: Job data to save.
                destination: 'jobs' or 'matched'.
        """
        with self._connect() as conn:
            today = conn.execute("SELECT date('now')").fetchone()[0]
            if destination == "matched":
                conn.execute(
                    "INSERT OR IGNORE INTO matched"
                    " (url, title, company, description, match_pct, scraped_at)"
                    " VALUES (?, ?, ?, ?, 0, ?)",
                    (job.url, job.title, job.company, json.dumps(job.description), today),
                )
                self._update_daily(conn, date=today, matched=1)
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO jobs"
                    " (url, title, company, description, source, scraped_at)"
                    " VALUES (?, ?, ?, ?, 'manual', ?)",
                    (job.url, job.title, job.company, json.dumps(job.description), today),
                )
                self._update_daily(conn, date=today, scraped=1)
            self.url_cache.add(job.url)
        logger.info(f"Manually saved job: {job.title} → {destination}")

    # ------------------------------------------------------------------
    # Matched jobs
    # ------------------------------------------------------------------

    def load_unoptimized_matched(self, limit: int | None) -> list[MatchedJob]:
        """Return matched jobs whose CV sections (cv_about/cv_keywords) are still NULL."""
        with self._connect() as conn:
            stmt = "SELECT * FROM matched WHERE cv_about IS NULL AND cv_keywords IS NULL"
            if limit is not None:
                stmt += f" LIMIT {limit}"
            rows = conn.execute(stmt).fetchall()
        return [MatchedJob.model_validate(dict(r)) for r in rows]

    def load_optimized_matched(self) -> list[MatchedJob]:
        """Return matched jobs that have CV sections filled in and are ready to apply to."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM matched WHERE cv_about IS NOT NULL AND cv_keywords IS NOT NULL"
            ).fetchall()
        return [MatchedJob.model_validate(dict(r)) for r in rows]

    def count_optimized_matched(self) -> int:
        """Return number of matched jobs with CV sections filled in."""
        with self._connect() as conn:
            res = conn.execute(
                "SELECT COUNT(*) FROM matched WHERE cv_about IS NOT NULL AND cv_keywords IS NOT NULL"
            ).fetchone()
        return res[0] if res else 0

    def update_cv(self, url: str, about: str, keywords: str) -> None:
        """Write optimized CV sections to a matched job."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE matched SET cv_about = ?, cv_keywords = ? WHERE url = ?",
                (about, keywords, url),
            )

    def mark_applied(self, url: str) -> None:
        """Delete a matched job after the user applies to it.

        Raises JobNotFound if the URL is not in the matched table.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title, company FROM matched WHERE url = ?", (url,)
            ).fetchone()
            if not row:
                raise JobNotFound("matched job not found")
            conn.execute(
                "INSERT INTO job_events (event, url, title, company) VALUES (?, ?, ?, ?)",
                (Event.applied, url, row["title"], row["company"])
            )
            conn.execute("DELETE FROM matched WHERE url = ?", (url,))
    
    def load_job_events(self) -> list[JobWithEvents]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, date, event, url, title, company FROM job_events ORDER BY date DESC"
            ).fetchall()
        
        grouped: dict[str, JobWithEvents] = {}
        for r in rows:
            url = r["url"]
            event = JobEvent(**dict(r))
            if url not in grouped:
                grouped[url] = JobWithEvents(
                    url=url,
                    title=r["title"],
                    company=r["company"],
                    latest_event_date=r["date"],
                    events=[event],
                )
            else:
                grouped[url].events.append(event)
        
        return sorted(grouped.values(), key=lambda j: j.latest_event_date, reverse=True)
    
    def add_job_event(self, url: str, event: Event, title: str, company: str) -> None:
        """Add a new event for a job."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO job_events (event, url, title, company) VALUES (?, ?, ?, ?)",
                (event, url, title, company)
            )

    # ------------------------------------------------------------------
    # Rejected review
    # ------------------------------------------------------------------

    def load_unreviewed_rejected(self) -> list[RejectedJob]:
        """Return all LLM-rejected jobs awaiting user review."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM rejected").fetchall()
        return [RejectedJob.model_validate(dict(r)) for r in rows]

    def reject_manually(self, url: str, user_reason: str) -> None:
        """Override the LLM's match: the user says this job is not relevant.

        Removes the job from matched, records the correction in learn with
        correct_label='rejected', and updates today's stats (matched -1, rejected +1).
        Raises JobNotFound if the URL is not in the matched table.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title, company, match_pct, scraped_at FROM matched WHERE url = ?", (url,)
            ).fetchone()
            if not row:
                raise JobNotFound("matched job not found")
            title, company, match_pct, scraped_at = row
            stats_date = scraped_at or conn.execute("SELECT date('now')").fetchone()[0]
            conn.execute("DELETE FROM matched WHERE url = ?", (url,))
            conn.execute(
                "INSERT OR REPLACE INTO learn"
                " (url, title, company, match_pct, reason, user_note, correct_label)"
                " VALUES (?, ?, ?, ?, ?, NULL, 'rejected')",
                (url, title, company, match_pct, user_reason),
            )
            self._update_daily(conn, date=stats_date, matched=-1, rejected=1)

    def confirm_rejection(self, url: str) -> None:
        """Confirm the LLM's rejection: the user agrees the job is not relevant.

        Simply removes the job from rejected. No learn entry is written because
        the LLM was correct. Raises JobNotFound if the URL is not in the rejected table.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT url FROM rejected WHERE url = ?", (url,)).fetchone()
            if not row:
                raise JobNotFound("rejected job not found")
            conn.execute("DELETE FROM rejected WHERE url = ?", (url,))

    def promote_to_matched(self, url: str, user_note: str = "") -> None:
        """Override the LLM's rejection: the user says this job is relevant.

        Moves the job from rejected to matched, records the correction in learn with
        correct_label='matched', and updates today's stats (matched +1, rejected -1).
        Raises JobNotFound if the URL is not in the rejected table.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT title, company, description, match_pct, reason, scraped_at FROM rejected WHERE url = ?", (url,)
            ).fetchone()
            if not row:
                raise JobNotFound("rejected job not found")
            title, company, description, match_pct, reason, scraped_at = row
            stats_date = scraped_at or conn.execute("SELECT date('now')").fetchone()[0]

            conn.execute(
                "INSERT OR REPLACE INTO matched"
                " (url, title, company, description, match_pct, scraped_at) VALUES (?, ?, ?, ?, ?, ?)",
                (url, title, company, description, match_pct, scraped_at),
            )
            conn.execute("DELETE FROM rejected WHERE url = ?", (url,))
            conn.execute(
                "INSERT OR REPLACE INTO learn"
                " (url, title, company, match_pct, reason, user_note, correct_label)"
                " VALUES (?, ?, ?, ?, ?, ?, 'matched')",
                (url, title, company, match_pct, reason, user_note),
            )
            self._update_daily(conn, date=stats_date, matched=1, rejected=-1)
        logger.info(f"Promoted incorrectly-rejected to matched: {title or url}")

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_daily_stats(self) -> DailyStats:
        """Return per-day scraped/matched/rejected counts and overall totals."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date, scraped, matched, rejected FROM daily_stats ORDER BY date DESC"
            ).fetchall()
        daily = [
            DailyStatEntry(date=r["date"], scraped=r["scraped"], matched=r["matched"], rejected=r["rejected"])
            for r in rows
        ]
        totals = DailyStatEntry(
            date="",
            scraped=sum(e.scraped for e in daily),
            matched=sum(e.matched for e in daily),
            rejected=sum(e.rejected for e in daily),
        )
        return DailyStats(daily=daily, totals=totals)
