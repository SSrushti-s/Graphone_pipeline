"""
AI Jobs vertical (Phase II). Uses Remotive's public JSON API
(https://remotive.com/api/remote-jobs) -- real, free, unauthenticated,
no anti-bot. A genuinely runnable 3rd source.

Correction from an earlier version: combining category=software-dev AND
search=AI as a single request ANDs both filters together, which can
legitimately return zero results depending on current listings (the
category restricts to dev roles, the search then further restricts to
listings containing the literal substring "AI" in title/description --
a narrow intersection). This version queries by search term alone across
several AI-related terms and unions the results, which is a broader,
more reliable net for "find AI jobs" than a single over-constrained query.

is_remote is always True here since Remotive is remote-only by definition;
role_family is derived from a lightweight keyword classifier on title,
since Remotive's own category field is coarser than the brief's
'Engineering' style buckets.
"""
import logging
from typing import AsyncIterator
from urllib.parse import quote

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import parse_published_date, is_within_hours
from src.schemas.models import JobRecord, JobContent, Source
from config.settings import FRESHNESS

logger = logging.getLogger("graphone.scraper.jobs")

REMOTIVE_API = "https://remotive.com/api/remote-jobs"

SEARCH_TERMS = ["AI", "machine learning", "LLM", "artificial intelligence", "ML engineer"]

ROLE_FAMILY_KEYWORDS = {
    "Engineering": ["engineer", "developer", "swe", "backend", "frontend", "fullstack"],
    "Research": ["research scientist", "research engineer", "ml researcher"],
    "Data": ["data scientist", "data engineer", "analytics"],
    "Product": ["product manager", "product owner"],
    "Design": ["designer", "ux", "ui"],
    "Sales": ["sales", "account executive"],
    "Marketing": ["marketing", "growth"],
}


class JobsScraper:
    def __init__(self, client: AsyncHttpClient, search_terms: list[str] | None = None):
        self.client = client
        self.search_terms = search_terms or SEARCH_TERMS

    async def scrape(self, target_count: int = 100, require_fresh: bool = False) -> AsyncIterator[JobRecord]:
        seen_urls = set()
        fetched = 0

        for term in self.search_terms:
            if fetched >= target_count:
                return
            url = f"{REMOTIVE_API}?search={quote(term)}"
            data, error = await self.client.fetch_json(url)
            if error or not data:
                logger.warning(f"Remotive fetch failed for search='{term}': {error}")
                continue

            jobs = data.get("jobs", [])
            logger.info(f"Remotive search='{term}' returned {len(jobs)} jobs")

            for job in jobs:
                if fetched >= target_count:
                    return
                job_url = job.get("url")
                if not job_url or job_url in seen_urls:
                    continue
                seen_urls.add(job_url)

                record = self._to_record(job)
                if record is None:
                    continue
                if require_fresh and not record.content.date:
                    continue
                if require_fresh and not is_within_hours(record.content.date, FRESHNESS.max_age_hours):
                    continue
                yield record
                fetched += 1

    # In src/scrapers/jobs_scraper.py
def _to_record(self, job: dict) -> JobRecord | None:
    company = job.get("company_name")
    title = job.get("title")
    url = job.get("url")
    if not company or not url:
        return None

    # If no publication date, assume it's recent (within 24h)
    # This is a heuristic - if we can't find a date, we still want to 
    # include the job rather than drop it entirely
    published_dt = parse_published_date(job.get("publication_date"))
    
    content = JobContent(
        company=company,
        date=published_dt,  # Could be None - handled in main
        is_remote=job.get("is_remote", True),
        role_family=self._classify_role(title or ""),
        title=title,
        url=url,
    )
    return JobRecord(source=Source(name="Remotive", url=url), content=content)

    @staticmethod
    def _classify_role(title: str) -> str:
        lowered = title.lower()
        for family, keywords in ROLE_FAMILY_KEYWORDS.items():
            if any(kw in lowered for kw in keywords):
                return family
        return "Other"