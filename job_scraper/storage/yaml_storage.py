"""YAML-based storage for scraped job data.

The YAML file acts as a pending queue between scraping and filtering phases.
Jobs are added during scraping and removed after filtering.
A separate URL cache (hashed) tracks all ever-seen URLs for fast dedup.
"""

import dbm
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


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


class YamlStorage:
    """YAML-based pending queue for scraped jobs.

    Jobs are added during scraping and removed after LLM filtering.
    The YAML file only contains unprocessed jobs.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.yaml_file = self.data_dir / "scraped_jobs.yaml"
        self.url_cache = UrlCache(data_dir)

    def _load_all(self) -> dict[str, Any]:
        """Load the full YAML file. Returns empty structure if file missing."""
        if not self.yaml_file.exists():
            return {"jobs": []}
        with open(self.yaml_file) as f:
            data = yaml.safe_load(f) or {}
        if "jobs" not in data:
            data["jobs"] = []
        return data

    def _save_all(self, data: dict[str, Any]) -> None:
        """Write the full YAML file atomically (write tmp, then rename)."""
        tmp_file = self.yaml_file.with_suffix(".yaml.tmp")
        with open(tmp_file, "w") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
                width=120,
            )
        tmp_file.rename(self.yaml_file)

    def save_job(self, job_data: dict[str, Any]) -> None:
        """Append a newly scraped job to the pending queue.

        Skips if URL is in the cache. Writes to disk immediately.
        """
        url = job_data["url"]

        if url in self.url_cache:
            logger.debug(f"URL already seen, skipping: {url}")
            return

        data = self._load_all()
        entry = {
            "url": url,
            "title": job_data.get("title", ""),
            "company": job_data.get("company", ""),
            "location": job_data.get("location", ""),
            "seniority": job_data.get("seniority", ""),
            "work_mode": job_data.get("work_mode", ""),
            "contracts": job_data.get("contracts", []),
            "technologies": job_data.get("technologies", []),
            "technologies_optional": job_data.get("technologies_optional", []),
            "requirements": job_data.get("requirements", []),
            "requirements_optional": job_data.get("requirements_optional", []),
            "responsibilities": job_data.get("responsibilities", []),
            "description": job_data.get("description", ""),
            "scraped_at": datetime.now().isoformat(),
        }
        data["jobs"].append(entry)
        self._save_all(data)
        self.url_cache.add(url)
        logger.info(f"Saved scraped job: {entry['title'] or url}")

    def load_pending_jobs(self) -> list[dict[str, Any]]:
        """Load all jobs from the pending queue."""
        return self._load_all()["jobs"]

    def remove_job(self, url: str) -> None:
        """Remove a job from the pending queue after processing."""
        data = self._load_all()
        data["jobs"] = [job for job in data["jobs"] if job["url"] != url]
        self._save_all(data)

    def pending_count(self) -> int:
        """Return number of jobs waiting to be filtered."""
        return len(self._load_all()["jobs"])
