"""JustJoin.it job board scraper — pure HTTP implementation.

Robots.txt compliance (https://justjoin.it/robots.txt):
  Disallow: /api/          ← this scraper does NOT touch any /api/ path
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Container, Generator
from types import MappingProxyType
from typing import Any, Self

import httpx
from loguru import logger
from pydantic import BaseModel, TypeAdapter

from job_scraper.exceptions import GetJobException, GetJobListingException
from job_scraper.schema import JobData


class BaseParams(BaseModel, ABC):
    
    @abstractmethod
    def build_listing_url(self) -> str:
        """Build the listing URL for this set of params."""

class BaseScraper(ABC):
    """Job board scraper base
    """

    HEADERS: MappingProxyType[str, str] = MappingProxyType({
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    })
    _param_type: type[BaseParams]

    def __init__(self, config: list[dict[str, Any]]) -> None:
        self._client: httpx.AsyncClient | None = None
        params = TypeAdapter(list[self._param_type]).validate_python(config)
        self._listing_urls = [p.build_listing_url() for p in params]


    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        )
        return self

    async def __aexit__(self, exc_type: Any, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str) -> str:
        """GET a URL and return the response body as text."""
        if not self._client:
            raise RuntimeError("Use 'async with Scraper() as s:' context manager.")
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.text
    
    @staticmethod
    @abstractmethod
    def _extract_job_urls(source: str) -> Generator[str]:
        ...

    @abstractmethod
    def _extract_job_data(self, job_url: str, source: str) -> JobData:
        """
        Raises:
            SourceParsingError
        """
        ...
    
    async def get_job_links(self, max_jobs: int, url_cache: Container) -> AsyncGenerator[str]:
        """Returns found job links as list.
        Raises: 
            RuntimeError if not used as context manager
            GetJobListingException if response status != 200 or no data was scraped (check selectors)
            """
        for listing_url in self._listing_urls:
            logger.info(f"fetching for {listing_url}...")
            try:
                listing_page_source = await self._get(listing_url)
            except httpx.HTTPStatusError as e:
                raise GetJobListingException("was not able to fetch job listing page") from e
            if listing_page_source is None:
                raise GetJobListingException("unexpected None fetch result")
            new_jobs = 0
            total_jobs = 0
            for url in self._extract_job_urls(listing_page_source):
                total_jobs += 1
                if new_jobs < max_jobs and url not in url_cache:
                    yield url
                    new_jobs += 1
            logger.info(f"New jobs found: {new_jobs} | total jobs found: {total_jobs}")
        
    async def view_job(self, job_url: str) -> JobData:
        """Fetch a job-offer page and return a normalised job dict.
        Raises:
            GetJobException
            SourceParsingError
            """
        try:
            html = await self._get(job_url)
        except httpx.HTTPStatusError as e:
            raise GetJobException("error fetchong job data") from e
        return self._extract_job_data(job_url, html)