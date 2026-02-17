"""SQLite-based storage for scraped job data.

Drop-in replacement for YamlStorage. Uses a single SQLite file as the pending
queue. Lists/arrays are stored as JSON columns. Deletes are O(log n) via
primary-key index instead of load-all-filter-rewrite.

Migration: if a legacy scraped_jobs.yaml is present, its records are imported
automatically on first instantiation and the file is renamed to
scraped_jobs.yaml.migrated.
"""

import dbm
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger

_LIST_FIELDS = [
    "contracts",
    "technologies",
    "technologies_optional",
    "requirements",
    "requirements_optional",
    "responsibilities",
]

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    url                    TEXT PRIMARY KEY,
    title                  TEXT,
    company                TEXT,
    location               TEXT,
    seniority              TEXT,
    work_mode              TEXT,
    contracts              TEXT,
    technologies           TEXT,
    technologies_optional  TEXT,
    requirements           TEXT,
    requirements_optional  TEXT,
    responsibilities       TEXT,
    scraped_at             TEXT
)
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


class SqliteStorage:
    """SQLite-based pending queue for scraped jobs.

    Jobs are added during scraping and removed after LLM filtering.
    The database only contains unprocessed jobs.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = data_dir / "scraped_jobs.db"
        self.url_cache = UrlCache(data_dir)

        self._init_db()
        self._migrate_from_yaml()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(_DDL)

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for field in _LIST_FIELDS:
            raw = d.get(field)
            d[field] = json.loads(raw) if raw else []
        return d

    def _migrate_from_yaml(self) -> None:
        yaml_file = self.data_dir / "scraped_jobs.yaml"
        if not yaml_file.exists():
            return

        with open(yaml_file) as f:
            data = yaml.safe_load(f) or {}

        jobs: list[dict[str, Any]] = data.get("jobs", [])
        if not jobs:
            yaml_file.rename(yaml_file.with_suffix(".yaml.migrated"))
            return

        imported = 0
        for job in jobs:
            url = job.get("url", "")
            if not url:
                continue
            self._insert(job)
            if url not in self.url_cache:
                self.url_cache.add(url)
            imported += 1

        yaml_file.rename(yaml_file.with_suffix(".yaml.migrated"))
        logger.info(f"Migrated {imported} jobs from YAML → SQLite ({self._db_path.name})")

    def _insert(self, job_data: dict[str, Any]) -> None:
        row = (
            job_data.get("url", ""),
            job_data.get("title", ""),
            job_data.get("company", ""),
            job_data.get("location", ""),
            job_data.get("seniority", ""),
            job_data.get("work_mode", ""),
            json.dumps(job_data.get("contracts", []), ensure_ascii=False),
            json.dumps(job_data.get("technologies", []), ensure_ascii=False),
            json.dumps(job_data.get("technologies_optional", []), ensure_ascii=False),
            json.dumps(job_data.get("requirements", []), ensure_ascii=False),
            json.dumps(job_data.get("requirements_optional", []), ensure_ascii=False),
            json.dumps(job_data.get("responsibilities", []), ensure_ascii=False),
            job_data.get("scraped_at", datetime.now().isoformat()),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO jobs
                  (url, title, company, location, seniority, work_mode,
                   contracts, technologies, technologies_optional,
                   requirements, requirements_optional, responsibilities,
                   scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )

    # ------------------------------------------------------------------
    # Public API (same interface as YamlStorage)
    # ------------------------------------------------------------------

    def save_job(self, job_data: dict[str, Any]) -> None:
        """Insert a newly scraped job into the pending queue.

        Skips if the URL is already in the cache. Writes to disk immediately.
        """
        url = job_data["url"]

        if url in self.url_cache:
            logger.debug(f"URL already seen, skipping: {url}")
            return

        self._insert(job_data)
        self.url_cache.add(url)
        logger.info(f"Saved scraped job: {job_data.get('title') or url}")

    def load_pending_jobs(self) -> list[dict[str, Any]]:
        """Return all jobs currently in the pending queue."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM jobs").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def remove_job(self, url: str) -> None:
        """Remove a job from the pending queue after processing."""
        with self._connect() as conn:
            conn.execute("DELETE FROM jobs WHERE url = ?", (url,))

    def pending_count(self) -> int:
        """Return number of jobs waiting to be filtered."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()
        return row[0]
