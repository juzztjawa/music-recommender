"""Orchestrator — the Supervisor (architecture.md §2/§3, FR-2/FR-4/FR-12).

Owns query understanding + hypothesis generation, delegates to the Audio
Analysis Agent (Phase 5) and Retrieval & Evidence Agent (Phase 3) for the two
specialist steps, applies deterministic Selection (Phase 4), and runs
Explanation Generation — assembling the final per-cluster recommendation
batch. This is the "Orchestrator graph" from the roadmap: the flow itself.

Built as a LangGraph `StateGraph` rather than a plain async pipeline function
even though the flow is strictly sequential with no fan-out (architecture.md
§5) — Phase 7's planned SSE streaming (`stream_mode=[...]`) is LangGraph-native
and needs a compiled graph to stream from. Concurrency *within* a stage (e.g.
running retrieval for several hypothesis clusters at once) isn't the dynamic
branching/skipping the "no fan-out" decision rules out — the stage sequence
itself never branches; only independent items within one stage run in
parallel, matching how the Retrieval Agent already fans out to providers
internally.
"""

import asyncio
import logging

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from app.agents.audio import analyze_input_song
from app.agents.explanation import candidate_key, generate_explanations
from app.agents.hypothesis import generate_hypotheses
from app.agents.retrieval import run_retrieval
from app.schemas.audio import AudioAnalysisResult
from app.schemas.hypothesis import HypothesisCluster
from app.schemas.retrieval import Candidate, EvidenceItem
from app.services.selection import filter_input_songs, select_recommendations

logger = logging.getLogger(__name__)


# --- Output shape ---


class RecommendedSong(BaseModel):
    title: str
    artist: str
    sources: list[str]
    evidence: list[EvidenceItem]
    recommendation_strength: float
    variant: str
    explanation: str


class DiscoveryCluster(BaseModel):
    theme: str
    hypothesis: str
    input_songs: list[str]
    recommendations: list[RecommendedSong]


class DiscoveryResult(BaseModel):
    audio_analysis: list[AudioAnalysisResult]
    clusters: list[DiscoveryCluster]


# --- Graph state ---


class DiscoveryState(BaseModel):
    songs: list[str]
    include_live: bool = False
    include_covers: bool = False
    target_count: int = 10
    audio_results: list[AudioAnalysisResult] = []
    hypothesis_clusters: list[HypothesisCluster] = []
    # Reassigned in place across stages: raw candidates per cluster after
    # retrieval, then trimmed to the final selected batch after selection.
    cluster_candidates: list[list[Candidate]] = []
    result: DiscoveryResult | None = None


# --- Nodes ---


async def _audio_node(state: DiscoveryState) -> dict:
    results = await asyncio.gather(*(analyze_input_song(song) for song in state.songs))
    return {"audio_results": list(results)}


async def _hypothesis_node(state: DiscoveryState) -> dict:
    hypotheses = await generate_hypotheses(state.songs, state.audio_results)
    return {"hypothesis_clusters": hypotheses.clusters}


async def _retrieval_node(state: DiscoveryState) -> dict:
    results = await asyncio.gather(
        *(run_retrieval(cluster.hypothesis) for cluster in state.hypothesis_clusters)
    )
    return {"cluster_candidates": [r.candidates for r in results]}


async def _selection_node(state: DiscoveryState) -> dict:
    selected = [
        select_recommendations(
            filter_input_songs(candidates, cluster.songs),
            include_live=state.include_live,
            include_covers=state.include_covers,
            target_count=state.target_count,
        )
        for cluster, candidates in zip(
            state.hypothesis_clusters, state.cluster_candidates, strict=True
        )
    ]
    return {"cluster_candidates": selected}


async def _explanation_node(state: DiscoveryState) -> dict:
    explanation_maps = await asyncio.gather(
        *(
            generate_explanations(cluster.hypothesis, candidates)
            for cluster, candidates in zip(
                state.hypothesis_clusters, state.cluster_candidates, strict=True
            )
        )
    )

    clusters = [
        DiscoveryCluster(
            theme=cluster.theme,
            hypothesis=cluster.hypothesis,
            input_songs=cluster.songs,
            recommendations=[
                RecommendedSong(
                    title=c.title,
                    artist=c.artist,
                    sources=c.sources,
                    evidence=c.evidence,
                    recommendation_strength=c.recommendation_strength,
                    variant=c.variant,
                    explanation=explanations.get(candidate_key(c.title, c.artist), c.rationale),
                )
                for c in candidates
            ],
        )
        for cluster, candidates, explanations in zip(
            state.hypothesis_clusters, state.cluster_candidates, explanation_maps, strict=True
        )
    ]
    return {"result": DiscoveryResult(audio_analysis=state.audio_results, clusters=clusters)}


def _build_graph():
    graph = StateGraph(DiscoveryState)
    graph.add_node("audio", _audio_node)
    graph.add_node("hypothesis", _hypothesis_node)
    graph.add_node("retrieval", _retrieval_node)
    graph.add_node("selection", _selection_node)
    graph.add_node("explanation", _explanation_node)
    graph.add_edge(START, "audio")
    graph.add_edge("audio", "hypothesis")
    graph.add_edge("hypothesis", "retrieval")
    graph.add_edge("retrieval", "selection")
    graph.add_edge("selection", "explanation")
    graph.add_edge("explanation", END)
    return graph.compile()


_graph = _build_graph()


async def run_discovery(
    songs: list[str],
    *,
    include_live: bool = False,
    include_covers: bool = False,
    target_count: int = 10,
) -> DiscoveryResult:
    """Run the full song-based discovery flow (architecture.md §6): audio
    analysis -> hypothesis generation -> retrieval -> selection ->
    explanation. `songs` is 1-5 free-text input-song queries (FR-1.2)."""
    final_state = await _graph.ainvoke(
        DiscoveryState(
            songs=songs,
            include_live=include_live,
            include_covers=include_covers,
            target_count=target_count,
        )
    )
    return final_state["result"]
