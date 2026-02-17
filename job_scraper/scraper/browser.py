"""Browser automation wrapper with persistent session support."""

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

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
