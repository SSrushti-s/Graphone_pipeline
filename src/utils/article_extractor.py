"""
Full-text article extraction from a news URL's raw HTML.

This is a heuristic extractor, not a full Readability.js-style port:
it looks for the highest-density block of <p> text on the page, which
is a simple, dependency-light approach that works reasonably well across
most news sites' article templates without needing per-site selectors.

Explicitly NOT attempting to defeat paywalls or bot walls -- if a fetch
fails or the extracted text is suspiciously short (likely a paywall/
consent-wall stub), we return None rather than fabricate content.
"""
import logging
from typing import Optional

from bs4 import BeautifulSoup

from src.utils.http_client import AsyncHttpClient

logger = logging.getLogger("graphone.utils.article_extractor")

MIN_VIABLE_LENGTH = 200  # chars; below this, likely a stub/paywall, not real content


async def extract_full_text(client: AsyncHttpClient, url: str) -> Optional[str]:
    result = await client.fetch(url)
    if not result.ok:
        logger.warning(f"Article fetch failed for {url}: status={result.status} error={result.error}")
        return None

    try:
        soup = BeautifulSoup(result.text, "lxml")
    except Exception as e:
        logger.warning(f"HTML parse failed for {url}: {e}")
        return None

    # Strip obviously non-article content before extracting paragraphs
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()

    # Heuristic: the <article> tag, if present, is the most reliable signal
    article_tag = soup.find("article")
    container = article_tag if article_tag else soup

    paragraphs = [p.get_text(strip=True) for p in container.find_all("p")]
    text = "\n\n".join(p for p in paragraphs if len(p) > 40)  # drop short/nav-like fragments

    if len(text) < MIN_VIABLE_LENGTH:
        logger.warning(f"Extracted text too short ({len(text)} chars, found {len(paragraphs)} <p> tags) for {url}")
        return None
    return text