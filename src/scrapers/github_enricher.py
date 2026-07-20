"""
GitHub star enrichment (Phase I requirement: 'dynamic metrics like current
GitHub stars'). Uses the real public GitHub REST API.

Unauthenticated: 60 requests/hour/IP.
With a GITHUB_TOKEN env var: 5,000 requests/hour -- this is the concrete
example of "scale via infra/config, not code" from the brief: add a token,
throughput goes up 80x, zero code changes.
"""
import logging
import os
import re

from src.utils.http_client import AsyncHttpClient
from src.schemas.models import ResearchPaperRecord

logger = logging.getLogger("graphone.scraper.github")

# Fix: Exclude ending punctuation by explicitly trimming matching scopes
REPO_PATH_RE = re.compile(r"github\.com/([\w\-]+)/([\w\-.]+)")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


class GitHubEnricher:
    def __init__(self, client: AsyncHttpClient):
        self.client = client
        self._rate_limited = False
        self._rate_limited_warned = False

    def _headers(self) -> dict:
        h = {"Accept": "application/vnd.github+json"}
        if GITHUB_TOKEN:
            h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        return h

    async def enrich(self, record: ResearchPaperRecord) -> ResearchPaperRecord:
        if not record.content.github_url:
            return record
        if self._rate_limited:
            return record

        m = REPO_PATH_RE.search(record.content.github_url)
        if not m:
            return record

        owner = m.group(1)
        # Clean up trailing punctuation periods or extra symbols
        repo = m.group(2).rstrip(".").rstrip("/").removesuffix(".git")
        
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        # FIX: Unpack as a tuple (data, error) since that is what your fetch_json returns
        data, error = await self.client.fetch_json(api_url, headers=self._headers())
        if error:
            if "status=403" in error or "status=429" in error:
                if not self._rate_limited_warned:
                    logger.error(
                        "GitHub API rate limit hit. Set GITHUB_TOKEN env var "
                        "(60/hr -> 5000/hr) to fix. Skipping further GitHub "
                        "enrichment for this run."
                    )
                    self._rate_limited_warned = True
                self._rate_limited = True
                return record
            logger.warning(f"GitHub enrichment failed for {owner}/{repo}: {error}")
            return record

        if data and "stargazers_count" in data:
            record.content.github_stars = data["stargazers_count"]
        return record
