"""
Startups vertical (Phase I) — Y Combinator company directory.

Uses the yc-oss/api project (https://github.com/yc-oss/api), an unofficial
but legitimate mirror of YC's own Algolia-indexed company data, published
as static JSON on GitHub Pages and refreshed daily via a public GitHub
Actions workflow. This deliberately does NOT scrape ycombinator.com
directly -- ycombinator.com/robots.txt disallows /companies, and this
source respects that by using data YC itself publishes through a
different, unrestricted channel instead of circumventing the disallow.

No auth required, no rate limiting encountered, one fetch per tag returns
the full list (no pagination needed). We pull several AI-related tags and
dedupe by YC's own numeric `id` field, since a company can carry multiple
overlapping tags (e.g. "AI" and "Artificial Intelligence" and "Machine
Learning" all exist as separate tags and a single company often has more
than one).
"""
import logging
from typing import AsyncIterator

from src.utils.http_client import AsyncHttpClient
from src.schemas.models import StartupRecord, StartupContent, StartupContentData, Source

logger = logging.getLogger("graphone.scraper.yc")

YC_API_BASE = "https://yc-oss.github.io/api/tags"

# Multiple overlapping AI-related tags, unioned and deduped by company id.
# This comfortably clears 1,000+ unique companies (833 + 920 + 230 tagged
# across these three alone, before dedup).
AI_TAGS = ["ai", "artificial-intelligence", "machine-learning", "generative-ai"]


class YCScraper:
    def __init__(self, client: AsyncHttpClient):
        self.client = client

    async def scrape(self, target_count: int = 1000) -> AsyncIterator[StartupRecord]:
        seen_ids = set()
        fetched = 0

        for tag in AI_TAGS:
            if fetched >= target_count:
                return
            url = f"{YC_API_BASE}/{tag}.json"
            data, error = await self.client.fetch_json(url)
            if error or not data:
                logger.warning(f"YC fetch failed for tag='{tag}': {error}")
                continue

            logger.info(f"YC tag='{tag}' returned {len(data)} companies")

            for company in data:
                if fetched >= target_count:
                    return
                company_id = company.get("id")
                if company_id is None or company_id in seen_ids:
                    continue
                seen_ids.add(company_id)

                record = self._to_record(company)
                if record:
                    yield record
                    fetched += 1

    def _to_record(self, company: dict) -> StartupRecord | None:
        name = company.get("name")
        url = company.get("url")
        if not name or not url:
            return None  # never fabricate a record without a real source URL

        team_size = company.get("team_size")  # can legitimately be null in source data

        content = StartupContent(
            entityName=name,
            data=StartupContentData(employeeCount=team_size),
        )
        return StartupRecord(source=Source(name="Y Combinator", url=url), content=content)