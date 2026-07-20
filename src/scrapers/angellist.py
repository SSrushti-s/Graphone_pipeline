"""
AngelList/Wellfound - Remote tech startup jobs.
Uses their public GraphQL API endpoint.
"""
import logging
import json
from typing import AsyncIterator

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import parse_published_date
from src.schemas.models import JobRecord, JobContent, Source

logger = logging.getLogger("graphone.scraper.angellist")

# Wellfound public API - using their jobs listing endpoint
WELLFOUND_JOBS_URL = "https://wellfound.com/jobs"

class AngelListScraper:
    def __init__(self, client: AsyncHttpClient):
        self.client = client
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://wellfound.com/",
        }

    async def scrape(self, target_count: int = 50) -> AsyncIterator[JobRecord]:
        # Use the search endpoint with filters
        params = {
            "q": "ai machine learning llm",
            "remote": "true",
            "sort": "recent",
        }
        
        # Try the main jobs page with query params
        data, error = await self.client.fetch_json(
            WELLFOUND_JOBS_URL,
            params=params,
            headers=self.headers
        )
        
        if error or not data:
            logger.warning(f"Wellfound fetch failed: {error}")
            # Try alternative: scrape jobs page HTML (fallback)
            result = await self.client.fetch(WELLFOUND_JOBS_URL, params=params, headers=self.headers)
            if result.ok:
                # Parse HTML for job listings
                jobs = self._parse_html(result.text)
                for job in jobs:
                    yield job
            return

        jobs = data.get("jobs", []) if isinstance(data, dict) else []
        logger.info(f"Wellfound returned {len(jobs)} total job listings")

        fetched = 0
        for job in jobs:
            if fetched >= target_count:
                return
            if not self._is_ai_related(job.get("title", "")):
                continue
            record = self._to_record(job)
            if record:
                yield record
                fetched += 1

    def _parse_html(self, html: str) -> list[JobRecord]:
        """Fallback: parse jobs from HTML if JSON API fails"""
        # Simplified parser - you can use BeautifulSoup if available
        # For now, return empty list and log
        logger.warning("HTML parsing not implemented - try using BeautifulSoup")
        return []

    @staticmethod
    def _is_ai_related(title: str) -> bool:
        lowered = title.lower()
        return any(kw in lowered for kw in ["ai", "machine learning", "ml", "llm", "artificial intelligence"])

    def _to_record(self, job: dict) -> JobRecord | None:
        company_obj = job.get("company", {})
        company = company_obj.get("name") if isinstance(company_obj, dict) else job.get("company_name")
        title = job.get("title")
        url = job.get("url") or job.get("job_url")
        
        if not company or not title or not url:
            return None

        date_str = job.get("created_at") or job.get("posted_at") or job.get("updated_at")
        published_dt = parse_published_date(date_str)
        
        content = JobContent(
            company=company,
            date=published_dt,
            is_remote=job.get("remote", False),
            role_family="Other",
            title=title,
            url=url,
        )
        return JobRecord(source=Source(name="Wellfound", url=url), content=content)