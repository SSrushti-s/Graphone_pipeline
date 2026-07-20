"""
Jobs vertical (Phase II) — Arbeitnow and Jobicy job boards.

Both use official public JSON APIs with no auth required.
Himalayas removed as it was being blocked/restricted.
"""
import logging
from typing import AsyncIterator

from src.utils.http_client import AsyncHttpClient
from src.utils.date_parser import parse_published_date
from src.schemas.models import JobRecord, JobContent, Source

logger = logging.getLogger("graphone.scraper.multi_board")

ROLE_FAMILY_KEYWORDS = {
    "Engineering": ["engineer", "developer", "swe", "backend", "frontend", "fullstack"],
    "Research": ["research scientist", "research engineer", "ml researcher"],
    "Data": ["data scientist", "data engineer", "analytics"],
    "Product": ["product manager", "product owner"],
    "Design": ["designer", "ux", "ui"],
    "Sales": ["sales", "account executive"],
    "Marketing": ["marketing", "growth"],
}

AI_KEYWORDS = ["ai", "machine learning", "ml", "llm", "artificial intelligence"]


def _classify_role(title: str) -> str:
    lowered = (title or "").lower()
    for family, keywords in ROLE_FAMILY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            return family
    return "Other"


def _is_ai_related(text: str) -> bool:
    lowered = (text or "").lower()
    return any(kw in lowered for kw in AI_KEYWORDS)


class ArbeitnowScraper:
    API_URL = "https://arbeitnow.com/api/job-board-api"

    def __init__(self, client: AsyncHttpClient):
        self.client = client

    async def scrape(self, target_count: int = 50) -> AsyncIterator[JobRecord]:
        data, error = await self.client.fetch_json(self.API_URL)
        if error or not data:
            logger.warning(f"Arbeitnow fetch failed: {error}")
            return

        jobs = data.get("data", [])
        logger.info(f"Arbeitnow returned {len(jobs)} total job listings")

        fetched = 0
        for job in jobs:
            if fetched >= target_count:
                return
            title = job.get("title", "")
            tags = " ".join(job.get("tags", []))
            if not _is_ai_related(f"{title} {tags}"):
                continue
            record = self._to_record(job)
            if record:
                yield record
                fetched += 1

    def _to_record(self, job: dict) -> JobRecord | None:
        company = job.get("company_name")
        title = job.get("title")
        url = job.get("url")
        if not company or not url:
            return None

        published_dt = None
        ts = job.get("created_at")
        if ts:
            from datetime import datetime, timezone
            try:
                published_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (ValueError, TypeError):
                published_dt = None

        content = JobContent(
            company=company, date=published_dt, is_remote=job.get("remote", True),
            role_family=_classify_role(title or ""), title=title, url=url,
        )
        return JobRecord(source=Source(name="Arbeitnow", url=url), content=content)


class JobicyScraper:
    API_URL = "https://jobicy.com/api/v2/remote-jobs"

    def __init__(self, client: AsyncHttpClient):
        self.client = client

    async def scrape(self, target_count: int = 50) -> AsyncIterator[JobRecord]:
        fetched = 0
        
        queries = [
            {"tag": "machine-learning"},
            {"tag": "artificial-intelligence"},
            {"tag": "data-science"},
        ]
        for params in queries:
            if fetched >= target_count:
                return
            query_str = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{self.API_URL}?count=50&{query_str}"
            data, error = await self.client.fetch_json(url)
            if error or not data:
                logger.warning(f"Jobicy fetch failed for params={params}: {error}")
                continue

            jobs = data.get("jobs", [])
            logger.info(f"Jobicy params={params} returned {len(jobs)} jobs")

            for job in jobs:
                if fetched >= target_count:
                    return
                record = self._to_record(job)
                if record:
                    yield record
                    fetched += 1

    def _to_record(self, job: dict) -> JobRecord | None:
        company = job.get("companyName")
        title = job.get("jobTitle")
        url = job.get("url")
        if not company or not url:
            return None

        published_dt = parse_published_date(job.get("pubDate"))
        content = JobContent(
            company=company, date=published_dt,
            is_remote=(job.get("jobGeo", "").lower() == "anywhere"),
            role_family=_classify_role(title or ""), title=title, url=url,
        )
        return JobRecord(source=Source(name="Jobicy", url=url), content=content)