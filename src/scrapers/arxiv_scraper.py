"""
Research Papers Vertical: arXiv scraper (Phase I).

Uses arXiv's official Atom API (export.arxiv.org/api/query) -- this is a
real, public, unauthenticated, rate-limit-friendly endpoint, so it's ideal
as one of the "2-3 real sources you can run yourself" without needing to
fight anti-bot protection. Cloudflare/Datadome bypass strategy for the
harder sources (e.g. Papers with Code's actual site) is documented
separately in architecture.pdf Phase V, since PWC's site is JS-rendered
and bot-protected in practice.

Pulls: title, authors, arxiv URL, published date.
GitHub linkage + star count is resolved via a second pass in
github_enricher.py, since arXiv abstracts don't reliably contain repo links
inline -- we regex-scan the abstract text for a github.com URL and cross-
check via the GitHub API.
"""
import logging
import re
from datetime import datetime
from typing import AsyncIterator
from xml.etree import ElementTree

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import parse_published_date
from src.schemas.models import ResearchPaperRecord, ResearchPaperContent, Source

logger = logging.getLogger("graphone.scraper.arxiv")

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}
GITHUB_URL_RE = re.compile(r"https?://github\.com/[\w\-]+/[\w\-.]+")


class ArxivScraper:
    """
    Paginates arXiv's API in batches of `page_size`, yielding validated
    ResearchPaperRecord objects. Designed to be called repeatedly with
    increasing `start` offsets by a driver that controls total record count
    -- this is the piece that "scales to 500k without code changes":
    raise `target_count` and add more concurrent category queries.
    """

    def __init__(self, client: AsyncHttpClient, category: str = "cs.AI", page_size: int = 100):
        self.client = client
        self.category = category
        self.page_size = page_size

    async def scrape(self, target_count: int = 100) -> AsyncIterator[ResearchPaperRecord]:
        fetched = 0
        start = 0
        while fetched < target_count:
            batch_size = min(self.page_size, target_count - fetched)
            url = (
                f"{ARXIV_API}?search_query=cat:{self.category}"
                f"&start={start}&max_results={batch_size}"
                f"&sortBy=submittedDate&sortOrder=descending"
            )
            result = await self.client.fetch(url)
            if not result.ok:
                logger.error(f"arXiv fetch failed at start={start}: {result.error}")
                break

            entries = self._parse_feed(result.text)
            if not entries:
                logger.info("No more arXiv entries returned, stopping pagination")
                break

            for entry in entries:
                record = self._to_record(entry)
                if record:
                    yield record
                    fetched += 1
                    if fetched >= target_count:
                        return

            start += batch_size

    def _parse_feed(self, xml_text: str) -> list[dict]:
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as e:
            logger.error(f"Failed to parse arXiv Atom feed: {e}")
            return []

        entries = []
        for entry in root.findall("atom:entry", NS):
            title_el = entry.find("atom:title", NS)
            id_el = entry.find("atom:id", NS)
            published_el = entry.find("atom:published", NS)
            summary_el = entry.find("atom:summary", NS)
            authors = [
                a.find("atom:name", NS).text.strip()
                for a in entry.findall("atom:author", NS)
                if a.find("atom:name", NS) is not None
            ]
            entries.append({
                "title": title_el.text.strip().replace("\n", " ") if title_el is not None else None,
                "url": id_el.text.strip() if id_el is not None else None,
                "published": published_el.text.strip() if published_el is not None else None,
                "summary": summary_el.text.strip() if summary_el is not None else "",
                "authors": authors,
            })
        return entries

    def _to_record(self, entry: dict) -> ResearchPaperRecord | None:
        if not entry.get("title") or not entry.get("url"):
            return None  # never fabricate a record without a real source URL

        github_match = GITHUB_URL_RE.search(entry.get("summary", ""))
        github_url = github_match.group(0) if github_match else None

        published_dt = parse_published_date(entry.get("published"))

        content = ResearchPaperContent(
            title=entry["title"],
            authors=entry.get("authors", []),
            paper_url=entry["url"],
            github_url=github_url,
            github_stars=None,  # filled by github_enricher.py in a second pass
            published_date=published_dt,
        )
        return ResearchPaperRecord(
            source=Source(name="arXiv", url=entry["url"]),
            content=content,
        )
