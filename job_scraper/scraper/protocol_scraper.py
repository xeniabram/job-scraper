"""theprotocol.it job board scraper implementation."""

import asyncio
from typing import Any

from loguru import logger

from job_scraper.scraper.browser import Browser


class ProtocolScraper:
    """Job board scraper for theprotocol.it (no authentication required)."""

    # CSS selectors for theprotocol.it
    SELECTORS: dict[str, list[str]] = {
        "job_cards": [
            '[data-test="list-item-offer"]',
        ],
        "title": [
            '[data-test="text-jobTitle"]',
            "h1",
            "h2.tico6j0",
        ],
        "company": [
            'a[href*="/firmy-it/"]',
            '[data-test*="company"]',
            '[class*="company"]',
        ],
        "location": [
            '[data-test*="location"]',
            '[class*="location"]',
        ],
        "description": [
            '[data-test*="description"]',
            "article",
            "main p",
        ],
        "technologies": [
            '[data-test*="tech"]',
            '[data-test*="skill"]',
            '[class*="technology"]',
        ],
    }

    # Modal/popup selectors
    COOKIE_CONSENT_SELECTORS = [
        'button:has-text("Akceptuj")',
        'button:has-text("Zgadzam się")',
        'button:has-text("Accept")',
    ]

    LANGUAGE_SELECTORS = [
        'button:has-text("PL")',
        'button:has-text("Polski")',
    ]

    def __init__(self, browser: Browser):
        self.browser = browser
        self._modals_handled = False

    # ------------------------------------------------------------------
    # Initialization - handle modals
    # ------------------------------------------------------------------

    async def _handle_modals(self) -> None:
        """Handle cookie consent and language selection modals on first visit."""
        if self._modals_handled:
            return

        logger.debug("Checking for modals...")

        # Handle cookie consent
        for selector in self.COOKIE_CONSENT_SELECTORS:
            try:
                button = self.browser.page.locator(selector).first
                if await button.is_visible(timeout=2000):
                    logger.debug(f"Accepting cookies: {selector}")
                    await button.click()
                    await asyncio.sleep(1)
                    break
            except:
                continue

        # Handle language selection
        for selector in self.LANGUAGE_SELECTORS:
            try:
                button = self.browser.page.locator(selector).first
                if await button.is_visible(timeout=2000):
                    logger.debug(f"Selecting language: {selector}")
                    await button.click()
                    await asyncio.sleep(2)
                    break
            except:
                continue

        self._modals_handled = True
        logger.debug("Modals handled")

    # ------------------------------------------------------------------
    # Session / login (not needed for theprotocol.it!)
    # ------------------------------------------------------------------

    async def ensure_logged_in(self) -> bool:
        """theprotocol.it doesn't require authentication - always returns True."""
        logger.info("theprotocol.it doesn't require login - proceeding...")
        return True

    # Backward-compat alias
    login = ensure_logged_in

    # ------------------------------------------------------------------
    # Search URL building
    # ------------------------------------------------------------------

    @staticmethod
    def build_search_url(filters: dict[str, Any] | None = None) -> str:
        """Build a theprotocol.it filter URL.

        Uses the same path segments the site produces when you pick filters
        from its UI:
          - technology  → /filtry/{technology};t    (e.g. "python" → /filtry/python;t)
          - category    → /filtry/{category};sp     (e.g. "backend" → /filtry/backend;sp)
          - contract    → /filtry/{contract};c      (e.g. "kontrakt-b2b" → /filtry/kontrakt-b2b;c)

        Args:
            filters: Dictionary of filters from config.yaml `search:` section.
                - technology: python, java, javascript, etc.
                - category:   backend, frontend, qa-testing, devops, etc.
                - contract:   kontrakt-b2b, umowa-o-prace, etc.
                - remote:     true/false

        Returns:
            Full search URL
        """
        filters = filters or {}

        technology = filters.get("technology", "").strip().lower()
        category = filters.get("category", "").strip().lower()
        contract = filters.get("contract", "").strip().lower()

        segments: list[str] = []
        if category:
            segments.append(f"{category};sp")
        if technology:
            segments.append(f"{technology};t")
        if contract:
            segments.append(f"{contract};c")

        if segments:
            url = "https://theprotocol.it/filtry/" + "/".join(segments)
        else:
            url = "https://theprotocol.it/"

        return url

    # ------------------------------------------------------------------
    # Navigation + link collection
    # ------------------------------------------------------------------

    async def navigate_to_jobs(self, search_params: dict[str, Any]) -> None:
        """Navigate to job search results.

        Args:
            search_params: Dictionary from config.yaml `search:` section.
                - technology: e.g. "python"
                - category: e.g. "backend"
        """
        url = self.build_search_url(search_params)

        logger.info(f"Navigating to: {url}")
        await self.browser.goto(url)
        await asyncio.sleep(2)

        # Handle modals on first visit
        await self._handle_modals()
        await asyncio.sleep(1)

    async def get_job_links(
        self, max_jobs: int = 100, url_cache=None, max_empty_pages: int = 2
    ) -> list[str]:
        """Paginate through search results using ?pageNumber= param.

        Only unseen URLs (not in url_cache) count toward max_jobs.
        Stops when max_empty_pages consecutive pages yield zero new links,
        or when the page content repeats (server loop detection).
        """
        logger.info(f"Collecting up to {max_jobs} new job links...")
        unseen_links: list[str] = []
        base_url = self.browser.page.url.split("?")[0]
        page_num = 1
        prev_page_urls: set[str] = set()
        consecutive_empty = 0

        while len(unseen_links) < max_jobs:
            try:
                if page_num > 1:
                    url = f"{base_url}?pageNumber={page_num}"
                    await self.browser.page.goto(url, wait_until="domcontentloaded")
                    await asyncio.sleep(2)

                job_cards = await self.browser.page.locator('[data-test="list-item-offer"]').all()

                if not job_cards:
                    logger.info(f"No job cards on page {page_num}, done")
                    break

                page_new = 0
                page_seen = 0
                current_page_urls: set[str] = set()
                for card in job_cards:
                    href = await card.get_attribute("href")
                    if href and "/praca/" in href:
                        clean_url = href.split("?")[0]
                        if not clean_url.startswith("http"):
                            clean_url = "https://theprotocol.it" + clean_url
                        current_page_urls.add(clean_url)
                        if url_cache is not None and clean_url in url_cache:
                            page_seen += 1
                        elif clean_url not in unseen_links:
                            unseen_links.append(clean_url)
                            page_new += 1

                logger.info(
                    f"Page {page_num}: {page_new} new, {page_seen} already seen"
                    f" | total new: {len(unseen_links)}"
                )

                if current_page_urls and current_page_urls == prev_page_urls:
                    logger.info("Page identical to previous — server looped back, stopping")
                    break

                if page_new == 0:
                    consecutive_empty += 1
                    if consecutive_empty >= max_empty_pages:
                        logger.info(
                            f"{consecutive_empty} consecutive pages with no new jobs — stopping"
                        )
                        break
                else:
                    consecutive_empty = 0

                prev_page_urls = current_page_urls
                page_num += 1

            except Exception as e:
                logger.warning(f"Error collecting links on page {page_num}: {e}")
                break

        result = unseen_links[:max_jobs]
        logger.info(f"Collected {len(result)} new job links across {page_num} page(s)")
        return result

    # ------------------------------------------------------------------
    # Job detail extraction
    # ------------------------------------------------------------------

    async def _extract_text(self, selectors: list[str], fallback_to_body: bool = False) -> str:
        """Try CSS selectors in order, return first match's text content."""
        for selector in selectors:
            try:
                element = await self.browser.page.query_selector(selector)
                if element:
                    text = await element.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue

        if fallback_to_body:
            try:
                text = await self.browser.page.evaluate("""
                    () => {
                        const main = document.querySelector('main')
                            || document.querySelector('[role="main"]')
                            || document.body;
                        return main ? main.innerText : '';
                    }
                """)
                if text:
                    return text.strip()
            except Exception:
                pass

        return ""

    async def view_job(self, job_url: str) -> dict[str, Any]:
        """View a job posting and extract structured data using data-test selectors."""
        try:
            await self.browser.goto(job_url)
            await asyncio.sleep(2)

            # 1. Core scalar fields via precise data-test attributes
            title = await self._extract_text(['[data-test="text-offerTitle"]'])
            company = await self._extract_text(['[data-test="text-offerEmployer"]'])
            location = await self._extract_text(['[data-test="text-primaryLocation"]'])
            seniority = await self._extract_text(['[data-test="content-positionLevels"]'])
            work_mode = await self._extract_text(['[data-test="content-workModes"]'])

            # Fallback: parse <title> tag when DOM fields are missing
            # Format: "Praca {title}, {company}, {city} - theprotocol.it"
            if not title or not company or not location:
                try:
                    page_title = await self.browser.page.title()
                    if " - theprotocol.it" in page_title:
                        core = (
                            page_title.removeprefix("Praca ")
                            .removesuffix(" - theprotocol.it")
                            .strip()
                        )
                        parts = [p.strip() for p in core.split(", ")]
                        if not title and parts:
                            title = parts[0]
                        if not location and len(parts) >= 3:
                            location = parts[-1]
                        if not company and len(parts) >= 3:
                            company = ", ".join(parts[1:-1])
                        elif not company and len(parts) == 2:
                            company = parts[1]
                except Exception as e:
                    logger.warning(f"Error parsing page title: {e}")

            # 2. Contracts — each block has salary, units, period, contract type
            contracts: list[dict[str, str]] = []
            try:
                contracts = await self.browser.page.evaluate("""
                    () => {
                        const blocks = document.querySelectorAll('[data-test="section-contract"]');
                        return Array.from(blocks).map(block => ({
                            salary:  block.querySelector('[data-test="text-contractSalary"]')?.textContent.trim() || '',
                            units:   block.querySelector('[data-test="text-contractUnits"]')?.textContent.trim() || '',
                            period:  block.querySelector('[data-test="text-contractTimeUnits"]')?.textContent.trim() || '',
                            type:    block.querySelector('[data-test="text-contractName"]')?.textContent.trim() || '',
                        }));
                    }
                """)
            except Exception as e:
                logger.warning(f"Error extracting contracts: {e}")

            # 3. Technologies — required (data-icon=true) vs optional (data-icon=false)
            technologies: list[str] = []
            technologies_optional: list[str] = []
            try:
                tech_data = await self.browser.page.evaluate("""
                    () => {
                        const chips = document.querySelectorAll('[data-test="chip-technology"]');
                        const required = [], optional = [];
                        chips.forEach(chip => {
                            const name = chip.getAttribute('title') || chip.textContent.trim();
                            (chip.getAttribute('data-icon') === 'true' ? required : optional).push(name);
                        });
                        return { required, optional };
                    }
                """)
                technologies = tech_data.get("required", [])
                technologies_optional = tech_data.get("optional", [])
            except Exception as e:
                logger.warning(f"Error extracting technologies: {e}")

            # 4. Requirements, nice-to-haves, responsibilities
            def _extract_section_items(selector: str):
                return self.browser.page.evaluate(f"""
                    () => {{
                        const sec = document.querySelector('{selector}');
                        if (!sec) return [];
                        return Array.from(sec.querySelectorAll('[data-test="text-sectionItem"], li'))
                            .map(el => el.textContent.trim()).filter(t => t.length > 0);
                    }}
                """)

            requirements: list[str] = []
            requirements_optional: list[str] = []
            responsibilities: list[str] = []
            try:
                requirements = await _extract_section_items(
                    '[data-test="section-requirements-expected"]'
                )
                requirements_optional = await _extract_section_items(
                    '[data-test="section-requirements-optional"]'
                )
                responsibilities = await _extract_section_items(
                    '[data-test="section-responsibilities"]'
                )
            except Exception as e:
                logger.warning(f"Error extracting requirements/responsibilities: {e}")

            if not title and not technologies and not requirements:
                logger.warning(f"Could not extract data from {job_url}")

            job_data = {
                "url": job_url,
                "title": title,
                "company": company,
                "location": location,
                "seniority": seniority.strip() if seniority else "",
                "work_mode": work_mode.strip() if work_mode else "",
                "contracts": contracts,
                "technologies": technologies,
                "technologies_optional": technologies_optional,
                "requirements": requirements,
                "requirements_optional": requirements_optional,
                "responsibilities": responsibilities,
            }

            logger.info(f"Viewing job: {title or 'Unknown'} at {company or 'Unknown'}")
            return job_data

        except Exception as e:
            logger.error(f"Error viewing job {job_url}: {e}")
            return {"url": job_url, "error": str(e)}
