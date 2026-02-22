from collections.abc import Iterable
from typing import Annotated, Literal

from bs4 import BeautifulSoup
from loguru import logger
from pydantic import Field, PlainSerializer

from job_scraper.schema import JobData
from job_scraper.scraper.base import BaseParams, BaseScraper

BASE_URL = "https://nofluffjobs.com"

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

class Params(BaseParams):
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
        PlainSerializer(serialize_joined)] = Field(default_factory=lambda: ["praca-zdalna"])


    @property
    def query_params(self) -> str:
        import urllib.parse
        data = self.model_dump()
        params = " ".join(f"{k}={v}" for k, v in data.items() if v is not None)
        return f"criteria={urllib.parse.quote(params, safe=",")}"

    def build_listing_url(self) -> str:
        if p := self.query_params:
            return f"{BASE_URL}/pl?{p}"
        return BASE_URL
    


class NoFluffScraper(BaseScraper):
    """Scraper for theprotocol.it using HTTP requests + HTML parsing."""
    _param_type = Params

    @staticmethod
    def _extract_job_urls(
        source: str
    ) -> list[str]:
        soup = BeautifulSoup(source, "html.parser")
        return [
            BASE_URL + str(card["href"])
            for card in soup.select("a.posting-list-item")
        ]

    def _extract_job_data(self, job_url: str, source: str) -> JobData:
        """Fetch a job detail page and extract structured data."""
        soup = BeautifulSoup(source, "html.parser")

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