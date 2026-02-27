"""Main orchestration logic for the job scraper.

Supports two independent phases:
  - scrape: Browser automation only, saves jobs to SQLite (no LLM)
  - filter: LLM filtering only, reads from SQLite (no browser)
  - run: Sequential scrape then filter (never simultaneous)
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Container

import psutil
from loguru import logger

from job_scraper.config import settings
from job_scraper.exceptions import GetJobException, GetJobListingException, SourceParsingError
from job_scraper.llm import JobFilter
from job_scraper.schema import JobData, MatchedJob
from job_scraper.scraper import AVAILABLE_SOURCES, Scraper, scrapers
from job_scraper.storage import ResultsStorage
from job_scraper.utils import RateLimiter, setup_logger


def _log_resources() -> None:
    """Log current process CPU and memory usage."""
    proc = psutil.Process(os.getpid())
    mem = proc.memory_info().rss / 1024 / 1024  # MB
    cpu = proc.cpu_percent(interval=0.1)
    logger.info(f"[resources] CPU: {cpu:.0f}% | RAM: {mem:.0f}MB")


def _is_excluded_company(company: str, excluded: list[str]) -> bool:
    """Case-insensitive substring match against excluded company list."""
    company_lower = company.lower()
    return any(exc.lower() == company_lower for exc in excluded)


async def _scrape_jobs(
    job_board: Scraper,
    rate_limiter: RateLimiter,
    storage: ResultsStorage,
    max_jobs: int,
    excluded_companies: Container[str],
) -> tuple[int, int, list[str]]:
    """Scrape jobs and save to SQLite. No LLM involved.
    Raises:
        RuntimeError
        GetJobListingException
        GetJobException
        SourceParsingError
        """
    _log_resources()

    scraped_count = 0
    excluded_count = 0
    blacklisted_companies_seen = []
    async for job_url in job_board.get_job_links(max_jobs=max_jobs, url_cache=storage.url_cache):
        logger.debug(f"\nScraping job at {job_url.split("?")[0]}")
        
        await rate_limiter.wait()
        job_data = await job_board.view_job(job_url)

        company = job_data.company
        if company.lower() in excluded_companies:
            logger.info(f"Skipping excluded company: {company}")
            excluded_count += 1
            blacklisted_companies_seen.append(company)
            continue

        storage.save_job(job_data)
        scraped_count += 1

        if scraped_count % 5 == 0:
            _log_resources()

    return  (scraped_count, excluded_count, blacklisted_companies_seen)



async def scrape_main(
    limit: int | None = None,
    sources: list[str] = AVAILABLE_SOURCES,
) -> None:
    """Scrape-only phase: extract jobs, save to SQLite. No LLM.

    Args:
        source: Which job board to scrape.
                "protocol"   → theprotocol.it  (HTTP, no browser)
                "justjoinit" → justjoin.it      (HTTP, no browser)
    """
    config = settings.load_config()

    storage = ResultsStorage(settings.data_dir)
    rate_limiter = RateLimiter(
        delay=config.scraper.fetch_interval,
    )

    excluded_companies = config.requirements.get("excluded_companies", [])
    scraped, excluded, blacklisted_companies_seen = 0, 0, []
    for source in sources:
        logger.info("="*10)
        logger.info(f"Scraping from {source}")
        logger.info("-"*10)
        async with scrapers[source](config=config.search[source]) as job_board:
            try:
                s, e, ec = await _scrape_jobs(
                    job_board=job_board, 
                    rate_limiter=rate_limiter, 
                    storage=storage, 
                    max_jobs=limit or config.scraper.session_limit_per_board, 
                    excluded_companies=excluded_companies)
                scraped += s
                excluded += e
                blacklisted_companies_seen.extend(ec)
            except (GetJobListingException, GetJobException, SourceParsingError) as e:
                logger.error(f"Failed scraping source {source} due to: {e}")

    pending = storage.pending_count()
    logger.info("\n" + "=" * 10)
    logger.info("Scraping Complete")
    logger.info(f"Pending in queue: {pending}")
    logger.info(f"Total URLs seen (cache): {len(storage.url_cache)}")
    if excluded:
        logger.info(f"Encountered blacklisted companies were {",".join(blacklisted_companies_seen)}")


async def filter_main(limit: int | None = None) -> None:
    """Filter + optimize phase: read SQLite queue, send to LLM, remove from queue."""
    config = settings.load_config()

    results = ResultsStorage(settings.data_dir)

    job_filter = JobFilter(
        model=settings.openai_model,
        requirements=config.requirements,
        api_key=settings.openai_api_key,
        profile_log=settings.logs_dir / "api_profile.jsonl",
    )

    pending_jobs = results.load_pending_jobs(limit)

    if not pending_jobs:
        logger.info("No jobs to filter. Run 'scrape' first.")
        return

    if limit:
        pending_jobs = pending_jobs[:limit]

    total = len(pending_jobs)
    logger.info(f"Filtering {total} jobs...")

    matched_count = 0
    rejected_count = 0
    semaphore = asyncio.Semaphore(90)

    async def filter_one(job_data: JobData, index: int) -> None:
        nonlocal matched_count, rejected_count
        async with semaphore:
            logger.info(f"\n[{index}/{total}] Filtering: {job_data.title}")

            filter_result = await job_filter.filter_job(job_data)

            if filter_result.match:
                cv_result = await job_filter.optimize_cv(job_data, config.cv_optimization)
                results.save_matched_job(
                    job=job_data,
                    cv=cv_result,
                    match_pct=filter_result.skillset_match_percent,
                )
                matched_count += 1
            else:
                results.save_rejected_job(
                    job=job_data,
                    match_pct=filter_result.skillset_match_percent,
                    reason=filter_result.reason,
                )
                rejected_count += 1

    await asyncio.gather(*(filter_one(job_data, i + 1) for i, job_data in enumerate(pending_jobs)))

    # Summary
    remaining = results.pending_count()
    logger.info("\n" + "=" * 10)
    logger.info("Filtering Complete")
    logger.info("=" * 10)
    logger.info(f"This session: {matched_count} matched, {rejected_count} rejected")
    logger.info(f"Remaining in queue: {remaining}")


async def optimize_main(limit: int | None = None) -> None:
    """Optimize CV sections for already-matched jobs. Reads results.db, writes back cv_about_me/cv_keywords."""
    config = settings.load_config()

    if not config.cv_optimization:
        logger.error("No cv_optimization section in config.yaml — nothing to do.")
        return
    results = ResultsStorage(settings.data_dir)

    unoptimized_jobs = results.load_unoptimized_matched(limit)
    if not unoptimized_jobs:
        logger.info("All matched jobs are already optimized.")
        return

    total = len(unoptimized_jobs)
    logger.info(f"Optimizing CV for {total} matched jobs...")

    job_filter = JobFilter(
        model=settings.openai_model,
        requirements=config.requirements,
        api_key=settings.openai_api_key,
        profile_log=settings.logs_dir / "api_profile.jsonl",
    )

    semaphore = asyncio.Semaphore(150)
    done = 0
    skipped = 0

    async def optimize_one(job_data: MatchedJob, index: int) -> None:
        nonlocal done, skipped
        async with semaphore:
            if not job_data:
                logger.warning(f"[{index}/{total}] No scraped data for {job_data.url} — skipping")
                skipped += 1
                return

            logger.info(f"[{index}/{total}] Optimizing: {job_data.title}")
            cv_result = await job_filter.optimize_cv(job_data, config.cv_optimization)
            if cv_result is None:
                skipped += 1
                return
            results.update_cv(job_data.url, cv_result.about_me, cv_result.keywords)
            done += 1

    await asyncio.gather(*(optimize_one(job, i + 1) for i, job in enumerate(unoptimized_jobs)))

    logger.info("\n" + "=" * 10)
    logger.info("Optimization Complete")
    logger.info("=" * 10)
    logger.info(f"Optimized: {done} | Skipped (no scraped data): {skipped}")
    

def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        prog="job-scraper",
        description="AI-powered job scraper with LLM filtering",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scrape
    scrape_parser = subparsers.add_parser("scrape", help="Scrape jobs to SQLite (no LLM)")
    scrape_parser.add_argument("--limit", type=int, help="Max jobs to scrape")
    scrape_parser.add_argument("--no-headless", dest="headless", action="store_false")
    scrape_parser.add_argument(
        "--sources",
        choices=["protocol", "justjoin", "nofluff", "local"],
        nargs="*",
        default=AVAILABLE_SOURCES,
        help="Job board(s) to scrape. Example: --sources protocol justjoin",
    )

    # filter
    filter_parser = subparsers.add_parser("filter", help="Filter scraped jobs with LLM")
    filter_parser.add_argument("--limit", type=int, help="Max jobs to filter this run")


    # optimize — generate CV sections for already-matched jobs
    optimize_parser = subparsers.add_parser(
        "optimize", help="Generate optimized CV sections for matched jobs (reads results.db)"
    )
    optimize_parser.add_argument("--limit", type=int, help="Max jobs to optimize this run")

    # review — interactive UI to mark matched jobs as applied / review rejected jobs
    review_parser = subparsers.add_parser("review", help="Open UI to review jobs")
    review_parser.add_argument(
        "--rejected",
        action="store_true",
        default=False,
        help="Review LLM-rejected jobs and label them for LLM tuning",
    )

    # add — manually add a job to the filter queue via a GUI form
    subparsers.add_parser("add", help="Open form to manually add a job to the filter queue")

    # reprocess — reset filtered_at so filter can run again on all jobs
    subparsers.add_parser("reprocess", help="Reset all filtered jobs so they can be re-filtered")


    # reprocess — reset filtered_at so filter can run again on all jobs
    subparsers.add_parser("run", help="cron job entrypoint")

    return parser.parse_args()


async def main(args: argparse.Namespace) -> None:
    """Main async entry point."""
    setup_logger(settings.logs_dir)

    match args.command:
        case "scrape":
            await scrape_main(
                limit=args.limit,
                sources=args.sources,
            )
        case "filter":
            await filter_main(limit=args.limit)
        case "optimize":
            await optimize_main(limit=args.limit)
        case _:
            logger.error("Unknown command. Use: scrape, filter, optimize, run, or reprocess")



def cli() -> None:
    """CLI entry point."""
    args = parse_args()

    if not args.command:
        parse_args()  # triggers help
        print("\nPlease specify a command: scrape, filter, optimize, review, or run")
        print("  Example: uv run job-scraper scrape --limit 20")
        sys.exit(1)

    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
