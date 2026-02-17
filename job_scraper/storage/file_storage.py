"""File-based storage for job links and metadata."""

from pathlib import Path
from typing import Any

import aiofiles
from loguru import logger


class FileStorage:
    """Async file storage for job data."""

    def __init__(self, data_dir: Path):
        """Initialize file storage.

        Args:
            data_dir: Directory to store data files
        """
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.matched_file = self.data_dir / "matched_jobs.txt"
        self.rejected_file = self.data_dir / "rejected_jobs.txt"

    async def save_matched_job(
        self,
        job_url: str,
        job_title: str = "",
        skillset_match_percent: int = 0,
    ) -> None:
        """Save a matched job to the matched jobs file.

        Args:
            job_url: URL of the job posting
            job_title: Optional job title
            skillset_match_percent: Percentage of skillset coverage
        """
        async with aiofiles.open(self.matched_file, mode="a") as f:
            line = f"{job_url} | {skillset_match_percent}% match"
            if job_title:
                line += f" | {job_title}"
            await f.write(line + "\n")

        logger.info(f"Saved matched job: {job_title or job_url}")

    async def save_rejected_job(
        self,
        job_url: str,
        reason: str = "",
        skillset_match_percent: int = 0,
    ) -> None:
        """Save a rejected job to the rejected jobs file.

        Args:
            job_url: URL of the job posting
            reason: Optional rejection reason
            skillset_match_percent: Percentage of skillset coverage
        """
        async with aiofiles.open(self.rejected_file, mode="a") as f:
            line = f"{job_url} | {skillset_match_percent}% match"
            if reason:
                line += f" | {reason}"
            await f.write(line + "\n")

        logger.debug(f"Saved rejected job: {job_url}")

    async def load_processed_urls(self) -> set[str]:
        """Load all previously processed job URLs to avoid duplicates.

        Returns:
            Set of processed URLs
        """
        urls: set[str] = set()

        for file_path in [self.matched_file, self.rejected_file]:
            if file_path.exists():
                async with aiofiles.open(file_path, mode="r") as f:
                    async for line in f:
                        # Extract URL (first part before |)
                        url = line.split("|")[0].strip()
                        if url:
                            urls.add(url)

        logger.info(f"Loaded {len(urls)} previously processed URLs")
        return urls

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored jobs.

        Returns:
            Dictionary with matched and rejected job counts
        """
        matched_count = 0
        rejected_count = 0

        if self.matched_file.exists():
            with open(self.matched_file) as f:
                matched_count = sum(1 for line in f if line.strip())

        if self.rejected_file.exists():
            with open(self.rejected_file) as f:
                rejected_count = sum(1 for line in f if line.strip())

        return {
            "matched": matched_count,
            "rejected": rejected_count,
            "total": matched_count + rejected_count,
        }
