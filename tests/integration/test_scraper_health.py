"""Live HTTP health checks — verify each scraper can fetch and parse real data.

Run manually or on a schedule:
    pytest -m integration

In CI (GitHub Actions), results are written to the job summary for inline review.
Sentry Cron Monitors track OK/error status per scraper (when SENTRY_DSN is set).
Monitors are auto-created in Sentry with a 3-day interval schedule.
"""

import os

import pytest
import sentry_sdk

from job_scraper.schema import JobData
from job_scraper.scraper.justjoinit_scraper import JustJoinItScraper
from job_scraper.scraper.nofluff_scraper import NoFluffScraper
from job_scraper.scraper.protocol_scraper import ProtocolScraper

SCRAPERS = [
    (
        NoFluffScraper,
        [{"seniority": {"senior"}, "category": {"ux"}}],
    ),
    (
        JustJoinItScraper,
        [{"technology": "c", "experience_level": ["senior"]}],
    ),
    (
        ProtocolScraper,
        [{"technologies_must": {"ios"}}],
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize("scraper_cls,config", SCRAPERS, ids=lambda x: getattr(x, "__name__", ""))
async def test_scraper_fetches_and_parses_one_job(scraper_cls, config):
    name = scraper_cls.__name__.replace("Scraper", "").lower()

    with sentry_sdk.monitor(
        monitor_slug=f"scraper-health-{name}",
        monitor_config={
            "schedule": {"type": "interval", "value": 3, "unit": "day"},
            "checkin_margin": 5,
            "max_runtime": 10,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
        },
    ):
        async with scraper_cls(config) as scraper:
            urls = []
            async for url in scraper.get_job_links(max_jobs=1, url_cache=set()):
                urls.append(url)

            assert len(urls) != 0, f"{scraper_cls.__name__}: listing returned no URLs — selector may be broken or site blocked"
            assert len(urls) < 2, f"{scraper_cls.__name__}: listing returned more urls than expected. check your limit implementation"

            job = await scraper.view_job(urls[0])

        assert isinstance(job, JobData)
        assert job.title, f"{scraper_cls.__name__}: job title is empty"
        assert job.company, f"{scraper_cls.__name__}: job company is empty"
        assert any(job.description.values()), f"{scraper_cls.__name__}: job description is entirely empty"

    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        _write_summary(summary, scraper_cls.__name__, urls[0], job)


def _write_summary(summary_path: str, scraper_name: str, url: str, job: JobData) -> None:
    lines = [
        f"## {scraper_name}",
        f"**{job.title}** @ {job.company}  ",
        f"[{url}]({url})",
        "",
    ]
    for key, value in job.description.items():
        if not value:
            continue
        value = str(value)
        preview = value[:150].replace("\n", " ")
        if len(value) > 150:
            full = value.replace("\n", " ")
            lines.append(f"<details><summary>{key}: {preview}…</summary>\n\n{full}\n\n</details>\n")
        else:
            lines.append(f"**{key}:** {preview}  ")

    lines.append("")
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
