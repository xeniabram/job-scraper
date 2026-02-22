"""Rate limiting and politeness utilities."""

import asyncio


class RateLimiter:
    """Rate limiter to ensure polite scraping behavior. Can be expanded with more logic if needed"""

    def __init__(
        self,
        delay: int
    ):
        self.delay = delay

    async def wait(self) -> None:
        """Wait appropriate time before next request."""
        await asyncio.sleep(self.delay)