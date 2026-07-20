"""
News/Jobs signal source: Hacker News (Phase II).

Uses HN's Algolia Search API (https://hn.algolia.com/api) instead of the
raw Firebase newstories firehose. This is a deliberate correction from an
earlier version: filtering the raw "newest submitted stories" stream by
title keyword is unreliable -- on any given few-hundred-story window, the
number of stories that happen to mention AI keywords in the title can
legitimately be zero, since most new HN submissions aren't AI-related at
all. The Algolia search endpoint lets us directly query for AI-relevant
terms sorted by recency, which is the correct tool for "find AI news"
rather than "filter arbitrary new stories and hope."
"""
import logging
from datetime import datetime, timezone
from typing import AsyncIterator
from urllib.parse import quote

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import is_within_hours
from src.schemas.models import NewsRecord, NewsContent, Source
from config.settings import FRESHNESS

logger = logging.getLogger("graphone.scraper.hn")

ALGOLIA_SEARCH_API = "https://hn.algolia.com/api/v1/search_by_date"

AI_QUERIES = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "Anthropic", "OpenAI",
    "machine learning", "neural network", "artificial intelligence",
]


class HackerNewsScraper:
    def __init__(self, client: AsyncHttpClient):
        self.client = client

    async def scrape(self, target_count: int = 100) -> AsyncIterator[NewsRecord]:
        seen_ids = set()
        fetched = 0
        per_query = max(20, target_count // len(AI_QUERIES) + 5)

        for query in AI_QUERIES:
            if fetched >= target_count:
                return
            url = (
                f"{ALGOLIA_SEARCH_API}?query={quote(query)}"
                f"&tags=story&hitsPerPage={per_query}"
            )
            data, error = await self.client.fetch_json(url)
            if error or not data:
                logger.warning(f"HN Algolia search failed for query '{query}': {error}")
                continue

            hits = data.get("hits", [])
            for hit in hits:
                if fetched >= target_count:
                    return
                object_id = hit.get("objectID")
                if not object_id or object_id in seen_ids:
                    continue
                seen_ids.add(object_id)

                record = self._to_record(hit)
                if record:
                    yield record
                    fetched += 1

    def _to_record(self, hit: dict) -> NewsRecord | None:
        title = hit.get("title")
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        if not title:
            return None

        created_at_i = hit.get("created_at_i")
        published_dt = (
            datetime.fromtimestamp(created_at_i, tz=timezone.utc)
            if created_at_i else None
        )
        fresh = is_within_hours(published_dt, FRESHNESS.max_age_hours)

        content = NewsContent(
            title=title,
            url=url,
            published_date=published_dt,
            full_text=None,
            is_fresh_24h=fresh,
        )
        return NewsRecord(source=Source(name="Hacker News", url=url), content=content)