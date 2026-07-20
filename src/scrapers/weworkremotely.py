"""
WeWorkRemotely - Remote job board with RSS feed.
Uses their atom feed for structured job listings.
"""
import logging
from typing import AsyncIterator
from xml.etree import ElementTree

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import parse_published_date
from src.schemas.models import JobRecord, JobContent, Source

logger = logging.getLogger("graphone.scraper.weworkremotely")

WWR_FEED = "https://weworkremotely.com/feed.atom"

AI_KEYWORDS = ["ai", "machine learning", "ml", "llm", "artificial intelligence", 
               "data scientist", "machine learning engineer"]


class WeWorkRemotelyScraper:
    def __init__(self, client: AsyncHttpClient):
        self.client = client
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }

    async def scrape(self, target_count: int = 50) -> AsyncIterator[JobRecord]:
        # Use fetch with custom headers
        result = await self.client.fetch(WWR_FEED, headers=self.headers)
        if not result.ok:
            logger.warning(f"WeWorkRemotely fetch failed: {result.error} (status: {result.status_code})")
            return

        if not result.text or len(result.text) < 100:
            logger.warning(f"WeWorkRemotely returned empty response")
            return

        entries = self._parse_feed(result.text)
        if not entries:
            logger.warning(f"WeWorkRemotely feed parsing returned 0 entries")
            return
            
        logger.info(f"WeWorkRemotely returned {len(entries)} total job listings")

        fetched = 0
        for entry in entries:
            if fetched >= target_count:
                return
            if not self._is_ai_related(entry.get("title", "")):
                continue
            record = self._to_record(entry)
            if record:
                yield record
                fetched += 1

    def _parse_feed(self, xml_text: str) -> list[dict]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as e:
            logger.warning(f"Failed to parse WeWorkRemotely RSS: {e}")
            return []

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = []
        for entry in root.findall(".//atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            updated_el = entry.find("atom:updated", ns)
            
            title = title_el.text.strip() if title_el is not None and title_el.text else None
            url = link_el.get("href") if link_el is not None else None
            published = updated_el.text.strip() if updated_el is not None and updated_el.text else None
            
            if title and url:
                entries.append({
                    "title": title,
                    "url": url,
                    "published": published,
                })
        return entries

    @staticmethod
    def _is_ai_related(title: str) -> bool:
        lowered = title.lower()
        return any(kw in lowered for kw in AI_KEYWORDS)

    def _to_record(self, entry: dict) -> JobRecord | None:
        title = entry.get("title")
        url = entry.get("url")
        if not title or not url:
            return None

        # Extract company from title (format: "Company: Job Title")
        company = title.split(":")[0].strip() if ":" in title else "Unknown"

        published_dt = parse_published_date(entry.get("published"))
        content = JobContent(
            company=company,
            date=published_dt,
            is_remote=True,
            role_family="Other",
            title=title,
            url=url,
        )
        return JobRecord(source=Source(name="WeWorkRemotely", url=url), content=content)