"""Unit tests for app.services.selection — FR-8, FR-9.2, FR-10.1-10.5, FR-11."""

from app.agents.retrieval import Candidate, EvidenceItem
from app.services.selection import (
    apply_artist_diversity,
    filter_variants,
    merge_duplicates,
    select_recommendations,
)


def make_candidate(
    title: str,
    artist: str,
    strength: float,
    *,
    sources: list[str] | None = None,
    variant: str = "original",
    evidence: list[EvidenceItem] | None = None,
) -> Candidate:
    return Candidate(
        title=title,
        artist=artist,
        sources=sources or ["musicbrainz"],
        evidence=evidence
        or [EvidenceItem(source="musicbrainz", evidence_type="metadata_similarity", summary="x")],
        recommendation_strength=strength,
        rationale="test rationale",
        variant=variant,
    )


# --- FR-8: consolidation ---


def test_merge_duplicates_combines_sources_and_evidence():
    a = make_candidate(
        "Buddy Holly",
        "Weezer",
        0.6,
        sources=["musicbrainz"],
        evidence=[
            EvidenceItem(source="musicbrainz", evidence_type="metadata_similarity", summary="a")
        ],
    )
    b = make_candidate(
        "buddy holly",
        "weezer",
        0.9,
        sources=["youtube_music"],
        evidence=[
            EvidenceItem(source="youtube_music", evidence_type="community_discussion", summary="b")
        ],
    )

    merged = merge_duplicates([a, b])

    assert len(merged) == 1
    result = merged[0]
    assert set(result.sources) == {"musicbrainz", "youtube_music"}
    assert len(result.evidence) == 2
    # score is the max of the group, not an average
    assert result.recommendation_strength == 0.9


def test_merge_duplicates_leaves_distinct_songs_untouched():
    a = make_candidate("Buddy Holly", "Weezer", 0.6)
    b = make_candidate("Say It Ain't So", "Weezer", 0.7)

    merged = merge_duplicates([a, b])

    assert len(merged) == 2


def test_merge_duplicates_exact_duplicate_provider_entries_collapse():
    # FR-10.2: duplicate provider entries shouldn't survive as two candidates
    a = make_candidate("El Scorcho", "Weezer", 0.5, sources=["spotify"])
    b = make_candidate("El Scorcho", "Weezer", 0.5, sources=["spotify"])

    merged = merge_duplicates([a, b])

    assert len(merged) == 1
    assert merged[0].sources == ["spotify"]


# --- FR-10.1: artist diversity ---


def test_apply_artist_diversity_caps_per_artist():
    candidates = [make_candidate(f"Song {i}", "Weezer", 1.0 - i * 0.1) for i in range(5)]

    capped = apply_artist_diversity(candidates, max_per_artist=3)

    assert len(capped) == 3
    assert [c.title for c in capped] == ["Song 0", "Song 1", "Song 2"]


def test_apply_artist_diversity_leaves_other_artists_alone():
    candidates = [
        make_candidate("A1", "Weezer", 0.9),
        make_candidate("A2", "Weezer", 0.8),
        make_candidate("A3", "Weezer", 0.7),
        make_candidate("A4", "Weezer", 0.6),
        make_candidate("B1", "The Rentals", 0.5),
    ]

    capped = apply_artist_diversity(candidates, max_per_artist=3)

    titles = [c.title for c in capped]
    assert titles == ["A1", "A2", "A3", "B1"]


# --- FR-10.3/10.4: variant filtering ---


def test_filter_variants_drops_live_by_default():
    original = make_candidate("Say It Ain't So", "Weezer", 0.8, variant="original")
    live = make_candidate("Say It Ain't So (Live)", "Weezer", 0.9, variant="live")

    filtered = filter_variants([original, live])

    assert filtered == [original]


def test_filter_variants_keeps_live_when_requested():
    original = make_candidate("Say It Ain't So", "Weezer", 0.8, variant="original")
    live = make_candidate("Say It Ain't So (Live)", "Weezer", 0.9, variant="live")

    filtered = filter_variants([original, live], include_live=True)

    assert set(c.title for c in filtered) == {original.title, live.title}


def test_filter_variants_drops_cover_when_original_present():
    original = make_candidate("Hallelujah", "Leonard Cohen", 0.7, variant="original")
    cover = make_candidate("Hallelujah", "Pentatonix", 0.9, variant="cover")

    filtered = filter_variants([original, cover])

    assert filtered == [original]


def test_filter_variants_keeps_cover_when_no_original_present():
    cover = make_candidate("Hallelujah", "Pentatonix", 0.9, variant="cover")

    filtered = filter_variants([cover])

    assert filtered == [cover]


def test_filter_variants_keeps_cover_when_requested():
    original = make_candidate("Hallelujah", "Leonard Cohen", 0.7, variant="original")
    cover = make_candidate("Hallelujah", "Pentatonix", 0.9, variant="cover")

    filtered = filter_variants([original, cover], include_covers=True)

    assert set(c.title for c in filtered) == {original.title, cover.title}


# --- FR-10.5 + FR-9/FR-11/FR-9.2, via the full pipeline ---


def test_select_recommendations_deprioritizes_remixes():
    original = make_candidate("Song", "Artist A", 0.8, variant="original")
    remix = make_candidate("Song (Remix)", "Artist B", 0.8, variant="remix")

    selected = select_recommendations([original, remix])

    assert [c.title for c in selected] == ["Song", "Song (Remix)"]


def test_select_recommendations_trims_to_target_count():
    candidates = [make_candidate(f"Song {i}", f"Artist {i}", 1.0 - i * 0.01) for i in range(15)]

    selected = select_recommendations(candidates, target_count=10)

    assert len(selected) == 10
    assert selected[0].title == "Song 0"


def test_select_recommendations_does_not_pad_when_few_survive():
    candidates = [make_candidate("Only Song", "Only Artist", 0.5)]

    selected = select_recommendations(candidates, target_count=10)

    assert len(selected) == 1


def test_select_recommendations_full_pipeline_order():
    # merge -> filter -> rank -> diversify -> trim, exercised together
    candidates = [
        make_candidate("Buddy Holly", "Weezer", 0.6, sources=["musicbrainz"]),
        make_candidate("buddy holly", "weezer", 0.95, sources=["youtube_music"]),
        make_candidate("Say It Ain't So (Live)", "Weezer", 0.99, variant="live"),
        make_candidate("El Scorcho", "Weezer", 0.7),
        make_candidate("Pink Triangle", "Weezer", 0.65),
        make_candidate("Undone", "The Rentals", 0.5),
    ]

    selected = select_recommendations(candidates, max_per_artist=3, target_count=10)

    titles = [c.title for c in selected]
    assert "Say It Ain't So (Live)" not in titles  # live excluded by default
    assert sum(1 for t in titles if t.lower() == "buddy holly") == 1  # merged, not duplicated
    weezer_count = sum(1 for c in selected if c.artist.lower() == "weezer")
    assert weezer_count <= 3  # artist cap enforced
