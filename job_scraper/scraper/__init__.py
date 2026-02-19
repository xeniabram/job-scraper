"""Web scraping and automation modules."""
from collections.abc import Collection
from typing import Any, Protocol

from job_scraper.scraper.justjoinit_scraper import JustJoinItScraper
from job_scraper.scraper.protocol_scraper import ProtocolScraper
from job_scraper.storage.sqlite_storage import UrlCache


class JobBoard(Protocol):
    def __init__(self, delay: float, config: list[dict[str, Any]]):...
    async def __aenter__(self) -> "JobBoard":
        ...
    async def __aexit__(self, *_: Any) -> None:
        ...
    async def get_job_links(self, max_jobs: int, url_cache: UrlCache) -> Collection[str]:...
    async def view_job(self, job_url: str) -> dict[str, Any]:...

scrapers: dict[str, type[JobBoard]] = {
    "justjoin": JustJoinItScraper,
    "protocol": ProtocolScraper
}