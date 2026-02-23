"""JustJoin.it job board scraper — pure HTTP implementation.

Robots.txt compliance (https://justjoin.it/robots.txt):
  Disallow: /api/          ← this scraper does NOT touch any /api/ path
"""
import json
from collections.abc import Generator
from typing import Annotated, Any, Literal

from bs4 import BeautifulSoup
from loguru import logger
from pydantic import PlainSerializer, field_validator

from job_scraper.exceptions import SourceParsingError
from job_scraper.schema import JobData
from job_scraper.scraper.base import BaseParams, BaseScraper

BASE_URL = "https://justjoin.it"

def serializer(data: list[str]) -> str:
    return ",".join(data)
def salary_serializer(data: int) -> str:
    return f"{data},500000"

class Params(BaseParams):
    technology: Literal["admin", "ai", "analytics", "architecture", "c", "data", "devops", "erp", "game", "go", "html", "java", "javascript", "mobile", "net", "other", "php", "pm", "python", "ruby", "scala", "security", "support", "testing", "ux"] | None = None
    employment_type: Annotated[list[Literal["b2b", "internship", "mandate-contract", "permanent", "specific-task-contract"]] | None, PlainSerializer(serializer, when_used="unless-none")] = None
    experience_level: Annotated[list[Literal["c-level", "junior", "mid", "senior"]] | None , PlainSerializer(serializer, when_used="unless-none")] = None
    workplace: Annotated[list[Literal["hybrid", "office"]] | None, PlainSerializer(serializer, when_used="unless-none")] = None
    location: Literal["remote", "all-locations"] | str = "all-locations"
    salary: Annotated[int | None, PlainSerializer(salary_serializer, when_used="unless-none")] = None
    with_salary: Literal["yes"] | None = None

    @property
    def order_by(self) -> str:
        return "DESC"
    
    @property
    def sort_by(self) -> str:
        return "published"
    
    @property
    def query_params(self) -> dict[str, str]:
        data = self.model_dump(exclude_none=True, exclude={"location", "technology"})
        data = {k.replace("_", "-"): v for k, v in data.items()}
        return data
    
    @field_validator("location", mode="before")
    @classmethod
    def default_location(cls, v: object) -> object:
        return v or "all-locations"
    
    def build_listing_url(self):
        path = f"{BASE_URL}/job-offers/{self.location}"
        if self.technology:
            path = f"{path}/{self.technology}"
        
        return f"{path}?{'&'.join(f"{k}={v}" for k, v in self.query_params.items())}"
    

class JustJoinItScraper(BaseScraper):
    """Job board scraper for justjoin.it — no browser required.
    Uses httpx.AsyncClient to fetch pages, then extracts job data
    Adheres to robots.txt: /api/ is never accessed.
    """
    _param_type = Params

    @staticmethod
    def _extract_job_details_json_ld(html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except json.JSONDecodeError:
                continue
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict) and item.get("@type") == "JobPosting":
                    return item
        raise SourceParsingError("structure does not match expected. update your scraping method")


    @staticmethod
    def _extract_job_urls(source: str) -> Generator[str]:
        """Extract job URLs from a class collection-card"""
        soup = BeautifulSoup(source, "html.parser")
        for a in soup.select("a.offer-card"):
            yield BASE_URL + str(a["href"]).split("?")[0]
 
    def _job_from_json_ld(
        self, job_url: str, ld: dict[str, Any]
        ) -> JobData:
            try:
                title = ld["title"].strip()
                company = ld["hiringOrganization"]["name"].strip()

                return JobData(
                    url=job_url,
                    title=title,
                    company=company,
                    description=ld
                )
            except KeyError as e:
                raise SourceParsingError("job json ld is not as expected") from e
    
    def _extract_job_data(self, job_url: str, source: str) -> JobData:
        json_ld = self._extract_job_details_json_ld(source)
        result = self._job_from_json_ld(job_url, json_ld)
        logger.info(
            f"Viewing job (JSON-LD): {result.title} at {result.company}"
        )
        return result