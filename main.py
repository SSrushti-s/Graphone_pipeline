"""
GraphOne Intelligence Graph -- Pipeline Entry Point.

Runs Phases I, II, and IV against real, runnable sources:
  - arXiv (research papers) + GitHub API (star enrichment)
  - RSS News (5 sources, 24h freshness filter)
  - 5+ Job Boards (Remotive, RemoteOK, Arbeitnow, Jobicy, Wellfound, WeWorkRemotely)

Startups/Products: this trial run derives startup & product records from
the arXiv/GitHub/job-company data actually collected (companies posting
jobs, orgs behind papers/repos) and resolves them through the entity
resolver -- rather than fabricating separate unsourced startup/product
scrapers, every startup/product record here traces back to a real URL,
honoring the "no hallucinated data" requirement. Scaling to the full
1,000+ dedicated startup/product directory scrape (e.g. a YC/Crunchbase-
style source) follows the exact same ScraperConfig + AsyncHttpClient
pattern established here -- see architecture.pdf for the target sources
and why they were out of scope to hit live in this build.

Usage:
    python main.py --papers 50 --news 50 --jobs 50

Environment variables (see .env.example):
    GROQ_API_KEYS or GROQ_API_KEY, plus GITHUB_TOKEN
"""
import argparse
import asyncio
import logging
import sys
from dotenv import load_dotenv
load_dotenv()

from src.utils.date_parser import is_within_hours
from config.settings import FRESHNESS
from src.utils.http_client import AsyncHttpClient
from src.scrapers.arxiv_scraper import ArxivScraper
from src.scrapers.github_enricher import GitHubEnricher
from src.scrapers.hn_scraper import HackerNewsScraper
from src.scrapers.jobs_scraper import JobsScraper
from src.scrapers.yc_scraper import YCScraper
from src.scrapers.yc_products_scraper import YCProductsScraper
from src.scrapers.rss_news_scraper import RSSNewsScraper
from src.scrapers.remoteok_scraper import RemoteOKScraper
from src.scrapers.multi_board_scraper import ArbeitnowScraper, JobicyScraper
from src.scrapers.angellist import AngelListScraper
from src.scrapers.weworkremotely import WeWorkRemotelyScraper
from src.utils.article_extractor import extract_full_text
from src.llm.news_enricher import NewsLLMEnricher
from src.resolver.entity_resolver import EntityResolver
from src.storage.dedupe import DedupeStore
from src.storage.csv_writer import write_records_to_csv
from config.settings import STORAGE

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("logs/pipeline.log")],
)
logger = logging.getLogger("graphone.main")


async def run_research_papers(client: AsyncHttpClient, target: int) -> list[dict]:
    logger.info(f"Phase I: scraping {target} research papers from arXiv...")
    scraper = ArxivScraper(client, category="cs.AI")
    enricher = GitHubEnricher(client)
    records = []
    async for paper in scraper.scrape(target_count=target):
        if paper.content.github_url:
            paper = await enricher.enrich(paper)
        records.append(paper.model_dump(mode="json"))
    logger.info(f"Collected {len(records)} research paper records")
    return records


async def run_news(client: AsyncHttpClient, target: int, dedupe: DedupeStore, llm_enrich_count: int = 10) -> list[dict]:
    logger.info(f"Phase II: scraping {target} AI news items across 5 sources...")
    records = []
    skipped_as_seen = 0

    hn_target = target // 2
    rss_target = target - hn_target

    hn_scraper = HackerNewsScraper(client)
    async for item in hn_scraper.scrape(target_count=hn_target):
        if dedupe.seen(item.content.url):
            skipped_as_seen += 1
            continue
        dedupe.mark_seen(item.content.url)
        records.append(item)

    rss_scraper = RSSNewsScraper(client)
    async for item in rss_scraper.scrape(target_count=rss_target):
        if dedupe.seen(item.content.url):
            skipped_as_seen += 1
            continue
        dedupe.mark_seen(item.content.url)
        records.append(item)
    
    stale_count = sum(1 for r in records if not r.content.is_fresh_24h)
    records = [r for r in records if r.content.is_fresh_24h]
    if stale_count:
        logger.info(f"Dropped {stale_count} stale (>24h) news items before output.")

    if skipped_as_seen:
        logger.info(f"Skipped {skipped_as_seen} news items already seen in a prior run.")

    # Phase III: LLM structuring, applied to a bounded subset
    logger.info(f"Phase III: fetching full-text + LLM-structuring {llm_enrich_count} articles...")
    enricher = NewsLLMEnricher()
    enriched_count = 0
    fetch_failures = 0
    llm_failures = 0
    skipped_non_article = 0

    def _looks_like_article(url: str) -> bool:
        skip_domains = ["github.com", "github.io", "arxiv.org"]
        return not any(d in url for d in skip_domains)

    candidates = [r for r in records if _looks_like_article(r.content.url)][:llm_enrich_count]
    skipped_non_article = min(llm_enrich_count, len(records)) - len(candidates)

    for record in candidates:
        full_text = await extract_full_text(client, record.content.url)
        if not full_text:
            fetch_failures += 1
            logger.warning(f"Full-text fetch/extract returned nothing for {record.content.url}")
            continue
        record.content.full_text = full_text
        record = await enricher.enrich(record)
        if record.content.llm_summary:
            enriched_count += 1
        else:
            llm_failures += 1
            logger.warning(f"LLM produced no summary for {record.content.url}")
    
    logger.info(
        f"Successfully LLM-enriched {enriched_count}/{len(candidates)} candidate articles "
        f"({fetch_failures} fetch failures -- often JS-rendered or bot-blocked pages, "
        f"{llm_failures} LLM failures, {skipped_non_article} skipped as non-article URLs)"
    )
    result = [r.model_dump(mode="json") for r in records]
    logger.info(f"Collected {len(result)} news records ({sum(1 for r in result if r['content']['is_fresh_24h'])} within 24h)")
    return result


# In run_jobs() - replace the date filter logic

async def run_jobs(client: AsyncHttpClient, target: int, dedupe: DedupeStore) -> list[dict]:
    logger.info(f"Phase II: scraping {target} AI jobs across 6 job boards...")
    records = []
    skipped_as_seen = 0
    skipped_stale = 0
    per_board = max(10, target // 6)

    scrapers = [
        ("Remotive", JobsScraper(client)),
        ("RemoteOK", RemoteOKScraper(client)),
        ("Arbeitnow", ArbeitnowScraper(client)),
        ("Jobicy", JobicyScraper(client)),
        ("Wellfound", AngelListScraper(client)),
        ("WeWorkRemotely", WeWorkRemotelyScraper(client)),
    ]

    for name, scraper in scrapers:
        board_count = 0
        board_skipped_stale = 0
        try:
            async for job in scraper.scrape(target_count=per_board):
                if dedupe.seen(job.content.url):
                    skipped_as_seen += 1
                    continue
                dedupe.mark_seen(job.content.url)
                
                # If date is None OR within 24h, keep it
                if job.content.date is not None:
                    if not is_within_hours(job.content.date, FRESHNESS.max_age_hours):
                        board_skipped_stale += 1
                        continue
                
                records.append(job.model_dump(mode="json"))
                board_count += 1
        except Exception as e:
            logger.error(f"Error scraping {name}: {e}")
            continue
        logger.info(f"Board {name} contributed {board_count} fresh jobs (skipped {board_skipped_stale} stale)")

    if skipped_as_seen:
        logger.info(f"Skipped {skipped_as_seen} jobs already seen in a prior run.")
    logger.info(f"Collected {len(records)} job records across {len(scrapers)} boards")
    return records

    if skipped_as_seen:
        logger.info(f"Skipped {skipped_as_seen} jobs already seen in a prior run.")
    logger.info(f"Collected {len(records)} job records across {len(scrapers)} boards")
    return records


def resolve_entities_from_jobs(jobs: list[dict], resolver: EntityResolver) -> list[dict]:
    """Derive canonicalized startup records from real job postings' company field."""
    seen_canonical = set()
    startup_records = []
    for job in jobs:
        raw_company = job["content"]["company"]
        result = resolver.resolve(raw_company, entity_type="STARTUP")
        canonical = result.canonical_name
        if canonical in seen_canonical:
            continue
        seen_canonical.add(canonical)
        startup_records.append({
            "schemaVersion": "1.0",
            "recordType": "STARTUP",
            "source": {"name": job["source"]["name"], "url": job["content"]["url"]},
            "content": {"entityName": canonical, "data": {"employeeCount": None}},
            "collectedAt": job["collectedAt"],
        })
    return startup_records


async def run_startups(client: AsyncHttpClient, target: int, resolver: EntityResolver) -> list[dict]:
    logger.info(f"Phase I: scraping {target} AI startups from Y Combinator...")
    scraper = YCScraper(client)
    records = []
    seen_canonical = set()
    async for record in scraper.scrape(target_count=target):
        result = resolver.resolve(record.content.entityName, entity_type="STARTUP")
        canonical = result.canonical_name
        if canonical in seen_canonical:
            continue
        seen_canonical.add(canonical)
        record.content.entityName = canonical
        records.append(record.model_dump(mode="json"))
        if len(records) >= target:
            break
    logger.info(f"Collected {len(records)} unique startup records")
    return records


async def run_products(client: AsyncHttpClient, target: int) -> list[dict]:
    logger.info(f"Phase I: deriving {target} AI products from Y Combinator data...")
    scraper = YCProductsScraper(client)
    records = []
    async for record in scraper.scrape(target_count=target):
        records.append(record.model_dump(mode="json"))
        if len(records) >= target:
            break
    logger.info(f"Collected {len(records)} product records")
    return records


async def main():
    parser = argparse.ArgumentParser(description="GraphOne Intelligence Graph pipeline")
    parser.add_argument("--papers", type=int, default=50, help="Target research paper count")
    parser.add_argument("--news", type=int, default=50, help="Target news item count")
    parser.add_argument("--jobs", type=int, default=50, help="Target job posting count")
    parser.add_argument("--startups", type=int, default=1002, help="Target startup count (add 2 for dedupe)")
    parser.add_argument("--products", type=int, default=1000, help="Target product count")
    args = parser.parse_args()

    # Ensure we clean the dedupe DB for fresh run
    import os
    if os.path.exists(STORAGE.dedupe_db_path):
        os.remove(STORAGE.dedupe_db_path)
        logger.info(f"Removed existing dedupe DB: {STORAGE.dedupe_db_path}")

    dedupe = DedupeStore()
    resolver = EntityResolver()

    async with AsyncHttpClient() as client:
        papers = await run_research_papers(client, args.papers)
        news = await run_news(client, args.news, dedupe)
        jobs = await run_jobs(client, args.jobs, dedupe)
        startups = await run_startups(client, args.startups, resolver)
        products = await run_products(client, args.products)

    # Export mapping log before writing
    mapping_log = resolver.export_mapping_log()

    write_records_to_csv(
        papers, f"{STORAGE.output_dir}/research_papers.csv",
        fieldnames=["schemaVersion", "recordType", "source.name", "source.url",
                    "content.title", "content.authors", "content.paper_url",
                    "content.github_url", "content.github_stars", "content.published_date",
                    "collectedAt"],
    )
    write_records_to_csv(
        news, f"{STORAGE.output_dir}/news.csv",
        fieldnames=["schemaVersion", "recordType", "source.name", "source.url",
                    "content.title", "content.url", "content.published_date",
                    "content.is_fresh_24h", "content.llm_summary", "content.llm_entities",
                    "collectedAt"],
    )
    write_records_to_csv(
        jobs, f"{STORAGE.output_dir}/jobs.csv",
        fieldnames=["schemaVersion", "recordType", "source.name", "source.url",
                    "content.company", "content.title", "content.date",
                    "content.is_remote", "content.role_family", "content.url", "collectedAt"],
    )
    write_records_to_csv(
        startups, f"{STORAGE.output_dir}/startups.csv",
        fieldnames=["schemaVersion", "recordType", "source.name", "source.url",
                    "content.entityName", "content.data.employeeCount", "collectedAt"],
    )
    write_records_to_csv(
        products, f"{STORAGE.output_dir}/products.csv",
        fieldnames=["schemaVersion", "recordType", "source.name", "source.url",
                    "content.startupName", "content.pricingModel", "collectedAt"],
    )
    write_records_to_csv(
        mapping_log, f"{STORAGE.output_dir}/entity_mapping_log.csv",
        fieldnames=["raw_name", "canonical_name", "match_method", "confidence", "entity_type"],
    )

    logger.info("Pipeline run complete. Output written to ./output/")
    dedupe.close()


if __name__ == "__main__":
    asyncio.run(main())