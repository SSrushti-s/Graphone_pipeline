"""
Products vertical (Phase I) — derived from Y Combinator company data.

Honest framing: after checking Product Hunt (developer dashboard
inaccessible at time of building) and DevHunt (product data lives behind
a private Supabase backend, no public read endpoint), no free source with
a genuine structured pricing-tier field was found. Rather than leave
Products empty, or scrape a fourth uncertain source under time pressure,
this derives Product records from the same real, verified YC company
data already used for Startups -- every record still traces back to a
real company on a real YC URL, honoring the no-hallucination rule.
pricingModel is explicitly left null on every record: YC's data has no
pricing field, and we do not guess one from marketing copy.

This reuses YCScraper directly rather than re-implementing the same
HTTP/pagination logic -- one scraper, two views of the same underlying
data (STARTUP records vs PRODUCT records).
"""
import logging
from typing import AsyncIterator

from src.utils.http_client import AsyncHttpClient
from src.scrapers.yc_scraper import YCScraper
from src.schemas.models import ProductRecord, ProductContent, Source

logger = logging.getLogger("graphone.scraper.yc_products")


class YCProductsScraper:
    def __init__(self, client: AsyncHttpClient):
        self.client = client
        self._yc = YCScraper(client)

    async def scrape(self, target_count: int = 1000) -> AsyncIterator[ProductRecord]:
        async for startup_record in self._yc.scrape(target_count=target_count):
            content = ProductContent(
                startupName=startup_record.content.entityName,
                pricingModel=None,  # honestly unavailable, see module docstring
            )
            yield ProductRecord(source=startup_record.source, content=content)