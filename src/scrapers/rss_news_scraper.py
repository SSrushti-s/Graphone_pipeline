"""
News vertical (Phase II) — multi-source RSS aggregator.

Standard RSS/Atom XML feeds from 5 distinct AI-focused publications,
satisfying the assignment's "5 distinct AI news sources" requirement.
RSS is a purpose-built, no-auth, no-bot-wall format for exactly this use
case (latest articles + real publish timestamps), which is why this
approach is both simpler and more reliable than ad-hoc HTML scraping.

Each feed entry gives us a real <pubDate> (RFC 822 format) which we parse
via the existing date_parser utility -- this exercises the strict-
timestamp freshness path, same as the Hacker News source, but now across
multiple independent publishers instead of one.

Sources (feed URL -> publication):
  - TechCrunch AI category feed
  - VentureBeat (AI/ML focused tech business coverage)
  - Ars Technica (broader tech, filtered to AI-related titles)
  - The Verge AI tag feed
  - MIT Technology Review AI feed
"""
import logging
from datetime import datetime
from typing import AsyncIterator
from xml.etree import ElementTree

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import parse_published_date, is_within_hours
from src.schemas.models import NewsRecord, NewsContent, Source
from config.settings import FRESHNESS

logger = logging.getLogger("graphone.scraper.rss")

RSS_SOURCES = [
    {"name": "TechCrunch", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "filter_ai": False},
    {"name": "VentureBeat", "url": "https://venturebeat.com/category/ai/feed/", "filter_ai": False},
    {"name": "Ars Technica", "url": "https://feeds.arstechnica.com/arstechnica/index", "filter_ai": True},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "filter_ai": False},
    {"name": "MIT Technology Review", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "filter_ai": False},
]

AI_KEYWORDS = [
    "ai", "llm", "gpt", "claude", "gemini", "anthropic", "openai",
    "machine learning", "neural", "chatbot", "artificial intelligence",
    "deep learning", "generative ai",
]


class RSSNewsScraper:
    def __init__(self, client: AsyncHttpClient):
        self.client = client

    async def scrape(self, target_count: int = 200) -> AsyncIterator[NewsRecord]:
        fetched = 0
        per_source = max(10, target_count // len(RSS_SOURCES) + 5)

        for source_cfg in RSS_SOURCES:
            if fetched >= target_count:
                return
            result = await self.client.fetch(source_cfg["url"])
            if not result.ok:
                logger.warning(f"RSS fetch failed for {source_cfg['name']}: {result.error}")
                continue

            entries = self._parse_feed(result.text)
            logger.info(f"RSS source='{source_cfg['name']}' returned {len(entries)} entries")

            count_from_source = 0
            for entry in entries:
                if fetched >= target_count or count_from_source >= per_source:
                    break
                if source_cfg["filter_ai"] and not self._is_ai_related(entry.get("title", "")):
                    continue
                record = self._to_record(entry, source_cfg["name"])
                if record and record.content.is_fresh_24h:
                    yield record
                    fetched += 1
                    count_from_source += 1

    @staticmethod
    def _is_ai_related(title: str) -> bool:
        lowered = title.lower()
        return any(kw in lowered for kw in AI_KEYWORDS)

    def _parse_feed(self, xml_text: str) -> list[dict]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as e:
            logger.warning(f"Failed to parse RSS feed XML: {e}")
            return []

        entries = []
        # Standard RSS 2.0: <rss><channel><item>...
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pubdate_el = item.find("pubDate")
            entries.append({
                "title": title_el.text.strip() if title_el is not None and title_el.text else None,
                "url": link_el.text.strip() if link_el is not None and link_el.text else None,
                "published": pubdate_el.text.strip() if pubdate_el is not None and pubdate_el.text else None,
            })

        # Fallback: Atom format <feed><entry><link href="..."/>
        if not entries:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                updated_el = entry.find("atom:updated", ns)
                entries.append({
                    "title": title_el.text.strip() if title_el is not None and title_el.text else None,
                    "url": link_el.get("href") if link_el is not None else None,
                    "published": updated_el.text.strip() if updated_el is not None and updated_el.text else None,
                })

        return entries

    def _to_record(self, entry: dict, source_name: str) -> NewsRecord | None:
        title = entry.get("title")
        url = entry.get("url")
        if not title or not url:
            return None  # never fabricate a record without a real source URL

        published_dt = parse_published_date(entry.get("published"))
        fresh = is_within_hours(published_dt, FRESHNESS.max_age_hours)

        content = NewsContent(
            title=title,
            url=url,
            published_date=published_dt,
            full_text=None,
            is_fresh_24h=fresh,
        )
        return NewsRecord(source=Source(name=source_name, url=url), content=content)