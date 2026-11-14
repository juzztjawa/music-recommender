"""discover_from_playlists with the Spotify client stubbed out."""

from app.clients import spotify_playlists as sp
from app.services import playlist_discovery as disc
from app.services.playlist_scoring import Seed


def pl(pid, owner="user"):
    return {
        "id": pid,
        "name": "sad indie",
        "description": "",
        "owner_id": owner,
        "owner_name": owner,
        "total": 30,
        "url": None,
    }


def tracks(near: str):
    seed = {
        "position": 0,
        "spotify_id": "s",
        "title": "Let Down",
        "artists": ["Radiohead"],
        "url": None,
    }
    nxt = {"position": 1, "spotify_id": "n", "title": near, "artists": ["N"], "url": None}
    rest = [
        {
            "position": i + 2,
            "spotify_id": f"x{i}",
            "title": f"f{near}{i}",
            "artists": [f"a{i}{near}"],
            "url": None,
        }
        for i in range(12)
    ]
    return [seed, nxt, *rest]


async def test_discovery_returns_scored_candidates_and_survives_bad_playlists(monkeypatch):
    async def fake_search(q, limit=10, offset=0):
        if q == "boom":
            raise sp.SpotifyRateLimited("429")
        return [pl("p1"), {**pl("p2"), "owner_id": "other"}, pl("p3")]

    async def fake_tracks(pid, max_tracks=200):
        return None if pid == "p3" else tracks("Shared")

    monkeypatch.setattr(sp, "search_playlists", fake_search)
    monkeypatch.setattr(sp, "get_playlist_tracks", fake_tracks)

    out = await disc.discover_from_playlists([Seed("Let Down", "Radiohead")], ["sad indie", "boom"])

    assert [c["title"] for c in out["candidates"]][:1] == ["Shared"]
    assert out["candidates"][0]["owners"] == 2
    assert out["stats"]["playlists_unreadable"] == 1
    assert any("boom" in e for e in out["stats"]["errors"])


async def test_search_queries_are_bounded_and_deduplicated(monkeypatch):
    monkeypatch.setattr(disc.settings, "playlist_max_searches", 3)
    qs = disc._search_queries([Seed("A", "X"), Seed("B", "Y")], ["Vibe", "vibe"])
    assert len(qs) == 3 and qs[0] == "Vibe"
