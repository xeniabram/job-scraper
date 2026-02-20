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
from job_scraper.exceptions import GetJobException
from job_scraper.llm import JobFilter
from job_scraper.scraper import JobBoard, scrapers
from job_scraper.storage import ResultsStorage
from job_scraper.utils import RateLimiter, setup_logger

AVAILABLE_SOURCES = list(scrapers.keys())

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
    job_board: JobBoard,
    rate_limiter: RateLimiter,
    storage: ResultsStorage,
    max_jobs: int,
    excluded_companies: list[str],
) -> None:
    """Scrape jobs and save to SQLite. No LLM involved."""
    # Get job links — limit applies to unseen jobs only
    max_jobs = min(max_jobs, rate_limiter.remaining_requests)
    new_jobs = await job_board.get_job_links(max_jobs=max_jobs, url_cache=storage.url_cache)
    logger.info(f"Found {len(new_jobs)} new jobs to scrape")

    if not new_jobs:
        logger.info("No new jobs to scrape")
        return

    _log_resources()

    scraped_count = 0
    excluded_count = 0
    for i, job_url in enumerate(new_jobs, 1):
        if rate_limiter.is_limit_reached():
            logger.warning("Daily limit reached!")
            break

        logger.info(f"\n[{i}/{len(new_jobs)}] Scraping job...")

        await rate_limiter.wait()
        try:
            job_data = await job_board.view_job(job_url)
        except GetJobException:
            storage.save_failed_job(job_url)
            continue

        company = job_data.company
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
        daily_limit=limit or config.scraper.daily_limit,
        delay=config.scraper.fetch_interval,
    )

    max_jobs = limit or config.scraper.daily_limit
    excluded_companies: list[str] = config.requirements.get("excluded_companies", [])
    for source in sources:
        logger.info("="*60)
        logger.info(f"Scraping from {source}")
        logger.info("-"*60)
        async with scrapers[source](delay=config.scraper.fetch_interval, config=config.search[source]) as job_board:
            await _scrape_jobs(job_board, rate_limiter, storage, max_jobs, excluded_companies)


async def filter_main(limit: int | None = None) -> None:
    """Filter-only phase: read SQLite queue, send to LLM (up to 150 concurrent), remove from queue. No browser."""
    config = settings.load_config()

    results = ResultsStorage(settings.data_dir)

    job_filter = JobFilter(
        model=settings.openai_model,
        requirements=config.requirements,
        api_key=settings.openai_api_key,
        profile_log=settings.logs_dir / "api_profile.jsonl",
    )

    pending_jobs = results.load_pending_jobs()

    if not pending_jobs:
        logger.info("No jobs to filter. Run 'scrape' first.")

    if limit:
        pending_jobs = pending_jobs[:limit]

    total = len(pending_jobs)
    logger.info(f"Filtering {total} jobs...")

    matched_count = 0
    rejected_count = 0
    semaphore = asyncio.Semaphore(90)

    async def filter_one(job_data: dict[str, Any], index: int) -> None:
        nonlocal matched_count, rejected_count
        async with semaphore:
            logger.info(f"\n[{index}/{total}] Filtering: {job_data.get('title', 'Unknown')}")

            filter_result = await job_filter.filter_job(job_data)

            if filter_result.match:
                cv: dict[str, str] = {}
                if config.cv_optimization:
                    cv_result = await job_filter.optimize_cv(job_data, config.cv_optimization)
                    cv = {"about_me": cv_result.about_me, "keywords": cv_result.keywords}

                await results.save_matched_job(
                    url=job_data["url"],
                    title=job_data.get("title", ""),
                    company=job_data.get("company", ""),
                    skillset_match_percent=filter_result.skillset_match_percent,
                    cv=cv,
                )
                matched_count += 1
                logger.success(
                    f"MATCHED: {job_data.get('title', 'Unknown')} (skillset: {filter_result.skillset_match_percent}%)"
                )
            else:
                await results.save_rejected_job(
                    url=job_data["url"],
                    role=job_data.get("title", ""),
                    reason=filter_result.reason,
                    skillset_match_percent=filter_result.skillset_match_percent,
                )
                rejected_count += 1

            results.mark_processed(job_data["url"])

    await asyncio.gather(*(filter_one(job_data, i + 1) for i, job_data in enumerate(pending_jobs)))

    # Summary
    remaining = results.pending_count()
    logger.info("\n" + "=" * 60)
    logger.info("Filtering Complete")
    logger.info("=" * 60)
    logger.info(f"This session: {matched_count} matched, {rejected_count} rejected")
    logger.info(f"Remaining in queue: {remaining}")


async def optimize_main(limit: int | None = None) -> None:
    """Optimize CV sections for already-matched jobs. Reads results.db, writes back cv_about_me/cv_keywords."""
    config = settings.load_config()

    if not config.cv_optimization:
        logger.error("No cv_optimization section in config.yaml — nothing to do.")

    results = ResultsStorage(settings.data_dir)

    urls = results.load_unoptimized_matched_urls()
    if not urls:
        logger.info("All matched jobs are already optimized.")

    if limit:
        urls = urls[:limit]

    total = len(urls)
    logger.info(f"Optimizing CV for {total} matched jobs...")

    job_filter = JobFilter(
        model=settings.openai_model,
        requirements=config.requirements,
        api_key=settings.openai_api_key,
        profile_log=settings.logs_dir / "api_profile.jsonl",
    )

    all_scraped = {job["url"]: job for job in results.load_all_jobs()}

    semaphore = asyncio.Semaphore(150)
    done = 0
    skipped = 0

    async def optimize_one(url: str, index: int) -> None:
        nonlocal done, skipped
        async with semaphore:
            job_data = all_scraped.get(url)
            if not job_data:
                logger.warning(f"[{index}/{total}] No scraped data for {url} — skipping")
                skipped += 1
                return

            logger.info(f"[{index}/{total}] Optimizing: {job_data.get('title', url)}")
            cv_result = await job_filter.optimize_cv(job_data, config.cv_optimization)
            results.update_cv(url, cv_result.about_me, cv_result.keywords)
            done += 1

    await asyncio.gather(*(optimize_one(url, i + 1) for i, url in enumerate(urls)))

    logger.info("\n" + "=" * 60)
    logger.info("Optimization Complete")
    logger.info("=" * 60)
    logger.info(f"Optimized: {done} | Skipped (no scraped data): {skipped}")


async def run_main(sources: list[str], limit: int | None = None, ) -> None:
    """Combined mode: scrape first (closes browser), then filter. Never simultaneous."""
    logger.info("Phase 1: Scraping...")
    await scrape_main(limit=limit, sources=sources)
    logger.info("\nPhase 2: Filtering...")
    await filter_main(limit=limit)


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
        choices=["protocol", "justjoin", "nofluff"],
        nargs="*",
        default=AVAILABLE_SOURCES,
        help="Job board(s) to scrape. Example: --sources protocol justjoin",
    )

    # filter
    filter_parser = subparsers.add_parser("filter", help="Filter scraped jobs with LLM")
    filter_parser.add_argument("--limit", type=int, help="Max jobs to filter this run")

    # run (combined, sequential)
    run_parser = subparsers.add_parser("run", help="Scrape then filter (sequential)")
    run_parser.add_argument("--limit", type=int, help="Max jobs to process")
    run_parser.add_argument(
        "--source",
        choices=["protocol", "justjoinit"],
        default="protocol",
        help="Job board to scrape: 'protocol' (theprotocol.it, default) or 'justjoinit' (justjoin.it)",
    )

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

    # reprocess — reset filtered_at so filter can run again on all jobs
    subparsers.add_parser("reprocess", help="Reset all filtered jobs so they can be re-filtered")

    return parser.parse_args()


async def main(args: argparse.Namespace) -> None:
    """Main async entry point."""
    setup_logger(settings.logs_dir)

    logger.info("=" * 60)
    logger.info(f"Job Scraper — {args.command}")
    logger.info("=" * 60)

    if args.command == "scrape":
        await scrape_main(
            limit=args.limit,
            sources=args.sources,
        )
    elif args.command == "filter":
        await filter_main(limit=args.limit)
    elif args.command == "optimize":
        await optimize_main(limit=args.limit)
    elif args.command == "run":
        await run_main(limit=args.limit, sources=args.sources)
    elif args.command == "reprocess":
        count = ResultsStorage(settings.data_dir).reset_processed()
        logger.info(f"Reset {count} jobs — run 'filter' to reprocess them")
    else:
        logger.error("Unknown command. Use: scrape, filter, optimize, run, or reprocess")



def cli() -> None:
    """CLI entry point."""
    args = parse_args()

    if not args.command:
        parse_args()  # triggers help
        print("\nPlease specify a command: scrape, filter, optimize, review, or run")
        print("  Example: uv run job-scraper scrape --limit 20")
        sys.exit(1)

    if args.command == "review":
        if args.rejected:
            from job_scraper.ui.rejected_review import run_rejected_review
            run_rejected_review()
        else:
            from job_scraper.ui.review import run_review
            run_review()
        sys.exit(0)

    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
