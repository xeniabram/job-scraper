"""theprotocol.it job board scraper — lightweight HTTP implementation.

No browser required. Uses curl_cffi to bypass Cloudflare and BeautifulSoup
to parse HTML via stable data-test attributes.
"""

import asyncio
import itertools
from collections.abc import Callable, Iterable
from typing import Annotated, Any, Literal

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from loguru import logger
from pydantic import BaseModel, PlainSerializer, TypeAdapter, model_validator

from job_scraper.exceptions import GetJobException
from job_scraper.schema import JobData
from job_scraper.storage import UrlCache


def serialize_with_suffix(suffix: str) -> Callable[[set[str] | str], str]:
    def inner(input: set[str] | str) -> str:
        if not input:
            return ""
        if isinstance(input, Iterable) and not isinstance(input, str):
            return ",".join(list(input)) + suffix
        return input + suffix
    return inner


type TechLiteral = set[Literal[
    "node.js", "net", "angular", "aws", "c", "c#", "c++",
    "go", "hibernate", "html", "ios", "java", "rust",
    "sql", "ruby", "react.js", "python", "r", "php",
    "javascript", "android", "typescript"
]]


class Params(BaseModel):
    technologies_must: Annotated[TechLiteral | None, PlainSerializer(serialize_with_suffix(";t"), when_used="unless-none")] = None
    technologies_nice: Annotated[TechLiteral | None, PlainSerializer(serialize_with_suffix(";nt"), when_used="unless-none")] = None
    technologies_not: TechLiteral | None = None
    specializations: Annotated[set[Literal[
        "backend", "frontend", "qa-testing", "security", "devops",
        "helpdesk", "it-admin", "data-analytics-bi", "big-data-science",
        "ux-ui", "ai-ml", "project-management", "fullstack", "mobile",
        "embedded", "gamedev", "architecture", "business-analytics",
        "agile", "product-management", "sap-erp", "system-analytics"
    ]] | None, PlainSerializer(serialize_with_suffix(";sp"), when_used="unless-none")] = None
    seniority_levels: Annotated[
        set[Literal[
            "trainee", "assistant", "junior", "mid",
            "senior", "expert", "lead", "manager",
            "head", "executive"
        ]] | None,
        PlainSerializer(serialize_with_suffix(";p"), when_used="unless-none")
    ] = None
    contracts: Annotated[list[Literal[
        "kontrakt-b2b", "umowa-o-prace", "umowa-zlecenie",
        "umowa-o-dzielo", "umowa-na-zastepstwo", "umowa-agencyjna",
        "umowa-o-prace-tymczasowa", "umowa-o-staz-praktyki"
    ]] | None, PlainSerializer(serialize_with_suffix(";c"), when_used="unless-none")] = None
    work_modes: Annotated[
        set[Literal["zdalna", "hybrydowa", "stacjonarna"]] | None,
        PlainSerializer(serialize_with_suffix(";rw"), when_used="unless-none")
    ] = None
    locations: Annotated[
        set[str] | None,
        PlainSerializer(serialize_with_suffix(";wp"), when_used="unless-none")
    ] = None
    salary: Annotated[int | None, PlainSerializer(serialize_with_suffix(";s"), when_used="unless-none")] = None
    project_description_present: bool = False

    @model_validator(mode="after")
    def validate_unique_tech(self) -> "Params":
        must_set = self.technologies_must or set()
        nice_set = self.technologies_nice or set()
        not_set = self.technologies_not or set()

        if overlap := must_set & nice_set:
            raise ValueError(f"Technologies cannot be both 'must' and 'nice': {overlap}")
        if overlap := must_set & not_set:
            raise ValueError(f"Technologies cannot be both 'must' and 'not': {overlap}")
        if overlap := nice_set & not_set:
            raise ValueError(f"Technologies cannot be both 'nice' and 'not': {overlap}")
        return self

    @property
    def query_params(self) -> str:
        parts: list[str] = []
        if self.technologies_not:
            parts.extend(f"et={tech}" for tech in self.technologies_not)
        if self.project_description_present:
            parts.append("context=projects")
        return "&".join(parts)
    
    @property
    def segments(self) -> str:
        data = self.model_dump(exclude_none=True, exclude={"project_description_present", "technologies_not"})
        return "/".join(data.values())

ParamList = TypeAdapter(list[Params])

BASE_URL = "https://theprotocol.it"
_IMPERSONATE = "chrome120"


class ProtocolScraper:
    """Scraper for theprotocol.it using HTTP requests + HTML parsing."""

    def __init__(self, delay: float, config: list[dict[str, Any]]):
        self._delay = delay
        self._session: AsyncSession | None = None
        param_list = ParamList.validate_python(config)
        self._search_urls = [self._build_listing_url(param) for param in param_list]

    async def __aenter__(self) -> "ProtocolScraper":
        self._session = AsyncSession(impersonate=_IMPERSONATE)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()
            self._session = None


    @staticmethod
    def _build_listing_url(config: Params) -> str:
        """Build a theprotocol.it filter URL from config dict."""
        query = config.query_params
        return BASE_URL + "/filtry/" + config.segments + (f"?{query}" if query else "")


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
            sep = "&" if "?" in search_url else "?"
            for page_num in itertools.count(1):
                suffix = f"{sep}pageNumber={page_num}" if page_num > 1 else ""
                try:
                    soup = await self._get(f"{search_url}{suffix}")
                except Exception as e:
                    logger.warning(f"Fetch error ({search_url} p{page_num}): {e}")
                    break

                cards = soup.select('a[data-test="list-item-offer"]')
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
                        logger.info(f"Collected {len(unseen)} job links")
                        return unseen
                logger.info(f"Page {page_num}: {page_new} new | total new: {len(unseen)} | total on page: {page_all}")

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

        def text(selector: str) -> str:
            el = soup.select_one(selector)
            return el.get_text(strip=True) if el else ""

        title = text('[data-test="text-offerTitle"]')
        company = text('[data-test="text-offerEmployer"]')
        location = text('[data-test="text-primaryLocation"]')
        seniority = text('[data-test="content-positionLevels"]')
        work_mode = text('[data-test="content-workModes"]')

        # Contracts — one block per contract type offered
        contracts: list[dict[str, str]] = []
        for block in soup.select('[data-test="section-contract"]'):

            def _t(sel: str, parent: Any = block) -> str:
                el = parent.select_one(sel)
                return el.get_text(strip=True) if el else ""

            contracts.append(
                {
                    "salary": _t('[data-test="text-contractSalary"]'),
                    "units": _t('[data-test="text-contractUnits"]'),
                    "period": _t('[data-test="text-contractTimeUnits"]'),
                    "type": _t('[data-test="text-contractName"]'),
                }
            )

        # Technologies: data-icon="true" → required, "false" → optional
        technologies: list[str] = []
        technologies_optional: list[str] = []
        for chip in soup.select('[data-test="chip-technology"]'):
            name = str(chip.get("title") or chip.get_text(strip=True))
            if str(chip.get("data-icon", "")) == "true":
                technologies.append(name)
            else:
                technologies_optional.append(name)

        def section_items(selector: str) -> list[str]:
            sec = soup.select_one(selector)
            if not sec:
                return []
            return [li.get_text(strip=True) for li in sec.select("li") if li.get_text(strip=True)]

        requirements = section_items('[data-test="section-requirements-expected"]')
        requirements_optional = section_items('[data-test="section-requirements-optional"]')
        responsibilities = section_items('[data-test="section-responsibilities"]')

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
            "contracts": contracts,
            "technologies": technologies,
            "technologies_optional": technologies_optional,
            "requirements": requirements,
            "requirements_optional": requirements_optional,
            "responsibilities": responsibilities,
            }
        )
