"""Web scraping and automation modules."""
from collections.abc import AsyncGenerator, Container
from typing import Any, Protocol, Self

from job_scraper.schema import JobData
from job_scraper.scraper.justjoinit_scraper import JustJoinItScraper
from job_scraper.scraper.local_scraper import LocalScraper
from job_scraper.scraper.nofluff_scraper import NoFluffScraper
from job_scraper.scraper.protocol_scraper import ProtocolScraper


class Scraper(Protocol):
    def __init__(self, delay: float, config: list[dict[str, Any]]) -> None: ...
    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *_: Any) -> None: ...
    def get_job_links(self, max_jobs: int, url_cache: Container) -> AsyncGenerator[str]: ...
    async def view_job(self, job_url: str) -> JobData: ...


class ScraperClass(Protocol):
    def __call__(self, delay: float, config: list[dict[str, Any]]) -> Scraper: ...
    
    
scrapers: dict[str, ScraperClass] = {
    "local": LocalScraper,
    "justjoin": JustJoinItScraper,
    "protocol": ProtocolScraper,
    "nofluff": NoFluffScraper
}
AVAILABLE_SOURCES = list(scrapers.keys())