"""JustJoin.it job board scraper — pure HTTP implementation.

Robots.txt compliance (https://justjoin.it/robots.txt):
  Disallow: /api/          ← this scraper does NOT touch any /api/ path
"""
import json
import re
from typing import Annotated, Any, Literal

import httpx
from loguru import logger
from pydantic import BaseModel, PlainSerializer, TypeAdapter, field_validator

from job_scraper.storage.sqlite_storage import UrlCache

BASE_URL = "https://justjoin.it"

def serializer(data: list[str]) -> str:
    return ",".join(data)
def salary_serializer(data: int) -> str:
    return f"{data},500000"

class Params(BaseModel):
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
ParamList = TypeAdapter(list[Params])

class JustJoinItScraper:
    """Job board scraper for justjoin.it — no browser required.
    Uses httpx.AsyncClient to fetch pages, then extracts job data
    Adheres to robots.txt: /api/ is never accessed.
    """

    HEADERS: dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,pl;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }

    def __init__(self, delay: float, config: list[dict[str, Any]]) -> None:
        self._delay = delay
        self._client: httpx.AsyncClient | None = None
        params: list[Params] = ParamList.validate_python(config)
        self._listing_urls = (self._build_listing_url(param) for param in params)
        logger.info(f"justjoin.it listing targets: {self._listing_urls}")

    # Async context manager (manages httpx client lifecycle)

    async def __aenter__(self) -> "JustJoinItScraper":
        self._client = httpx.AsyncClient(
            headers=self.HEADERS,
            follow_redirects=True,
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str) -> str | None:
        """GET a URL and return the response body as text."""
        if not self._client:
            raise RuntimeError("Use 'async with JustJoinItScraper() as s:' context manager.")
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as exc:
            logger.warning(f"HTTP {exc.response.status_code} for {url}")
        except Exception as exc:
            logger.warning(f"Request failed for {url}: {exc}")
        return None

    @staticmethod
    def _extract_json_ld(html: str) -> dict[str, Any] | None:
        """Extract the first schema.org/JobPosting JSON-LD block."""
        for match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        ):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and "JobPosting" in data.get("@type", ""):
                    return data
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and "JobPosting" in item.get("@type", ""):
                            return item
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _build_listing_url(params: Params) -> str:
        """Build a JustJoin.it listing page URL from config search filters.
        Produces URLs like:
          /job-offers/all-locations/python?employment-type=b2b&experience-level=junior,mid&orderBy=DESC&sortBy=published
        """

        path = f"{BASE_URL}/job-offers/{params.location}"
        if params.technology:
            path = f"{path}/{params.technology}"
        
        return f"{path}?{'&'.join(f"{k}={v}" for k, v in params.query_params.items())}"

    @staticmethod
    def _extract_collection_page_urls(html: str) -> list[str]:
        """Extract job URLs from JSON-LD CollectionPage.hasPart (Next.js App Router)."""
        for match in re.finditer(
            r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            html,
            re.DOTALL,
        ):
            try:
                data = json.loads(match.group(1))
                if isinstance(data, dict) and data.get("@type") == "CollectionPage":
                    parts = data.get("hasPart", [])
                    return [p["url"] for p in parts if isinstance(p, dict) and p.get("url")]
            except json.JSONDecodeError:
                continue
        return []

    async def get_job_links(self, max_jobs: int, url_cache: UrlCache) -> set[str]:
        result = set()
        for listing_url in self._listing_urls:
            logger.info(f"fetching for {listing_url}...")
            listing_page_source = await self._get(listing_url)
            if listing_page_source is None:
                continue
            urls = self._extract_collection_page_urls(listing_page_source)
            logger.info(f"total jobs: {len(urls)}")
            for url in urls:
                if len(result) < max_jobs:
                    if url not in url_cache:
                        result.add(url)
            logger.info(f"new jobs: {len(result)}")
        return result

    async def view_job(self, job_url: str) -> dict[str, Any]:
        """Fetch a job-offer page and return a normalised job dict."""
        html = await self._get(job_url)
        if not html:
            return {"url": job_url, "error": "Failed to fetch page"}

        json_ld = self._extract_json_ld(html)
        if json_ld:
            result = self._job_from_json_ld(job_url, json_ld)
            if result.get("title"):
                logger.info(
                    f"Viewing job (JSON-LD): {result.get('title')} at {result.get('company')}"
                )
                return result
        return {"url": job_url, "error": "No json_ld"}

    def _job_from_json_ld(
        self, job_url: str, ld: dict[str, Any]
    ) -> dict[str, Any]:
        """Map schema.org/JobPosting to our internal schema."""
        title = ld.get("title", "")
        company = ld.get("hiringOrganization", {}).get("name", "")
        location_obj = ld.get("jobLocation", {})
        address = location_obj.get("address", {})
        city = address.get("addressLocality", "")
        country = address.get("addressCountry", "")
        location = ", ".join(filter(None, [city, country]))

        work_mode_raw = ld.get("jobLocationType", "")
        work_mode = "Remote" if "TELECOMMUTE" in work_mode_raw.upper() else ""

        salary_obj = ld.get("baseSalary", {})
        salary_value = salary_obj.get("value", {})
        currency = salary_obj.get("currency", "PLN")
        sal_from = salary_value.get("minValue", "")
        sal_to = salary_value.get("maxValue", "")
        salary_str = ""
        if sal_from and sal_to:
            salary_str = f"{sal_from} - {sal_to} {currency}"
        elif sal_from:
            salary_str = f"from {sal_from} {currency}"

        description_html = ld.get("description", "")
        reqs = self._html_to_lines(description_html)

        return {
            "url": job_url,
            "title": title,
            "company": company,
            "location": location,
            "seniority": "",
            "work_mode": work_mode,
            "contracts": [{"type": "", "salary": salary_str}] if salary_str else [],
            "technologies": [],
            "technologies_optional": [],
            "requirements": reqs,
            "requirements_optional": [],
            "responsibilities": [],
        }

    @staticmethod
    def _html_to_lines(html: str) -> list[str]:
        """Strip HTML tags and return non-empty lines (for description parsing)."""
        text = re.sub(r"<[^>]+>", " ", html)
        lines = [ln.strip() for ln in re.split(r"[\n\r]+", text)]
        return [ln for ln in lines if len(ln) > 15]
