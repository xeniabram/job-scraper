"""theprotocol.it job board scraper — lightweight HTTP implementation.

No browser required. Uses curl_cffi to bypass Cloudflare and BeautifulSoup
to parse HTML via stable data-test attributes.
"""

from collections.abc import Callable, Generator
from typing import Annotated, Literal

from bs4 import BeautifulSoup
from loguru import logger
from pydantic import PlainSerializer, model_validator

from job_scraper.exceptions import SourceParsingError
from job_scraper.schema import JobData
from job_scraper.scraper.base import BaseParams, BaseScraper
from job_scraper.utils import text

BASE_URL = "https://theprotocol.it"


def _with_suffix(suffix: str) -> Callable[[set[str] | str], str]:
    def inner(data: set[str] | str) -> str:
        if not data:
            return ""
        if isinstance(data, str):
            return data + suffix
        return ",".join(data) + suffix
    return inner


TechLiteral = set[Literal[
    "node.js", "net", "angular", "aws", "c", "c#", "c++",
    "go", "hibernate", "html", "ios", "java", "rust",
    "sql", "ruby", "react.js", "python", "r", "php",
    "javascript", "android", "typescript"
]]


class Params(BaseParams):
    technologies_must: Annotated[TechLiteral | None, PlainSerializer(_with_suffix(";t"), when_used="unless-none")] = None
    technologies_nice: Annotated[TechLiteral | None, PlainSerializer(_with_suffix(";nt"), when_used="unless-none")] = None
    technologies_not: TechLiteral | None = None
    specializations: Annotated[set[Literal[
        "backend", "frontend", "qa-testing", "security", "devops",
        "helpdesk", "it-admin", "data-analytics-bi", "big-data-science",
        "ux-ui", "ai-ml", "project-management", "fullstack", "mobile",
        "embedded", "gamedev", "architecture", "business-analytics",
        "agile", "product-management", "sap-erp", "system-analytics"
    ]] | None, PlainSerializer(_with_suffix(";sp"), when_used="unless-none")] = None
    seniority_levels: Annotated[
        set[Literal[
            "trainee", "assistant", "junior", "mid",
            "senior", "expert", "lead", "manager",
            "head", "executive"
        ]] | None,
        PlainSerializer(_with_suffix(";p"), when_used="unless-none")
    ] = None
    contracts: Annotated[list[Literal[
        "kontrakt-b2b", "umowa-o-prace", "umowa-zlecenie",
        "umowa-o-dzielo", "umowa-na-zastepstwo", "umowa-agencyjna",
        "umowa-o-prace-tymczasowa", "umowa-o-staz-praktyki"
    ]] | None, PlainSerializer(_with_suffix(";c"), when_used="unless-none")] = None
    work_modes: Annotated[
        set[Literal["zdalna", "hybrydowa", "stacjonarna"]] | None,
        PlainSerializer(_with_suffix(";rw"), when_used="unless-none")
    ] = None
    locations: Annotated[
        set[str] | None,
        PlainSerializer(_with_suffix(";wp"), when_used="unless-none")
    ] = None
    salary: Annotated[int | None, PlainSerializer(_with_suffix(";s"), when_used="unless-none")] = None
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
    
    def build_listing_url(self) -> str:
        query = self.query_params
        return BASE_URL + "/filtry/" + self.segments + (f"?{query}" if query else "")


class ProtocolScraper(BaseScraper):
    """Scraper for theprotocol.it using HTTP requests + HTML parsing."""
    _param_type = Params

    def _extract_job_urls(self, source: str) -> Generator[str]:
        soup = BeautifulSoup(source, "html.parser")
        for card in soup.select('a[data-test="list-item-offer"]'):
            yield (BASE_URL + str(card["href"])).split("?")[0]

    def _extract_job_data(self, job_url: str, source: str) -> JobData:
        """Parse a job detail page and return structured data."""
        soup = BeautifulSoup(source, "html.parser")

        title = text('[data-test="text-offerTitle"]', soup)
        company = text('[data-test="text-offerEmployer"]', soup)
        location = text('[data-test="text-primaryLocation"]', soup)
        seniority = text('[data-test="content-positionLevels"]', soup)
        work_mode = text('[data-test="content-workModes"]', soup)

        # Contracts — one block per contract type offered
        contracts: list[dict[str, str]] = []
        for block in soup.select('[data-test="section-contract"]'):
            contracts.append(
                {
                    "salary": text('[data-test="text-contractSalary"]', block),
                    "units": text('[data-test="text-contractUnits"]', block),
                    "period": text('[data-test="text-contractTimeUnits"]', block),
                    "type": text('[data-test="text-contractName"]', block),
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

        if not title or not company or not technologies or not requirements:
            raise SourceParsingError("was not able to extract essential information")

        logger.info(f"Viewed: {title or 'Unknown'} @ {company or 'Unknown'}")
        return JobData(
            url=job_url,
            title=title,
            company=company,
            description={
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
