"""Browser automation wrapper with persistent session support."""

import asyncio
import random
from pathlib import Path
from typing import Literal

from loguru import logger
from playwright.async_api import BrowserContext, Page, async_playwright


class Browser:
    """Browser wrapper with persistent session and human-like behavior.

    Uses Playwright's persistent context so cookies/session survive across runs.
    First run: user logs in manually. Subsequent runs: session is reused.
    """

    def __init__(self, headless: bool = False, user_data_dir: Path | None = None):
        self.headless = headless
        self.user_data_dir = user_data_dir or Path("data/browser_session")
        self._playwright = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def start(self) -> None:
        """Start browser with persistent context (session reuse)."""
        logger.info("Starting browser...")

        # Ensure session directory exists
        self.user_data_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        # launch_persistent_context saves cookies/localStorage to user_data_dir
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.user_data_dir),
            headless=self.headless,
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )

        # Stealth: hide webdriver flag
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Reuse existing page or create one
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        logger.info("Browser started successfully")

    async def stop(self) -> None:
        """Stop browser (session is saved automatically)."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser stopped (session saved)")

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    async def goto(
        self,
        url: str,
        wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"]
        | None = "domcontentloaded",
    ) -> None:
        logger.debug(f"Navigating to: {url}")
        await self.page.goto(url, wait_until=wait_until)
        await self._random_delay(0.5, 1.5)

    async def type_human(self, selector: str, text: str) -> None:
        """Type text with irregular, human-like timing.

        Mimics real typing: fast bursts, hesitations, occasional pauses.
        """
        await self.page.click(selector)
        await self._random_delay(0.3, 0.7)

        for char in text:
            await self.page.keyboard.type(char)

            # Base delay varies per character
            if char in (" ", "@", ".", "-"):
                # Slight pause at word boundaries / special chars
                await self._random_delay(0.12, 0.35)
            elif random.random() < 0.1:
                # ~10% chance of a longer "thinking" pause
                await self._random_delay(0.3, 0.7)
            else:
                # Normal typing — irregular rhythm
                await self._random_delay(0.04, 0.18)

    async def scroll_slowly(self, distance: int = 300, steps: int = 5) -> None:
        step_size = distance // steps
        for _ in range(steps):
            await self.page.evaluate(f"window.scrollBy(0, {step_size})")
            await self._random_delay(0.2, 0.5)

    async def random_mouse_movement(self) -> None:
        x = random.randint(100, 1800)
        y = random.randint(100, 1000)
        await self.page.mouse.move(x, y)
        await self._random_delay(0.1, 0.3)

    async def _random_delay(self, min_seconds: float, max_seconds: float) -> None:
        delay = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(delay)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
