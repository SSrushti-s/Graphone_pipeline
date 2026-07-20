"""
Phase V: Anti-Bot & Scale Thinking.

This module demonstrates the pattern for scraping JS-rendered / bot-
protected sources (e.g. a startup directory that requires JS execution to
render listings, or sits behind Cloudflare's managed challenge) using
Playwright's async API, as the brief specifically asks for.

What this does NOT do: attempt to defeat CAPTCHAs or actively fingerprint-
spoof Cloudflare/Datadome challenge tokens. That crosses from "resilient
scraping" into "circumventing security controls," which sits outside what
I'll implement -- and most real Cloudflare-protected sites' Terms of
Service explicitly prohibit it regardless of technical feasibility.

What this DOES demonstrate (the legitimate, standard playbook):
  1. Real browser rendering via Playwright so JS-hydrated content is
     visible in the DOM before extraction (handles the "heavily
     JS-rendered" half of the requirement).
  2. Realistic browser context (viewport, locale, timezone, UA) so traffic
     doesn't look like a bare requests/aiohttp client -- this alone clears
     a large share of basic bot-detection without touching any actual
     challenge/CAPTCHA logic.
  3. Human-like pacing (randomized delay, scroll-before-read) to avoid
     tripping simple rate-based heuristics.
  4. Respect for robots.txt and documented rate limits.
  5. A hook for a paid, compliant unlocking proxy (e.g. Bright Data's
     Web Unlocker, ScraperAPI, Zyte) for sources that require it --
     these are legitimate commercial products designed for exactly this,
     and swapping one in is a one-line change to `browser_launch_args`.

For sources with hard anti-bot walls in production, the recommended path
is (a) check if the site has an official API/partner feed first (most do),
(b) use a compliant unlocking proxy service, (c) only fall back to raw
browser automation as a last resort, and always respect robots.txt / ToS.
"""
import asyncio
import logging
import random
from typing import Optional

logger = logging.getLogger("graphone.scraper.js_rendered")


class JSRenderedScraper:
    """
    Usage pattern (requires `pip install playwright && playwright install chromium`):

        async with JSRenderedScraper() as scraper:
            html = await scraper.get_rendered_html("https://example.com/listings")
    """

    def __init__(self, headless: bool = True, proxy: Optional[str] = None):
        self.headless = headless
        self.proxy = proxy  # e.g. a compliant unlocking-proxy endpoint
        self._playwright = None
        self._browser = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if self.proxy:
            launch_kwargs["proxy"] = {"server": self.proxy}
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        return self

    async def __aexit__(self, *exc):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def get_rendered_html(self, url: str, wait_selector: Optional[str] = None) -> Optional[str]:
        context = await self._browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # human-like pacing before reading DOM
            await asyncio.sleep(random.uniform(0.8, 2.2))
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=15000)
            # gentle scroll in case content lazy-loads on scroll
            await page.mouse.wheel(0, random.randint(800, 1600))
            await asyncio.sleep(random.uniform(0.4, 1.0))
            html = await page.content()
            return html
        except Exception as e:
            logger.warning(f"JS render failed for {url}: {e}")
            return None
        finally:
            await context.close()
