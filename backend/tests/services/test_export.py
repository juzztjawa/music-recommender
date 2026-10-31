"""Tests for CSV/JSON export (app.services.export)."""

import csv
import io
import json

from app.services.export import CSV_COLUMNS, to_csv, to_json

RESULT = {
    "clusters": [
        {
            "theme": "orchestral rock",
            "recommendations": [
                {
                    "title": 'Song, "A"',
                    "artist": "Artist A",
                    "recommendation_strength": 0.9,
                    "variant": "original",
                    "sources": ["spotify", "reddit"],
                    "explanation": "shares soaring builds",
                }
            ],
        },
        {"theme": "empty", "recommendations": []},
    ]
}


def test_csv_round_trips_awkward_characters():
    rows = list(csv.DictReader(io.StringIO(to_csv(RESULT))))
    assert list(rows[0].keys()) == CSV_COLUMNS
    assert len(rows) == 1
    assert rows[0]["title"] == 'Song, "A"'
    assert rows[0]["sources"] == "spotify; reddit"
    assert rows[0]["cluster"] == "orchestral rock"


def test_csv_header_only_when_no_recommendations():
    assert to_csv({"clusters": []}).strip() == ",".join(CSV_COLUMNS)


def test_json_is_lossless():
    assert json.loads(to_json(RESULT)) == RESULT
