"""Local scraper — reads job JSON files from disk instead of fetching from the web."""
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
        return str(self.path)


class LocalScraper(BaseScraper):
    """Reads job data from local JSON files instead of fetching from a live job board."""
    _param_type = Params

    async def _get(self, url: str) -> str:
        return Path(url).read_text(encoding="utf-8-sig")
    
    async def __aenter__(self) -> Self:
        return self
    
    async def __aexit__(self, exc_type: Any, *_: Any) -> None:
        if exc_type is None:
            for location in self._listing_urls:
                for file in Path(location).iterdir():
                    file.unlink()
            logger.info("Cleaned up processed job files")

    def _extract_job_urls(self, source: str) -> Generator[str]:
        """Yield file paths for all .json files in the directory."""
        for file in Path(source).glob("*.json"):
            yield str(file)

    def _extract_job_data(self, job_url: str, source: str) -> JobData:
        return JobData.model_validate(json.loads(source))