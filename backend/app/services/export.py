"""FR-16 export: turn a stored discovery result into CSV / JSON.

Pure functions over the `DiscoveryResult` dict shape, so they are unit-tested
without a database. Spotify playlist export is not here — it needs per-tester
OAuth and is tracked separately.
"""

import csv
import io
import json
from typing import Any

CSV_COLUMNS = [
    "cluster",
    "title",
    "artist",
    "recommendation_strength",
    "variant",
    "sources",
    "explanation",
]


def to_csv(result: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    for cluster in result.get("clusters", []):
        for rec in cluster.get("recommendations", []):
            writer.writerow(
                [
                    cluster.get("theme", ""),
                    rec["title"],
                    rec["artist"],
                    rec.get("recommendation_strength", ""),
                    rec.get("variant", ""),
                    "; ".join(rec.get("sources", [])),
                    rec.get("explanation", ""),
                ]
            )
    return buf.getvalue()


def to_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)
