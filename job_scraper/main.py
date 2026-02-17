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
from typing import Any

import psutil
from loguru import logger

from job_scraper.config import settings
from job_scraper.llm import JobFilter
from job_scraper.storage import FileStorage, SqliteStorage
from job_scraper.utils import RateLimiter, setup_logger


def _log_resources() -> None:
    """Log current process CPU and memory usage."""
    proc = psutil.Process(os.getpid())
    mem = proc.memory_info().rss / 1024 / 1024  # MB
    cpu = proc.cpu_percent(interval=0.1)
    # Include child processes (Chromium)
    children = proc.children(recursive=True)
    child_mem = sum(c.memory_info().rss for c in children) / 1024 / 1024
    logger.info(f"[resources] CPU: {cpu:.0f}% | RAM: {mem:.0f}MB (+ {child_mem:.0f}MB browser)")


def _is_excluded_company(company: str, excluded: list[str]) -> bool:
    """Case-insensitive substring match against excluded company list."""
    company_lower = company.lower()
    return any(exc.lower() in company_lower for exc in excluded)


async def _scrape_jobs(
    job_board: Any,
    rate_limiter: RateLimiter,
    storage: SqliteStorage,
    max_jobs: int,
) -> int:
    """Scrape jobs and save to SQLite. No LLM involved."""
    # Login
    if not await job_board.login():
        logger.error("Failed to login.")
        return 1

    config = settings.load_config()
    excluded_companies: list[str] = config.requirements.get("excluded_companies", [])

    # Navigate to jobs with filters
    await job_board.navigate_to_jobs(config.search)

    # Get job links — limit applies to unseen jobs only
    max_jobs = min(max_jobs, rate_limiter.remaining_requests)
    new_jobs = await job_board.get_job_links(max_jobs=max_jobs, url_cache=storage.url_cache)
    logger.info(f"Found {len(new_jobs)} new jobs to scrape")

    if not new_jobs:
        logger.info("No new jobs to scrape")
        return 0

    _log_resources()

    scraped_count = 0
    excluded_count = 0
    for i, job_url in enumerate(new_jobs, 1):
        if rate_limiter.is_limit_reached():
            logger.warning("Daily limit reached!")
            break

        logger.info(f"\n[{i}/{len(new_jobs)}] Scraping job...")

        await rate_limiter.wait()

        job_data = await job_board.view_job(job_url)

        company = job_data.get("company", "")
        if excluded_companies and _is_excluded_company(company, excluded_companies):
            logger.info(f"Skipping excluded company: {company}")
            excluded_count += 1
            continue

        storage.save_job(job_data)
        scraped_count += 1

        if scraped_count % 5 == 0:
            _log_resources()

    # Summary
    pending = storage.pending_count()
    logger.info("\n" + "=" * 60)
    logger.info("Scraping Complete")
    logger.info("=" * 60)
    logger.info(
        f"Jobs scraped this session: {scraped_count} (skipped {excluded_count} excluded companies)"
    )
    logger.info(f"Pending in queue: {pending}")
    logger.info(f"Total URLs seen (cache): {len(storage.url_cache)}")

    return 0


async def scrape_main(limit: int | None = None, headless: bool = True, mock_mode: bool = False) -> int:
    """Scrape-only phase: browser + extraction, save to SQLite. No LLM."""
    config = settings.load_config()

    storage = SqliteStorage(settings.data_dir)
    rate_limiter = RateLimiter(
        daily_limit=limit or config.scraper.daily_limit,
        delay=config.scraper.fetch_interval
    )

    max_jobs = limit or config.scraper.daily_limit

    if mock_mode:
        
        from job_scraper.scraper import MockJobBoard

        job_board = MockJobBoard(browser=None)
        return await _scrape_jobs(job_board, rate_limiter, storage, max_jobs)
    else:
        from job_scraper.scraper import Browser
        from job_scraper.scraper.protocol_scraper import ProtocolScraper

        async with Browser(headless=headless) as browser:
            job_board = ProtocolScraper(
                browser=browser,
            )
            return await _scrape_jobs(job_board, rate_limiter, storage, max_jobs)


async def filter_main(limit: int | None = None) -> int:
    """Filter-only phase: read SQLite queue, send to LLM one-by-one, remove from queue. No browser."""
    config = settings.load_config()

    storage = SqliteStorage(settings.data_dir)
    file_storage = FileStorage(settings.data_dir)

    job_filter = JobFilter(
        model=settings.openai_model,
        requirements=config.requirements,
        api_key=settings.openai_api_key,
    )

    pending_jobs = storage.load_pending_jobs()

    if not pending_jobs:
        logger.info("No jobs to filter. Run 'scrape' first.")
        return 0

    if limit:
        pending_jobs = pending_jobs[:limit]

    logger.info(f"Filtering {len(pending_jobs)} jobs one-by-one...")

    matched_count = 0
    rejected_count = 0

    for i, job_data in enumerate(pending_jobs, 1):
        logger.info(f"\n[{i}/{len(pending_jobs)}] Filtering: {job_data.get('title', 'Unknown')}")

        filter_result = await job_filter.filter_job(job_data)

        # Write result to text files, then remove from YAML queue
        if filter_result.match:
            await file_storage.save_matched_job(
                job_data["url"],
                job_data.get("title", ""),
                skillset_match_percent=filter_result.skillset_match_percent,
            )
            matched_count += 1
            logger.success(
                f"MATCHED: {job_data.get('title', 'Unknown')} (skillset: {filter_result.skillset_match_percent}%)"
            )
        else:
            await file_storage.save_rejected_job(
                job_data["url"],
                filter_result.reason,
                skillset_match_percent=filter_result.skillset_match_percent,
            )
            rejected_count += 1

        storage.mark_processed(job_data["url"])

    # Summary
    remaining = storage.pending_count()
    logger.info("\n" + "=" * 60)
    logger.info("Filtering Complete")
    logger.info("=" * 60)
    logger.info(f"This session: {matched_count} matched, {rejected_count} rejected")
    logger.info(f"Remaining in queue: {remaining}")

    return 0


async def run_main(limit: int | None = None) -> int:
    """Combined mode: scrape first (closes browser), then filter. Never simultaneous."""
    logger.info("Phase 1: Scraping...")
    result = await scrape_main(limit=limit)
    if result != 0:
        return result

    logger.info("\nPhase 2: Filtering...")
    return await filter_main(limit=limit)


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
    scrape_parser.add_argument("--headless", action="store_true", default=None)
    scrape_parser.add_argument("--no-headless", dest="headless", action="store_false")

    # filter
    filter_parser = subparsers.add_parser("filter", help="Filter scraped jobs with LLM")
    filter_parser.add_argument("--limit", type=int, help="Max jobs to filter this run")

    # run (combined, sequential)
    run_parser = subparsers.add_parser("run", help="Scrape then filter (sequential)")
    run_parser.add_argument("--limit", type=int, help="Max jobs to process")

    # reprocess — reset filtered_at so filter can run again on all jobs
    subparsers.add_parser("reprocess", help="Reset all filtered jobs so they can be re-filtered")

    return parser.parse_args()


async def main(args: argparse.Namespace) -> int:
    """Main async entry point."""
    try:
        setup_logger(settings.logs_dir)

        logger.info("=" * 60)
        logger.info(f"Job Scraper — {args.command}")
        logger.info("=" * 60)

        if args.command == "scrape":
            return await scrape_main(limit=args.limit, headless=args.headless)
        elif args.command == "filter":
            return await filter_main(limit=args.limit)
        elif args.command == "run":
            return await run_main(limit=args.limit)
        elif args.command == "reprocess":
            storage = SqliteStorage(settings.data_dir)
            count = storage.reset_processed()
            logger.info(f"Reset {count} jobs — run 'filter' to reprocess them")
            return 0
        else:
            logger.error("Unknown command. Use: scrape, filter, run, or reprocess")
            return 1

    except KeyboardInterrupt:
        logger.warning("\nInterrupted by user")
        return 130
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1


def cli() -> None:
    """CLI entry point."""
    args = parse_args()

    if not args.command:
        parse_args()  # triggers help
        print("\nPlease specify a command: scrape, filter, or run")
        print("  Example: uv run job-scraper scrape --limit 20")
        sys.exit(1)

    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    cli()
