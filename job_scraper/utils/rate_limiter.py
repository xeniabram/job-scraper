"""Rate limiting and politeness utilities."""

import asyncio
from datetime import datetime, timedelta

from loguru import logger


class RateLimiter:
    """Rate limiter to ensure polite scraping behavior."""

    def __init__(
        self,
        daily_limit: int,
        delay: int
    ):
        """Initialize rate limiter.

        Args:
            daily_limit: Maximum number of requests per day
            min_delay: Minimum delay between requests in seconds
            max_delay: Maximum delay between requests in seconds
        """
        self.daily_limit = daily_limit
        self.delay = delay

        self._request_count = 0
        self._reset_time = datetime.now() + timedelta(days=1)
        self._last_request_time = datetime.now()

    async def wait(self) -> None:
        """Wait appropriate time before next request with random delay."""
        # Check if we've hit daily limit
        if self._request_count >= self.daily_limit:
            if datetime.now() < self._reset_time:
                wait_seconds = (self._reset_time - datetime.now()).total_seconds()
                logger.warning(
                    f"Daily limit of {self.daily_limit} reached. "
                    f"Waiting {wait_seconds:.0f} seconds until reset."
                )
                await asyncio.sleep(wait_seconds)
                self._reset_counter()

        # Add random delay between requests

        # Ensure minimum time has passed since last request
        time_since_last = (datetime.now() - self._last_request_time).total_seconds()
        if time_since_last < self.delay:
            await asyncio.sleep(self.delay - time_since_last)

        self._last_request_time = datetime.now()
        self._request_count += 1

        logger.debug(f"Rate limiter: {self._request_count}/{self.daily_limit} requests today")

    def _reset_counter(self) -> None:
        """Reset daily counter."""
        self._request_count = 0
        self._reset_time = datetime.now() + timedelta(days=1)
        logger.info("Rate limiter counter reset")

    @property
    def remaining_requests(self) -> int:
        """Get number of remaining requests for today."""
        return max(0, self.daily_limit - self._request_count)

    def is_limit_reached(self) -> bool:
        """Check if daily limit has been reached."""
        return self._request_count >= self.daily_limit
