"""Tests for the Orchestrator graph (app.agents.orchestrator) — verifies the
audio -> hypothesis -> retrieval -> selection -> explanation wiring,
including FR-1.2 clustering and the explanation-fallback-to-rationale path.

All four delegated calls (audio analysis, hypothesis generation, retrieval,
explanation generation) are mocked — this tests orchestration, not the LLM
or network behavior of the pieces themselves, which are covered by their own
modules' tests / SETUP.md live-testing.
"""

from app.agents import orchestrator
from app.agents.audio import AudioAnalysisResult
from app.agents.retrieval import Candidate, EvidenceItem, RetrievalResult
from app.services.hypothesis import HypothesisCluster, HypothesisResult


def make_candidate(title: str, artist: str, strength: float = 0.8) -> Candidate:
    return Candidate(
        title=title,
        artist=artist,
        sources=["musicbrainz"],
        evidence=[
            EvidenceItem(source="musicbrainz", evidence_type="metadata_similarity", summary="x")
        ],
        recommendation_strength=strength,
        rationale="fallback rationale",
        variant="original",
    )


async def test_single_cluster_happy_path(monkeypatch):
    async def fake_analyze(query):
        return AudioAnalysisResult(query=query, caption=f"caption for {query}")

    async def fake_hypotheses(songs, audio_results):
        return HypothesisResult(
            clusters=[
                HypothesisCluster(theme="rock", songs=songs, hypothesis="upbeat rock")
            ]
        )

    async def fake_retrieval(hypothesis):
        assert hypothesis == "upbeat rock"
        return RetrievalResult(
            candidates=[make_candidate("Song A", "Artist A"), make_candidate("Song B", "Artist B")],
            providers_queried=["musicbrainz"],
        )

    async def fake_explanations(hypothesis, candidates):
        return {"song a::artist a": "shares a driving guitar riff with your input song"}

    monkeypatch.setattr(orchestrator, "analyze_input_song", fake_analyze)
    monkeypatch.setattr(orchestrator, "generate_hypotheses", fake_hypotheses)
    monkeypatch.setattr(orchestrator, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(orchestrator, "generate_explanations", fake_explanations)

    result = await orchestrator.run_discovery(["Song X"], target_count=10)

    assert len(result.audio_analysis) == 1
    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert cluster.theme == "rock"
    assert cluster.hypothesis == "upbeat rock"
    assert cluster.input_songs == ["Song X"]

    titles = {r.title: r.explanation for r in cluster.recommendations}
    assert titles["Song A"] == "shares a driving guitar riff with your input song"
    # Missing from the mocked explanation map -> falls back to the candidate's rationale.
    assert titles["Song B"] == "fallback rationale"


async def test_divergent_songs_produce_separate_clusters(monkeypatch):
    calls = []

    async def fake_analyze(query):
        return AudioAnalysisResult(query=query, caption=None, error="download failed: no results")

    async def fake_hypotheses(songs, audio_results):
        return HypothesisResult(
            clusters=[
                HypothesisCluster(
                    theme="classical", songs=[songs[0]], hypothesis="calm orchestral"
                ),
                HypothesisCluster(theme="metal", songs=[songs[1]], hypothesis="aggressive metal"),
            ]
        )

    async def fake_retrieval(hypothesis):
        calls.append(hypothesis)
        return RetrievalResult(candidates=[make_candidate("X", "Y")], providers_queried=[])

    async def fake_explanations(hypothesis, candidates):
        return {}

    monkeypatch.setattr(orchestrator, "analyze_input_song", fake_analyze)
    monkeypatch.setattr(orchestrator, "generate_hypotheses", fake_hypotheses)
    monkeypatch.setattr(orchestrator, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(orchestrator, "generate_explanations", fake_explanations)

    result = await orchestrator.run_discovery(["Calm Song", "Heavy Song"])

    assert sorted(calls) == ["aggressive metal", "calm orchestral"]
    assert len(result.clusters) == 2
    themes = {c.theme: c.hypothesis for c in result.clusters}
    assert themes == {"classical": "calm orchestral", "metal": "aggressive metal"}
    # Audio failed for both -> graceful degradation, hypothesis generation still ran.
    assert all(a.caption is None for a in result.audio_analysis)
