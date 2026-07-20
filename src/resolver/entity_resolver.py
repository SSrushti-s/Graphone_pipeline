"""
Deterministic Entity Resolution (Phase IV).

Resolution ladder, cheapest/most-confident first:
  1. Exact match (normalized) against canonical names
  2. Alias match against the seed list's known aliases
  3. Fuzzy match (token-sort ratio) against canonical + alias corpus
  4. (optional) LLM tie-break for ambiguous fuzzy matches near the threshold

Interview talking point: doing fuzzy matching LAST and only as a narrow
band around the threshold (not for everything) keeps resolution both fast
(no O(n) fuzzy compare per record against a huge canonical set once aliases
cover the common cases) and precise (fuzzy matching alone over-merges
similarly-named but distinct companies).
"""
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    from rapidfuzz import fuzz, process
except ImportError:
    from difflib import SequenceMatcher

    class _FuzzFallback:
        @staticmethod
        def token_sort_ratio(a: str, b: str) -> float:
            a_sorted = " ".join(sorted(a.lower().split()))
            b_sorted = " ".join(sorted(b.lower().split()))
            return SequenceMatcher(None, a_sorted, b_sorted).ratio() * 100

    class _ProcessFallback:
        @staticmethod
        def extractOne(query, choices, scorer=None):
            scorer = scorer or _FuzzFallback.token_sort_ratio
            best, best_score = None, -1.0
            for choice in choices:
                score = scorer(query, choice)
                if score > best_score:
                    best, best_score = choice, score
            return (best, best_score, None) if best is not None else None

    fuzz = _FuzzFallback()
    process = _ProcessFallback()

from config.settings import STORAGE
from src.schemas.models import EntityMappingLog

logger = logging.getLogger("graphone.resolver")

FUZZY_ACCEPT_THRESHOLD = 90   # auto-accept above this score
FUZZY_REVIEW_THRESHOLD = 75   # below this, no match


def _normalize(name: str) -> str:
    n = name.lower().strip()
    n = re.sub(r"[.,]", "", n)
    n = re.sub(r"\b(inc|llc|ltd|pbc|lp|corp|corporation|co)\b\.?", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


@dataclass
class ResolutionResult:
    canonical_name: Optional[str]
    method: str          # "exact" | "alias" | "fuzzy" | "unresolved"
    confidence: float


class EntityResolver:
    def __init__(self, seed_path: str = STORAGE.entity_seed_path):
        self.seed: dict[str, list[str]] = json.loads(Path(seed_path).read_text())
        self._alias_to_canonical: dict[str, str] = {}
        self._exact_index: dict[str, str] = {}
        self._all_aliases: list[str] = []

        for canonical, aliases in self.seed.items():
            self._exact_index[_normalize(canonical)] = canonical
            for alias in aliases:
                norm = _normalize(alias)
                self._alias_to_canonical[norm] = canonical
                self._all_aliases.append(alias)

        self.mapping_log: list[EntityMappingLog] = []

    def resolve(self, raw_name: str, entity_type: str = "STARTUP") -> ResolutionResult:
        if not raw_name or not raw_name.strip():
            return ResolutionResult(None, "unresolved", 0.0)

        norm = _normalize(raw_name)

        # 1. exact match on canonical names
        if norm in self._exact_index:
            result = ResolutionResult(self._exact_index[norm], "exact", 1.0)
            self._log(raw_name, result, entity_type)
            return result

        # 2. alias match
        if norm in self._alias_to_canonical:
            result = ResolutionResult(self._alias_to_canonical[norm], "alias", 0.98)
            self._log(raw_name, result, entity_type)
            return result

        # 3. fuzzy match against all known aliases + canonical names
        corpus = self._all_aliases + list(self.seed.keys())
        match = process.extractOne(raw_name, corpus, scorer=fuzz.token_sort_ratio)
        if match:
            matched_str, score, _ = match
            if score >= FUZZY_ACCEPT_THRESHOLD:
                canonical = self._alias_to_canonical.get(_normalize(matched_str), matched_str)
                result = ResolutionResult(canonical, "fuzzy", score / 100.0)
                self._log(raw_name, result, entity_type)
                return result

        # unresolved -- new entity, not in seed list. In production this
        # would be queued for LLM-assisted canonicalization + human review
        # rather than silently dropped or auto-created.
        result = ResolutionResult(raw_name.strip(), "unresolved", 0.0)
        self._log(raw_name, result, entity_type)
        return result

    def _log(self, raw_name: str, result: ResolutionResult, entity_type: str):
        self.mapping_log.append(EntityMappingLog(
            raw_name=raw_name,
            canonical_name=result.canonical_name or raw_name,
            match_method=result.method,
            confidence=result.confidence,
            entity_type=entity_type,
        ))

    def export_mapping_log(self) -> list[dict]:
        return [m.model_dump() for m in self.mapping_log]
