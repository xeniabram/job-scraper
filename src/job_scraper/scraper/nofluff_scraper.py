import asyncio
from collections.abc import Iterable
from typing import Annotated, Any, Literal

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from loguru import logger
from pydantic import BaseModel, PlainSerializer, TypeAdapter

from job_scraper.exceptions import GetJobException
from job_scraper.schema import JobData
from job_scraper.storage import UrlCache

BASE_URL = "https://nofluffjobs.com/pl/"

def serialize_joined(input: set[str] | list[str] | str) -> str:
    if not input:
        return ""
    if isinstance(input, Iterable) and not isinstance(input, str):
        return ",".join(input)
    return str(input)

TechLiteral = set[Literal[
    "Java", "Python", "C#", "SQL", "C++", "Golang",
    "JavaScript", "React", "Angular", "TypeScript", "HTML"
]]

CategoryLiteral = set[Literal[
    "sys-administrator", "business-analyst", "architecture", "backend",
    "data", "ux", "devops", "erp", "embedded", "frontend", "fullstack",
    "game-dev", "mobile", "project-manager", "security", "support",
    "testing", "other"
]]

SeniorityLiteral = set[Literal["trainee", "junior", "mid", "senior", "expert"]]

EmploymentLiteral = set[Literal["permanent", "zlecenie", "b2b", "uod", "intern"]]

WorkModeLiteral = set[Literal["remote", "hybrid", "fieldwork"]]

JobLanguageLiteral = set[Literal["pl", "en"]]


# ── Params model ──────────────────────────────────────────────────────────────

class Params(BaseModel):
    requirement: Annotated[
        TechLiteral | None,
        PlainSerializer(serialize_joined, when_used="unless-none"),
    ] = None

    category: Annotated[
        CategoryLiteral | None,
        PlainSerializer(serialize_joined, when_used="unless-none"),
    ] = None

    seniority: Annotated[
        SeniorityLiteral | None,
        PlainSerializer(serialize_joined, when_used="unless-none"),
    ] = None

    employment: Annotated[
        EmploymentLiteral | None,
        PlainSerializer(serialize_joined, when_used="unless-none")
    ]

    city: Annotated[
        list[Literal["praca-zdalna", "hybrid", "fieldwork"] | str],
         PlainSerializer(serialize_joined)] = ["praca-zdalna"]


    @property
    def query_params(self) -> str:
        import urllib.parse
        data = self.model_dump()
        params = " ".join(f"{k}={v}" for k, v in data.items() if v is not None)
        return f"criteria={urllib.parse.quote(params, safe=",")}"

    def url(self, base: str) -> str:
        if p := self.query_params:
            return f"{base}?{p}"
        return base

BASE_URL = "https://nofluffjobs.com"
_IMPERSONATE = "chrome120"

ParamList = TypeAdapter(list[Params])



class NoFluffScraper:
    """Scraper for theprotocol.it using HTTP requests + HTML parsing."""

    def __init__(self, delay: float, config: list[dict[str, Any]]):
        self._delay = delay
        self._session: AsyncSession | None = None
        param_list = ParamList.validate_python(config)
        self._search_urls = [param.url(BASE_URL) for param in param_list]

    async def __aenter__(self) -> "NoFluffScraper":
        self._session = AsyncSession(impersonate=_IMPERSONATE)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def _get(self, url: str) -> BeautifulSoup:
        if not self._session:
            raise RuntimeError("Use 'async with ProtocolScraper() as s:' context manager.")
        resp = await self._session.get(
            url,
            headers={"Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8"},
            timeout=30,
        )
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    async def get_job_links(
        self,
        max_jobs: int,
        url_cache: UrlCache,
    ) -> list[str]:
        """Paginate all search URLs and return up to max_jobs unseen job links."""
        unseen: list[str] = []
        seen: set[str] = set()

        for search_url in self._search_urls:
            logger.info(f"Fetching url {search_url}...")
            try:
                soup = await self._get(search_url)
            except Exception as e:
                logger.warning(f"Fetch error ({search_url}): {e}")
                continue

            cards = soup.select("a.posting-list-item")
            if not cards:
                break

            page_new = 0
            page_all = 0
            for card in cards:
                href = str(card.get("href") or "")
                if not href:
                    continue
                page_all += 1
                full_url = (BASE_URL + href) if not href.startswith("http") else href
                full_url = full_url.split("?")[0]
                if full_url in seen or full_url in url_cache:
                    continue
                seen.add(full_url)
                unseen.append(full_url)
                page_new += 1
                if len(unseen) >= max_jobs:
                    logger.info(f"Collected {len(unseen)} job links. Total links on the page: {page_all}")
                    return unseen

            await asyncio.sleep(self._delay)

        logger.info(f"Collected {len(unseen)} job links")
        return unseen

    async def view_job(self, job_url: str) -> JobData:
        """Fetch a job detail page and extract structured data."""
        try:
            soup = await self._get(job_url)
        except Exception as e:
            logger.error(f"Failed to fetch {job_url}: {e}")
            raise GetJobException

        title_tag = soup.select_one("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""
        company_url = soup.select_one('[data-cy="JobOffer_CompanyProfile"]')
        company = company_url.get_text(strip=True) if company_url else ""
        work_mode_container = soup.select_one('[data-cy="location_pin"] > span')
        work_mode = work_mode_container.get_text(strip=True) if work_mode_container else ""
        location = [
            span.get_text(strip=True)
            for span in soup.select(".popover-locations li a span")
        ]
        seniority_container = soup.select_one("#posting-seniority span")
        seniority = seniority_container.get_text(strip=True) if seniority_container else ""
        salaries = {}
        first_list = soup.select_one("common-posting-salaries-list")

        if first_list:
            for i, div in enumerate(first_list.select(".salary")):
                amount_container = div.select_one("h4")
                amount = amount_container.get_text(strip=True) if amount_container else f"salary {i}"
                contract_container = div.select_one("span")
                contract = contract_container.get_text(strip=True) if contract_container else f"contract {i}"
                salaries[contract] = amount
        technologies = [
            el.get_text(strip=True)
            for el in soup.select('[branch="musts"] li')
        ]
        technologies_optional = [
            el.get_text(strip=True)
            for el in soup.select('[branch="nices"] li')
        ]
        section = soup.select_one('[data-cy-section="JobOffer_Requirements"] nfj-read-more div')
        requirements = section.get_text(separator="\n", strip=True) if section else None
        resp_section = soup.select_one("#posting-description nfj-read-more div")
        responsibilities = resp_section.get_text(separator="\n", strip=True) if resp_section else None

        if not title and not technologies and not requirements:
            logger.warning(f"No data extracted from {job_url}")

        logger.info(f"Viewed: {title or 'Unknown'} @ {company or 'Unknown'}")
        return JobData(
            url=job_url,
            title=title,
            company=company,
            description= {
                "location": location,
            "seniority": seniority,
            "work_mode": work_mode,
            "technologies": technologies,
            "technologies_optional": technologies_optional,
            "requirements": requirements,
            "responsibilities": responsibilities,
            }
        )