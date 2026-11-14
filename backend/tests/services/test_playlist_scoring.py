"""Behaviours the playlist scoring must preserve (see app/services/playlist_scoring.py)."""

from app.services.playlist_scoring import (
    PlaylistInput,
    Seed,
    norm_title,
    score_candidates,
)

SEED = Seed("Let Down", "Radiohead")


def tr(pos: int, title: str, artist: str) -> dict:
    return {
        "position": pos,
        "spotify_id": f"id-{title}",
        "title": title,
        "artists": [artist],
        "url": f"https://open.spotify.com/track/{title}",
    }


def playlist(
    pid: str, owner: str, titles: list[tuple[str, str]], name="sad indie"
) -> PlaylistInput:
    return PlaylistInput(pid, name, "", owner, [tr(i, t, a) for i, (t, a) in enumerate(titles)])


def filler(n: int, tag: str) -> list[tuple[str, str]]:
    return [(f"{tag}{i}", f"{tag}Artist{i}") for i in range(n)]


def near_seed(neighbor: tuple[str, str], tag: str) -> list[tuple[str, str]]:
    return [*filler(10, tag + "a"), ("Let Down", "Radiohead"), neighbor, *filler(10, tag + "b")]


def test_title_normalisation_ignores_remaster_and_live_suffixes():
    assert norm_title("Let Down - Remastered 2016") == norm_title("Let Down (Live)") == "let down"


def test_playlists_without_the_seed_or_its_artist_are_ignored():
    p = playlist("p1", "u1", filler(30, "x"))
    assert score_candidates([p], [SEED]) == []


def test_seed_itself_is_never_recommended():
    ps = [playlist(f"p{i}", f"u{i}", near_seed(("Song A", "A"), str(i))) for i in range(3)]
    titles = {c.title for c in score_candidates(ps, [SEED])}
    assert "Let Down" not in titles and "Song A" in titles


def test_neighbour_of_the_seed_beats_a_distant_track():
    tracks = [("Let Down", "Radiohead"), ("Near", "N"), *filler(40, "f"), ("Far", "F")]
    ps = [
        PlaylistInput(
            f"p{i}", "mood", "", f"u{i}", [tr(j, t, a) for j, (t, a) in enumerate(tracks)]
        )
        for i in range(2)
    ]
    scores = {c.title: c.score for c in score_candidates(ps, [SEED], limit=100)}
    assert scores["Near"] > scores["Far"]


def test_one_owner_with_many_playlists_cannot_manufacture_consensus():
    farm = [playlist(f"f{i}", "farmer", near_seed(("Spam", "S"), f"f{i}")) for i in range(5)]
    real = [playlist(f"r{i}", f"user{i}", near_seed(("Real", "R"), f"r{i}")) for i in range(2)]
    result = {c.title: c for c in score_candidates(farm + real, [SEED], min_owners=1, limit=200)}
    assert result["Spam"].owners == 1 and result["Real"].owners == 2
    assert result["Real"].score > result["Spam"].score


def test_user_built_outranks_editorial_playlists():
    ed = playlist("e", "spotify", near_seed(("Editorial", "E"), "e"))
    us = playlist("u", "someone", near_seed(("UserPick", "U"), "u"))
    result = {c.title: c.score for c in score_candidates([ed, us], [SEED], min_owners=1, limit=100)}
    assert result["UserPick"] > result["Editorial"]


def test_globally_ubiquitous_tracks_are_discounted():
    hit = ("Hit", "Pop")
    anchored = [
        playlist(f"a{i}", f"u{i}", [*near_seed(("Niche", "N"), f"a{i}"), hit]) for i in range(3)
    ]
    # the same ubiquitous track appears in many unrelated playlists too
    unrelated = [playlist(f"o{i}", f"v{i}", [*filler(20, f"o{i}"), hit]) for i in range(30)]
    scores = {c.title: c.score for c in score_candidates(anchored + unrelated, [SEED])}
    assert scores["Niche"] > scores["Hit"]


def test_single_owner_candidates_are_kept_but_flagged_weak_when_little_else_exists():
    p = playlist("p", "u1", near_seed(("Lonely", "L"), "p"))
    out = score_candidates([p], [SEED], min_owners=2)
    assert out and all(c.weak for c in out)


def test_tiny_playlists_are_ignored():
    p = playlist("p", "u1", [("Let Down", "Radiohead"), ("Tiny", "T")])
    assert score_candidates([p], [SEED]) == []


def test_artist_only_match_counts_less_than_a_song_match():
    song = playlist("s", "u1", near_seed(("ViaSong", "A"), "s"))
    artist_tracks = [
        *filler(10, "q"),
        ("Other Song", "Radiohead"),
        ("ViaArtist", "B"),
        *filler(10, "z"),
    ]
    art = playlist("a", "u2", artist_tracks)
    result = {
        c.title: c.score for c in score_candidates([song, art], [SEED], min_owners=1, limit=100)
    }
    assert result["ViaSong"] > result["ViaArtist"]


def test_live_and_cover_titles_are_hinted():
    ps = [playlist(f"p{i}", f"u{i}", near_seed(("Creep (Live)", "R"), str(i))) for i in range(2)]
    cands = score_candidates(ps, [SEED])
    assert cands[0].variant_hint == "live"


def test_one_artist_cannot_flood_the_pool_and_seed_artist_is_capped_harder():
    same = [("Let Down", "Radiohead")] + [(f"R{i}", "Radiohead") for i in range(6)]
    other = [(f"O{i}", "OtherBand") for i in range(8)]
    ps = [playlist(f"p{i}", f"u{i}", [*filler(10, f"p{i}"), *same, *other]) for i in range(2)]
    out = score_candidates(ps, [SEED], limit=100)
    artists = [c.artist for c in out]
    assert artists.count("Radiohead") == 2  # seed artist capped at MAX_PER_SEED_ARTIST
    assert artists.count("OtherBand") == 4  # others capped at MAX_PER_ARTIST
