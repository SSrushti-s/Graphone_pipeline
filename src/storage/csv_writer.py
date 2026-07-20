"""
Writes pipeline output to CSV files -- one per tab required in the
deliverable spec (Startups, Products, Research Papers, Jobs, News,
Entity Mapping Log). These CSVs are exactly what you import into Google
Sheets (File > Import > Upload, one tab per file) to produce the
"public Google Sheet link" deliverable.
"""
import csv
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("graphone.storage.csv")


def write_records_to_csv(records: list[dict], path: str, fieldnames: list[str]):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(_flatten(record))
    logger.info(f"Wrote {len(records)} records to {path}")


def _flatten(d: dict, parent_key: str = "", sep: str = ".") -> dict[str, Any]:
    items = {}
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.update(_flatten(v, new_key, sep))
        elif isinstance(v, list):
            items[new_key] = "; ".join(str(x) for x in v)
        else:
            items[new_key] = v
    return items
