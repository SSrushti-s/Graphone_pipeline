"""
Jobs vertical (Phase II) — RemoteOK.

Uses RemoteOK's official public JSON API (https://remoteok.com/api),
confirmed via independent uptime monitoring to be stable and CORS-enabled.
No auth required. This is source #2 of the required 5 job boards
(source #1 being Remotive, already implemented in jobs_scraper.py).

RemoteOK's API returns a flat JSON array. The first element is always a
metadata/legal object (not a job), which we skip -- this is documented
RemoteOK API behavior, not a parsing bug.
"""
import logging
from typing import AsyncIterator

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import parse_published_date
from src.schemas.models import JobRecord, JobContent, Source

logger = logging.getLogger("graphone.scraper.remoteok")

REMOTEOK_API = "https://remoteok.com/api"

AI_KEYWORDS = ["ai", "machine learning", "ml", "llm", "artificial intelligence", "data scien"]

ROLE_FAMILY_KEYWORDS = {
    "Engineering": ["engineer", "developer", "swe", "backend", "frontend", "fullstack"],
    "Research": ["research scientist", "research engineer", "ml researcher"],
    "Data": ["data scientist", "data engineer", "analytics"],
    "Product": ["product manager", "product owner"],
    "Design": ["designer", "ux", "ui"],
    "Sales": ["sales", "account executive"],
    "Marketing": ["marketing", "growth"],
}


class RemoteOKScraper:
    def __init__(self, client: AsyncHttpClient):
        self.client = client

    async def scrape(self, target_count: int = 100) -> AsyncIterator[JobRecord]:
        data, error = await self.client.fetch_json(REMOTEOK_API)
        if error or not data:
            logger.warning(f"RemoteOK fetch failed: {error}")
            return

        # First element is a legal/metadata notice, not a job -- skip it.
        jobs = [item for item in data if isinstance(item, dict) and item.get("id")]
        logger.info(f"RemoteOK returned {len(jobs)} total job listings")

        fetched = 0
        for job in jobs:
            if fetched >= target_count:
                return
            if not self._is_ai_related(job):
                continue
            record = self._to_record(job)
            if record:
                yield record
                fetched += 1

    @staticmethod
    def _is_ai_related(job: dict) -> bool:
        title = (job.get("position") or "").lower()
        tags = " ".join(job.get("tags", [])).lower()
        description = (job.get("description") or "").lower()[:500]  # cap to avoid scanning huge text
        combined = f"{title} {tags} {description}"
        return any(kw in combined for kw in AI_KEYWORDS)

    def _to_record(self, job: dict) -> JobRecord | None:
        company = job.get("company")
        title = job.get("position")
        url = job.get("url")
        if not company or not url:
            return None

        published_dt = parse_published_date(job.get("date"))
        role_family = self._classify_role(title or "")

        content = JobContent(
            company=company,
            date=published_dt,
            is_remote=True,
            role_family=role_family,
            title=title,
            url=url,
        )
        return JobRecord(source=Source(name="RemoteOK", url=url), content=content)

    @staticmethod
    def _classify_role(title: str) -> str:
        lowered = title.lower()
        for family, keywords in ROLE_FAMILY_KEYWORDS.items():
            if any(kw in lowered for kw in keywords):
                return family
        return "Other"