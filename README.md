# GraphOne Intelligence Graph — Data Pipeline

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Async, fault-tolerant ingestion pipeline for the AI/venture ecosystem Intelligence Graph. Built for the AI Engineer / Data Intelligence trial assignment.

This project demonstrates a production-grade approach to acquiring and structuring data from diverse sources, including research papers, news, jobs, startups, and products.

## Key Achievements

| Phase | Requirement | Status | Details |
|-------|-------------|--------|---------|
| **Phase I** | 1,000+ Research Papers | ✅ | Scraped from arXiv with GitHub star enrichment |
| **Phase I** | 1,000+ Startups | ✅ | Derived from Y Combinator directory |
| **Phase I** | 1,000+ Products | ✅ | Derived from Y Combinator data |
| **Phase II** | 5 AI News Sources | ✅ | RSS feeds from TechCrunch, VentureBeat, Ars Technica, The Verge, MIT Tech Review |
| **Phase II** | 5 AI Job Boards | ✅ | Remotive, RemoteOK, Arbeitnow, Jobicy, Wellfound |
| **Phase II** | 24-Hour Freshness | ✅ | Date filtering with fallback heuristics |
| **Phase III** | Multi-Tier LLM | ✅ | Gemini → Groq → DeepSeek fallback with 429 handling |
| **Phase IV** | Entity Resolution | ✅ | Canonicalization against 50+ seed entities |
| **Phase V** | Anti-Bot Strategy | ✅ | Playwright pattern for JS-rendered pages |
| **Phase VI** | Architecture Design | ✅ | Complete design document included |

## What This Pipeline Actually Does

Runs **real, live** scrapers end-to-end (no mocked data):

| Source | What it collects | Why this source |
|--------|------------------|-----------------|
| **arXiv API** | Research papers (title, authors, URL, published date) | Official public Atom API, no auth, generous rate limits |
| **GitHub REST API** | Star counts for papers with linked repos | Official public API, matches "dynamic metrics" requirement |
| **RSS Feeds (5 sources)** | AI-related news, 24h freshness filtered | TechCrunch, VentureBeat, Ars Technica, The Verge, MIT Technology Review |
| **Job Boards (5 sources)** | AI/remote job postings | Remotive, RemoteOK, Arbeitnow, Jobicy, Wellfound |
| **Y Combinator API** | Startup and product listings | Official directory data for canonical entity resolution |

Startup and product records are **derived from real source data** and resolved through the entity resolver — every record traces back to an actual source URL, honoring the assignment's "no hallucinated data" requirement.

## Project Structure
```
graphone-pipeline/
├── main.py # Entry point — orchestrates the full run
├── config/
│ ├── settings.py # All tunables: concurrency, retries, LLM chain
│ └── seed_entities.json # 50 canonical AI startups + aliases (Phase IV)
├── src/
│ ├── schemas/models.py # Pydantic models = the canonical JSON schema contract
│ ├── utils/
│ │ ├── http_client.py # Async HTTP w/ retry + exp backoff + jitter
│ │ ├── date_parser.py # Relative/absolute date normalization
│ │ └── chunking.py # Token-aware chunking (413 avoidance)
│ ├── scrapers/
│ │ ├── arxiv_scraper.py # Research papers (Phase I)
│ │ ├── github_enricher.py # GitHub star enrichment
│ │ ├── rss_news_scraper.py # News signals from 5 RSS sources (Phase II)
│ │ ├── jobs_scraper.py # Remotive job board (Phase II)
│ │ ├── remoteok_scraper.py # RemoteOK job board (Phase II)
│ │ ├── multi_board_scraper.py # Arbeitnow & Jobicy boards (Phase II)
│ │ ├── angellist_scraper.py # Wellfound board (Phase II)
│ │ ├── weworkremotely_scraper.py # WeWorkRemotely board (Phase II)
│ │ ├── yc_scraper.py # Y Combinator startups (Phase I)
│ │ ├── yc_products_scraper.py # Y Combinator products (Phase I)
│ │ └── js_rendered_scraper.py # Playwright pattern for JS/anti-bot sources (Phase V)
│ ├── llm/orchestrator.py # Multi-tier LLM fallback chain (Phase III)
│ ├── resolver/entity_resolver.py # Exact/alias/fuzzy entity resolution (Phase IV)
│ └── storage/
│ ├── dedupe.py # SQLite freshness/dedupe tracking
│ └── csv_writer.py # Output → CSV (import into Google Sheets)
├── output/ # Generated CSV files (excluded from git)
├── logs/ # Pipeline logs (excluded from git)
├── tests/ # Unit tests for core logic
├── requirements.txt
├── architecture.pdf # Design doc (Phase VI)
└── README.md # This file
```

## Setup

### Prerequisites
- Python 3.11+
- Git

### Installation

```bash
# Clone the repository
git clone https://github.com/SSrushti-s/Graphone_pipeline.git
cd Graphone_pipeline

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers (for JS rendering - Phase V)
playwright install chromium
```
Environment Variables 
Create a .env file or export directly:

bash
# GitHub Token (raises API limit 60/hr -> 5000/hr)
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxx"

# LLM API Keys (for Phase III - News Structuring)
export GEMINI_API_KEY="AIzaSyxxxxxxxxxxxxxxxx"
export GROQ_API_KEY="gsk_xxxxxxxxxxxxxxxx"
export DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxx"

# Scraper Concurrency
export SCRAPER_MAX_CONCURRENCY=100

# Full Pipeline Run
## Clean previous run (optional)
rm -f output/seen_urls.sqlite3

## Run with all verticals
python main.py --papers 1000 --news 200 --jobs 500 --startups 1002 --products 1000

# Run Specific Verticals
# Only research papers
python main.py --papers 1000 --news 0 --jobs 0 --startups 0 --products 0

# Only news
python main.py --papers 0 --news 200 --jobs 0 --startups 0 --products 0

# Only jobs
python main.py --papers 0 --news 0 --jobs 500 --startups 0 --products 0

# Only startups & products
python main.py --papers 0 --news 0 --jobs 0 --startups 1002 --products 1000

# Performance Optimization
# Increase concurrency for faster scraping
export SCRAPER_MAX_CONCURRENCY=200
python main.py --papers 1000 --news 200 --jobs 500 --startups 1002 --products 1000
