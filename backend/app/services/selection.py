"""Consolidation, selection, and diversification (architecture.md §2, Phase 4).

Deterministic Python over the Retrieval & Evidence Agent's already-scored
candidates — no LLM call here. Implements FR-8 (consolidation), FR-10.1-10.5
(diversification), and FR-11/FR-9.2 (final batch size, no padding to hit a
count). Ranking itself (FR-9) is the agent's `recommendation_strength`; this
module only sorts and trims by it.
"""

import re

from app.agents.retrieval import Candidate, EvidenceItem

REMIX_STRENGTH_PENALTY = 0.85


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def merge_duplicates(candidates: list[Candidate]) -> list[Candidate]:
    """Collapse candidates that share a normalized (artist, title) key.

    Exact-match safety net — the agent already merges duplicates it recognizes
    semantically during retrieval (see its system prompt); this only catches
    what it missed. A merged candidate keeps every source and every evidence
    item (FR-8), with `recommendation_strength`/`rationale`/`variant` taken
    from whichever original member scored highest — finding the same song via
    multiple providers is corroborating evidence, not a reason to average the
    score down.
    """
    groups: dict[tuple[str, str], list[Candidate]] = {}
    order: list[tuple[str, str]] = []
    for candidate in candidates:
        key = (_normalize(candidate.artist), _normalize(candidate.title))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(candidate)

    merged: list[Candidate] = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            merged.append(group[0])
            continue

        best = max(group, key=lambda c: c.recommendation_strength)

        sources: list[str] = []
        for c in group:
            for source in c.sources:
                if source not in sources:
                    sources.append(source)

        evidence: list[EvidenceItem] = []
        seen_evidence: set[tuple[str, str, str]] = set()
        for c in group:
            for item in c.evidence:
                dedup_key = (item.source, item.evidence_type, item.summary)
                if dedup_key not in seen_evidence:
                    seen_evidence.add(dedup_key)
                    evidence.append(item)

        merged.append(
            best.model_copy(update={"sources": sources, "evidence": evidence})
        )

    return merged


def filter_variants(
    candidates: list[Candidate],
    *,
    include_live: bool = False,
    include_covers: bool = False,
) -> list[Candidate]:
    """Drop live recordings and redundant covers per FR-10.3/FR-10.4.

    Live recordings are dropped unless explicitly requested. A cover is
    dropped only when an "original" of the same title is also present in the
    pool (grouped by title alone — a cover keeps the title but changes the
    artist); a cover with no original in the pool is kept, since excluding it
    would just be losing a valid recommendation.
    """
    if not include_live:
        candidates = [c for c in candidates if c.variant != "live"]

    if not include_covers:
        titles_with_original = {
            _normalize(c.title) for c in candidates if c.variant == "original"
        }
        candidates = [
            c
            for c in candidates
            if not (c.variant == "cover" and _normalize(c.title) in titles_with_original)
        ]

    return candidates


def _sort_key(candidate: Candidate) -> float:
    if candidate.variant == "remix":
        return candidate.recommendation_strength * REMIX_STRENGTH_PENALTY
    return candidate.recommendation_strength


def apply_artist_diversity(candidates: list[Candidate], max_per_artist: int = 3) -> list[Candidate]:
    """Cap songs per artist at `max_per_artist` (FR-10.1).

    Expects `candidates` already sorted best-first; keeps the highest-ranked
    entries per artist and preserves the incoming order.
    """
    counts: dict[str, int] = {}
    result: list[Candidate] = []
    for candidate in candidates:
        artist_key = _normalize(candidate.artist)
        count = counts.get(artist_key, 0)
        if count >= max_per_artist:
            continue
        counts[artist_key] = count + 1
        result.append(candidate)
    return result


def select_recommendations(
    candidates: list[Candidate],
    *,
    include_live: bool = False,
    include_covers: bool = False,
    max_per_artist: int = 3,
    target_count: int = 10,
) -> list[Candidate]:
    """Full Phase 4 pipeline: consolidate, filter, rank, diversify, trim.

    Returns at most `target_count` candidates. Returns fewer if fewer survive
    filtering — per FR-9.2, never pad with weakly-supported candidates just to
    hit a requested count.
    """
    merged = merge_duplicates(candidates)
    filtered = filter_variants(merged, include_live=include_live, include_covers=include_covers)
    ranked = sorted(filtered, key=_sort_key, reverse=True)
    diversified = apply_artist_diversity(ranked, max_per_artist=max_per_artist)
    return diversified[:target_count]
