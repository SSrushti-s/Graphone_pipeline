"""
Freshness / dedupe tracking store.

For the trial: SQLite with a hashed-URL primary key -- single-writer,
zero-ops, good enough for a single-node run.

For production (500k+, distributed crawler nodes): the same interface
(`seen`, `mark_seen`) would be backed by Redis (SETNX with TTL) so multiple
crawler workers share one dedupe view with atomic check-and-set instead of
racing on a local file. See architecture.pdf section 3 for the full
distributed design. Keeping the interface identical means swapping the
backend is a one-file change (src/storage/dedupe.py), not a pipeline rewrite.
"""
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.settings import STORAGE, FRESHNESS


class DedupeStore:
    def __init__(self, db_path: str = STORAGE.dedupe_db_path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_urls (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                first_seen_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    @staticmethod
    def _hash(url: str) -> str:
        return hashlib.sha256(url.strip().lower().encode()).hexdigest()

    def seen(self, url: str) -> bool:
        h = self._hash(url)
        cur = self.conn.execute("SELECT 1 FROM seen_urls WHERE url_hash = ?", (h,))
        return cur.fetchone() is not None

    def mark_seen(self, url: str):
        h = self._hash(url)
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_urls (url_hash, url, first_seen_at) VALUES (?, ?, ?)",
            (h, url, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def purge_older_than(self, days: int = FRESHNESS.dedupe_ttl_days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        self.conn.execute("DELETE FROM seen_urls WHERE first_seen_at < ?", (cutoff,))
        self.conn.commit()

    def close(self):
        self.conn.close()
