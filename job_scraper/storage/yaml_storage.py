"""YAML-based storage for scraped job data.

The YAML file acts as a pending queue between scraping and filtering phases.
Jobs are added during scraping and removed after filtering.
A separate URL cache (hashed) tracks all ever-seen URLs for fast dedup.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from loguru import logger


class UrlCache:
    """Persistent set of seen URLs stored as SHA256 hashes.

    One hash per line in a flat file. Loaded into memory as a set
    for O(1) lookups. Survives across sessions.
    """

    def __init__(self, data_dir: Path):
        self._file = data_dir / ".url_cache"
        self._hashes: set[str] = set()
        self._load()

    @staticmethod
    def _hash(url: str) -> str:
        return hashlib.sha256(url.encode()).hexdigest()

    def _load(self) -> None:
        if not self._file.exists():
            return
        with open(self._file, "r") as f:
            self._hashes = {line.strip() for line in f if line.strip()}
        logger.debug(f"URL cache loaded: {len(self._hashes)} entries")

    def __contains__(self, url: str) -> bool:
        return self._hash(url) in self._hashes

    def add(self, url: str) -> None:
        h = self._hash(url)
        if h not in self._hashes:
            self._hashes.add(h)
            with open(self._file, "a") as f:
                f.write(h + "\n")

    def __len__(self) -> int:
        return len(self._hashes)


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
        with open(self.yaml_file, "r") as f:
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
