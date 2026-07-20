"""
Shared async HTTP layer. Every scraper goes through this so retry/backoff/
concurrency behavior is consistent and centrally tunable.

Design notes for interview:
- Uses a single aiohttp.ClientSession per crawl run (connection pooling).
- A global asyncio.Semaphore caps concurrency -- this is what lets us say
  "scales to 500k records via infra, not code": raise SCRAPER_MAX_CONCURRENCY
  and add worker nodes, the code is unchanged.
- Exponential backoff with jitter on 429/5xx prevents thundering-herd
  retries when a target starts rate limiting many workers at once.
"""
import asyncio
import logging
import random
from typing import Optional
from wsgiref import headers

import aiohttp

from config.settings import SCRAPER

logger = logging.getLogger("graphone.http")


class FetchResult:
    def __init__(self, url: str, status: int, text: Optional[str], error: Optional[str] = None):
        self.url = url
        self.status = status
        self.text = text
        self.error = error

    @property
    def ok(self) -> bool:
        return self.error is None and self.text is not None


class AsyncHttpClient:
    def __init__(self, max_concurrency: int = SCRAPER.max_concurrency):
        self._sem = asyncio.Semaphore(max_concurrency)
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=SCRAPER.request_timeout_s)
        self._session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(self, *exc):
        if self._session:
            await self._session.close()

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(SCRAPER.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def fetch(self, url: str, method: str = "GET", **kwargs) -> FetchResult:
        """Fetch a URL with retry + exponential backoff + jitter on 429/5xx."""
        last_error = None
        passed_headers = kwargs.pop('headers', {})
        merged_headers = {**self._headers(), **passed_headers}
        for attempt in range(SCRAPER.max_retries + 1):
            async with self._sem:
                try:
                    async with self._session.request(
                        method, url, headers=merged_headers, **kwargs
                    ) as resp:
                        if resp.status == 429:
                            retry_after = resp.headers.get("Retry-After")
                            wait = float(retry_after) if retry_after else self._backoff(attempt)
                            logger.warning(f"429 on {url}, backing off {wait:.1f}s (attempt {attempt+1})")
                            last_error = "rate_limited"
                            await asyncio.sleep(wait)
                            continue
                        if resp.status >= 500:
                            wait = self._backoff(attempt)
                            logger.warning(f"{resp.status} on {url}, retrying in {wait:.1f}s")
                            last_error = f"server_error_{resp.status}"
                            await asyncio.sleep(wait)
                            continue
                        if resp.status == 404:
                            return FetchResult(url, resp.status, None, error="not_found")
                        if resp.status >= 400:
                            text = await resp.text()
                            return FetchResult(url, resp.status, text, error=f"client_error_{resp.status}")

                        text = await resp.text()
                        return FetchResult(url, resp.status, text)

                except asyncio.TimeoutError:
                    last_error = "timeout"
                    wait = self._backoff(attempt)
                    logger.warning(f"Timeout on {url}, retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)
                except aiohttp.ClientError as e:
                    last_error = str(e)
                    wait = self._backoff(attempt)
                    logger.warning(f"ClientError on {url}: {e}, retrying in {wait:.1f}s")
                    await asyncio.sleep(wait)

        return FetchResult(url, 0, None, error=last_error or "max_retries_exceeded")

    @staticmethod
    def _backoff(attempt: int) -> float:
        base = min(SCRAPER.base_backoff_s * (2 ** attempt), SCRAPER.max_backoff_s)
        jitter = random.uniform(0, base * 0.3)
        return base + jitter

    async def fetch_json(self, url, **kwargs) -> tuple[Optional[dict], Optional[str]]:
        result = await self.fetch(url, **kwargs)
        if not result.ok:
            return None, result.error
        try:
            import json
            return json.loads(result.text), None
        except Exception as e:
            snippet = (result.text or "")[:200].replace("\n", " ")
            return None, f"json_parse_error: {e} | status={result.status} body={snippet!r}"