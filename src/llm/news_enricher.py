"""
LLM-based news enrichment (Phase III).

Takes a NewsRecord that already has full_text populated (see
src/utils/article_extractor.py) and runs it through the multi-tier LLM
fallback chain to extract a structured summary and named entities --
this is the concrete "structure raw HTML/text into canonical JSON schema
using LLMs" requirement from the assignment, applied to real scraped
article content rather than a synthetic example.

A record whose LLM response fails to parse as valid JSON, or is missing
required keys, is left with llm_summary=None / llm_entities=[] rather
than partially filled with guessed values -- consistent with the
no-hallucination rule applied everywhere else in this pipeline.
"""
import logging

from src.llm.orchestrator import LLMOrchestrator
from src.schemas.models import NewsRecord

logger = logging.getLogger("graphone.llm.news_enricher")

SYSTEM_PROMPT = """You are a precise information extraction system. Given a news
article's full text, extract ONLY the following as JSON, with no preamble,
no markdown fences, and no commentary:

{
  "summary": "<2-3 sentence factual summary of the article, in your own words>",
  "entities": ["<company or product names explicitly mentioned>", "..."]
}

Rules:
- summary must be grounded only in the provided text -- do not add outside knowledge.
- entities should be company/product/organization names only, not people or generic terms.
- If the text is too short or unclear to summarize confidently, return
  {"summary": null, "entities": []} rather than guessing.
- Output ONLY the JSON object, nothing else.
"""


class NewsLLMEnricher:
    def __init__(self, orchestrator: LLMOrchestrator | None = None):
        self.orchestrator = orchestrator or LLMOrchestrator()

    async def enrich(self, record: NewsRecord) -> NewsRecord:
        if not record.content.full_text:
            return record  # nothing to extract from

        result = await self.orchestrator.extract(SYSTEM_PROMPT, record.content.full_text)
        if result is None:
            logger.warning(f"LLM enrichment failed for {record.content.url}, leaving fields empty")
            return record

        summary = result.get("summary")
        entities = result.get("entities")

        if isinstance(summary, str) and summary.strip():
            record.content.llm_summary = summary.strip()
        if isinstance(entities, list):
            record.content.llm_entities = [e for e in entities if isinstance(e, str)]

        return record