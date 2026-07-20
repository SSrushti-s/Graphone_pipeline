"""
Date normalization for the 'Freshness Challenge' (Phase II).

Handles:
- Absolute dates in many formats (via dateutil)
- Relative dates: "2 hours ago", "yesterday", "3 days ago", "just now"
- Missing/absent dates -> heuristic fallback (caller decides what to do)

Interview talking point: freshness correctness matters more than freshness
recall here — a false "fresh" record pollutes the 24h guarantee, so on
ambiguity we return None rather than guess, and let the caller apply the
"seen before" heuristic (src/storage/dedupe.py) as the fallback signal.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as dateutil_parser

_RELATIVE_PATTERN = re.compile(
    r"(?P<num>\d+)\s*(?P<unit>second|minute|min|hour|hr|day|week|month)s?\s*ago",
    re.IGNORECASE,
)

_UNIT_TO_SECONDS = {
    "second": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600,
    "day": 86400, "week": 604800, "month": 2592000,
}


def parse_published_date(raw: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort parse of a publish date string into an aware UTC datetime."""
    if not raw or not raw.strip():
        return None
    raw = raw.strip()
    now = now or datetime.now(timezone.utc)

    lowered = raw.lower()
    if "just now" in lowered or lowered in ("now", "moments ago"):
        return now
    if "yesterday" in lowered:
        return now - timedelta(days=1)
    if "today" in lowered:
        return now

    m = _RELATIVE_PATTERN.search(lowered)
    if m:
        num = int(m.group("num"))
        unit = m.group("unit")
        seconds = _UNIT_TO_SECONDS.get(unit, 0) * num
        return now - timedelta(seconds=seconds)

    try:
        dt = dateutil_parser.parse(raw, fuzzy=True)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError):
        return None


def is_within_hours(dt: Optional[datetime], hours: int, now: Optional[datetime] = None) -> bool:
    if dt is None:
        return False
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) <= timedelta(hours=hours) and dt <= now + timedelta(minutes=5)
