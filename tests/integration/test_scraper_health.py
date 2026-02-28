"""Live HTTP health checks — verify each scraper can fetch and parse real data.

Run manually or on a schedule:
    pytest -m integration -s

Each test prints the full parsed job to stdout for manual review.
In CI (GitHub Actions), results are also saved to tests/integration/results/ and
uploaded as workflow artifacts so you can review them over time.
Sentry Cron Monitors track OK/error status per scraper (when SENTRY_DSN is set).
Monitors are auto-created in Sentry with a 3-day interval schedule.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sentry_sdk

from job_scraper.schema import JobData
from job_scraper.scraper.justjoinit_scraper import JustJoinItScraper
from job_scraper.scraper.nofluff_scraper import NoFluffScraper
from job_scraper.scraper.protocol_scraper import ProtocolScraper

RESULTS_DIR = Path(__file__).parent / "results"

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

    if os.environ.get("CI"):
        _save_result(name, scraper_cls.__name__, urls[0], job)


def _save_result(name: str, scraper_name: str, url: str, job: JobData) -> None:
    result_dir = RESULTS_DIR / name
    result_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    result_file = result_dir / f"{timestamp}.json"
    result_file.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "scraper": scraper_name,
                "url": str(url),
                "job": json.loads(job.model_dump_json()),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
