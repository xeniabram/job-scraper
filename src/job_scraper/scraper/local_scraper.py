"""Local scraper
"""
import json
from collections.abc import Generator
from pathlib import Path
from typing import Any, Self

from loguru import logger

from job_scraper.schema import JobData
from job_scraper.scraper.base import BaseParams, BaseScraper


class Params(BaseParams):
    path: Path

    def build_listing_url(self) -> str:
        """Build the listing URL for this set of params."""
        return str(self.path)

class LocalScraper(BaseScraper):
    """Job board scraper for justjoin.it — no browser required.
    Uses httpx.AsyncClient to fetch pages, then extracts job data
    Adheres to robots.txt: /api/ is never accessed.
    """
    _param_type = Params

    async def _get(self, url: str) -> str:
        """ _get stub to conform to base class"""
        return url
    
    async def __aenter__(self) -> Self:
        return self
    
    async def __aexit__(self, exc_type: Any, *_: Any) -> None:
        if exc_type is None:
            for location in self._listing_urls:
                for file in Path(location).iterdir():
                    file.unlink()
            logger.info("Cleaned up processed job files")

    @staticmethod
    def _extract_job_urls(source: str) -> Generator[str]:
        """Extract job URLs from a class collection-card"""
        for file in Path(source).glob("*.json"):
            yield str(file)
    
    def _extract_job_data(self, job_url: str, source: str) -> JobData:
        with open(job_url, encoding="utf-8-sig") as file:
            json_str = file.read()
        return JobData.model_validate(json.loads(json_str))