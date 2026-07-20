# GraphOne Intelligence Graph — Data Pipeline

Async, fault-tolerant ingestion pipeline for the AI/venture ecosystem
Intelligence Graph. Built for the AI Engineer / Data Intelligence trial
assignment.

## What this actually does

Runs three **real, live** scrapers end-to-end (no mocked data):

| Source | What it collects | Why this source |
|---|---|---|
| **arXiv API** | Research papers (title, authors, URL, published date) | Official public Atom API, no auth, generous rate limits |
| **GitHub REST API** | Star counts for papers with linked repos | Official public API, matches "dynamic metrics" requirement |
| **Hacker News (Firebase API)** | AI-related news, 24h freshness filtered | Official public API, exercises the strict-timestamp freshness path |
| **Remotive API** | AI/remote job postings | Public JSON API, exercises job-board ingestion + role classification |

Startup records are **derived from real job postings' company field**,
resolved through the entity resolver — every startup record traces back
to an actual source URL (a real job posting), honoring the assignment's
"no hallucinated data" requirement, rather than being invented.

**What's architected but not live-run here:** Papers with Code (JS-rendered,
bot-protected in practice) and a dedicated startup/product directory
scrape are implemented as a documented pattern (`js_rendered_scraper.py`)
rather than executed against production anti-bot walls — see
`architecture.pdf` §5 for why, and what "live" would require.

## Project structure

```
graphone-pipeline/
├── main.py                        # Entry point — orchestrates the full run
├── config/
│   ├── settings.py                 # All tunables: concurrency, retries, LLM chain
│   └── seed_entities.json          # 50 canonical AI startups + aliases (Phase IV)
├── src/
│   ├── schemas/models.py           # Pydantic models = the canonical JSON schema contract
│   ├── utils/
│   │   ├── http_client.py          # Async HTTP w/ retry + exp backoff + jitter
│   │   ├── date_parser.py          # Relative/absolute date normalization
│   │   └── chunking.py             # Token-aware chunking (413 avoidance)
│   ├── scrapers/
│   │   ├── arxiv_scraper.py        # Research papers (Phase I)
│   │   ├── github_enricher.py      # GitHub star enrichment
│   │   ├── hn_scraper.py           # News signal (Phase II)
│   │   ├── jobs_scraper.py         # Job board (Phase II)
│   │   └── js_rendered_scraper.py  # Playwright pattern for JS/anti-bot sources (Phase V)
│   ├── llm/orchestrator.py         # Multi-tier LLM fallback chain (Phase III)
│   ├── resolver/entity_resolver.py # Exact/alias/fuzzy entity resolution (Phase IV)
│   └── storage/
│       ├── dedupe.py                # SQLite freshness/dedupe tracking
│       └── csv_writer.py            # Output → CSV (import into Google Sheets)
├── requirements.txt
└── architecture.pdf                 # Design doc (Phase VI)
```

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium       # only needed if you use js_rendered_scraper.py
```

### Environment variables (optional but recommended)

Create a `.env` file or export directly:

```bash
export GROQ_API_KEYS="key-1,key-2,key-3,key-4,key-5"  # https://console.groq.com/keys
export GROQ_API_KEY="key-1"                           # fallback single-key compatibility
export GITHUB_TOKEN="..."                            # optional — raises GitHub API limit 60/hr -> 5000/hr
```

None of these are required to run the core scrapers (arXiv, HN, Remotive,
GitHub unauthenticated) — they're only needed if you plug the LLM
orchestrator into a live extraction task (e.g. structuring messy news
full-text into the canonical schema).

## Running it

```bash
python main.py --papers 1000 --news 200 --jobs 500
```

Output lands in `./output/`:
- `research_papers.csv`
- `news.csv`
- `jobs.csv`
- `startups.csv`
- `entity_mapping_log.csv`

Import each CSV as a separate tab in Google Sheets
(File → Import → Upload → "Insert as new sheet") to produce the 5-tab
deliverable (Products tab: see note below).

**Note on the Products tab:** the trial's Products schema wasn't populated
by any of the three live sources above (none of arXiv/HN/Remotive expose
product-level pricing data) — see `architecture.pdf` for the intended
source (e.g. a startup directory's product listings) and why it's
documented rather than executed here.

## Scaling from trial to 500k+ (no code changes)

Every knob is in `config/settings.py`:

```python
SCRAPER_MAX_CONCURRENCY=200        # up from 20
GROQ_API_KEYS=key-1,key-2,key-3,key-4,key-5 GITHUB_TOKEN=... # unlocks 80x GitHub throughput
```

Then: run N worker processes each pulling a distinct arXiv category /
job-board page range, all writing through the same dedupe store (swapped
to Redis for cross-node dedupe — see `architecture.pdf` §3). This is
infra scaling (more workers, higher concurrency, a shared dedupe backend),
not a code rewrite.

## Testing what's here right now

Every module was syntax-checked and the network-independent logic
(date parsing, chunking, entity resolution) was unit-tested during
development. Sample verified behavior:

```
'OpenAI, Inc.'  -> 'OpenAI'      (exact match, normalized)
'Open AI'       -> 'OpenAI'      (alias match)
'antropic'      -> 'Anthropic'   (fuzzy match, 94% confidence)
'2 hours ago'   -> correctly resolves to a timestamp 2h before now
```

Run `python -m pytest tests/` once you've installed dependencies (test
stubs included — see `tests/`).
