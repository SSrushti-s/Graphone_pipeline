"""
Unit tests for the network-independent logic: date parsing, chunking,
entity resolution. Run with: python -m pytest tests/ -v
(requires `pip install -r requirements.txt` first)
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.date_parser import parse_published_date, is_within_hours
from src.utils.chunking import chunk_text, estimate_tokens
from src.resolver.entity_resolver import EntityResolver
from config.settings import LLMConfig


class TestDateParser:
    def test_relative_hours(self):
        now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        result = parse_published_date("2 hours ago", now)
        assert result.hour == 10

    def test_yesterday(self):
        now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        result = parse_published_date("yesterday", now)
        assert result.day == 17

    def test_absolute_iso(self):
        result = parse_published_date("2024-01-15T10:00:00Z")
        assert result.year == 2024 and result.month == 1

    def test_missing_date_returns_none(self):
        assert parse_published_date(None) is None
        assert parse_published_date("") is None

    def test_freshness_window(self):
        now = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        fresh = parse_published_date("2 hours ago", now)
        stale = parse_published_date("3 days ago", now)
        assert is_within_hours(fresh, 24, now) is True
        assert is_within_hours(stale, 24, now) is False


class TestChunking:
    def test_short_text_not_chunked(self):
        text = "Short text."
        chunks = chunk_text(text, max_tokens=1000)
        assert len(chunks) == 1

    def test_long_text_chunked_under_budget(self):
        text = ("Paragraph about AI research and startups. " * 100 + "\n\n") * 10
        chunks = chunk_text(text, max_tokens=200, overlap_tokens=20)
        assert len(chunks) > 1
        for c in chunks:
            # allow overlap slop but should be in the right ballpark
            assert estimate_tokens(c) < 400


class TestLLMConfig:
    def test_parses_multiple_groq_keys(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEYS", "key-1, key-2, key-3")
        cfg = LLMConfig()
        assert cfg.groq_api_keys == ["key-1", "key-2", "key-3"]


class TestEntityResolver:
    def setup_method(self):
        self.resolver = EntityResolver()

    def test_exact_match(self):
        result = self.resolver.resolve("OpenAI")
        assert result.canonical_name == "OpenAI"
        assert result.method == "exact"

    def test_alias_match(self):
        result = self.resolver.resolve("Open AI")
        assert result.canonical_name == "OpenAI"
        assert result.method == "alias"

    def test_suffix_normalization(self):
        result = self.resolver.resolve("OpenAI, Inc.")
        assert result.canonical_name == "OpenAI"

    def test_unresolved_new_entity(self):
        result = self.resolver.resolve("Totally Unknown Startup Corp")
        assert result.method == "unresolved"

    def test_mapping_log_populated(self):
        self.resolver.resolve("OpenAI")
        self.resolver.resolve("Anthropic")
        log = self.resolver.export_mapping_log()
        assert len(log) == 2
