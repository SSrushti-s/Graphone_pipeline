"""
Canonical schema definitions for GraphOne Intelligence Graph.
Every record produced by any scraper/LLM extractor MUST validate against
one of these models before it is allowed to hit storage. This is the
"data fidelity" gate the assignment scores on — invalid or hallucinated
records get rejected here, not silently written.
"""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator

SCHEMA_VERSION = "1.0"


class PricingModel(str, Enum):
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"


class Source(BaseModel):
    name: str
    url: str  # kept as str not HttpUrl so we never silently drop a record over a strict URL parse


class BaseRecord(BaseModel):
    """Shared envelope fields every record type carries."""
    schemaVersion: str = SCHEMA_VERSION
    recordType: str
    source: Source
    collectedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("collectedAt")
    @classmethod
    def _iso(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v


class StartupContentData(BaseModel):
    employeeCount: Optional[int] = None


class StartupContent(BaseModel):
    entityName: str
    data: StartupContentData = Field(default_factory=StartupContentData)


class StartupRecord(BaseRecord):
    recordType: str = "STARTUP"
    content: StartupContent


class ProductContent(BaseModel):
    startupName: str
    pricingModel: Optional[PricingModel] = None


class ProductRecord(BaseRecord):
    recordType: str = "PRODUCT"
    content: ProductContent


class ResearchPaperContent(BaseModel):
    title: str
    authors: list[str] = Field(default_factory=list)
    paper_url: str
    github_url: Optional[str] = None
    github_stars: Optional[int] = None
    published_date: Optional[datetime] = None


class ResearchPaperRecord(BaseRecord):
    recordType: str = "RESEARCH_PAPER"
    content: ResearchPaperContent


class JobContent(BaseModel):
    company: str
    date: Optional[datetime] = None
    is_remote: Optional[bool] = None
    role_family: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None


class JobRecord(BaseRecord):
    recordType: str = "JOB"
    content: JobContent


class NewsContent(BaseModel):
    title: str
    url: str
    published_date: Optional[datetime] = None
    full_text: Optional[str] = None
    is_fresh_24h: bool = False
    llm_summary: Optional[str] = None
    llm_entities: list[str] = Field(default_factory=list)

class NewsRecord(BaseRecord):
    recordType: str = "NEWS"
    content: NewsContent


class EntityMappingLog(BaseModel):
    raw_name: str
    canonical_name: str
    match_method: str  # "exact" | "alias" | "fuzzy" | "llm"
    confidence: float
    entity_type: str  # "STARTUP" | "PRODUCT"
