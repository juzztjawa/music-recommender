"""Tests for the supervisor agent (app.agents.orchestrator + app.tools.orchestrator).

The model is a scripted fake that emits tool calls in a fixed order, so these
tests exercise the real agent loop, the real tools, the run state and the
result assembly. The delegated specialists (audio, retrieval, explanation) are
mocked: this checks orchestration, not LLM or network behaviour.
"""

import uuid

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.agents import orchestrator
from app.schemas.audio import AudioAnalysisResult
from app.schemas.retrieval import Candidate, EvidenceItem, RetrievalResult
from app.services.threads import ThreadTurn
from app.tools import orchestrator as tools


class ScriptedModel(FakeMessagesListChatModel):
    """Plays back AIMessages in order; accepts (and ignores) bind_tools."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name: str, call_id: str, **args) -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def turn(*calls: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=list(calls))


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


@pytest.fixture
def specialists(monkeypatch):
    """Mock audio / retrieval / explanation; record what they were asked."""
    seen = {"retrieval": [], "audio": []}

    async def fake_analyze(query):
        seen["audio"].append(query)
        return AudioAnalysisResult(query=query, caption=f"caption for {query}")

    async def fake_retrieval(hypothesis):
        seen["retrieval"].append(hypothesis)
        return RetrievalResult(
            candidates=[
                make_candidate("Song A", "Artist A"),
                make_candidate("Song B", "Artist B"),
                make_candidate("Song X", "Artist X"),  # the input song itself
            ],
            providers_queried=["musicbrainz"],
        )

    async def fake_explanations(hypothesis, candidates):
        return {"song a::artist a": "shares a driving guitar riff"}

    monkeypatch.setattr(tools, "analyze_input_song", fake_analyze)
    monkeypatch.setattr(tools, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(tools, "generate_explanations", fake_explanations)
    return seen


def script(monkeypatch, *messages: AIMessage) -> None:
    model = ScriptedModel(responses=list(messages))
    monkeypatch.setattr(orchestrator, "get_primary_model", lambda: model)
    monkeypatch.setattr(orchestrator, "get_fallback_model", lambda: model)


FULL_FLOW = [
    turn(call("analyze_audio", "1", song="Song X Artist X")),
    turn(
        call(
            "retrieve_candidates",
            "2",
            theme="rock",
            hypothesis="upbeat rock",
            input_songs=["Song X Artist X"],
        )
    ),
    turn(call("select_and_diversify", "3", cluster_id="c1")),
    turn(call("write_explanations", "4", cluster_id="c1")),
    AIMessage(content="I found some upbeat rock for you."),
]


async def test_full_flow_assembles_result_from_tool_state(monkeypatch, specialists):
    script(monkeypatch, *FULL_FLOW)

    result = await orchestrator.run_discovery("songs like Song X by Artist X")

    assert result.reply == "I found some upbeat rock for you."
    assert specialists["audio"] == ["Song X Artist X"]
    assert specialists["retrieval"] == ["upbeat rock"]
    assert len(result.audio_analysis) == 1
    cluster = result.clusters[0]
    assert (cluster.theme, cluster.hypothesis) == ("rock", "upbeat rock")
    titles = {r.title: r.explanation for r in cluster.recommendations}
    # The input song is filtered out by the deterministic selection step.
    assert set(titles) == {"Song A", "Song B"}
    assert titles["Song A"] == "shares a driving guitar riff"
    # Not in the mocked explanation map -> falls back to the candidate's rationale.
    assert titles["Song B"] == "fallback rationale"


async def test_stream_emits_tool_events_then_message_and_result(monkeypatch, specialists):
    script(monkeypatch, *FULL_FLOW)

    events = [e async for e in orchestrator.stream_discovery("songs like Song X")]

    tool_events = [(e["name"], e["status"]) for e in events if e["type"] == "tool"]
    assert tool_events == [
        ("analyze_audio", "started"), ("analyze_audio", "done"),
        ("retrieve_candidates", "started"), ("retrieve_candidates", "done"),
        ("select_and_diversify", "started"), ("select_and_diversify", "done"),
        ("write_explanations", "started"), ("write_explanations", "done"),
    ]  # fmt: skip
    started = next(e for e in events if e["type"] == "tool" and e["status"] == "started")
    assert started["args"] == {"song": "Song X Artist X"}
    assert [e["type"] for e in events[-2:]] == ["message", "result"]
    assert events[-1]["data"]["clusters"][0]["recommendations"][0]["title"] == "Song A"


async def test_description_only_request_skips_audio(monkeypatch, specialists):
    script(
        monkeypatch,
        turn(
            call(
                "retrieve_candidates",
                "1",
                theme="calm orchestral",
                hypothesis="peaceful orchestral music",
                input_songs=[],
            )
        ),
        turn(call("select_and_diversify", "2", cluster_id="c1")),
        turn(call("write_explanations", "3", cluster_id="c1")),
        AIMessage(content="Here is some calm orchestral music."),
    )

    result = await orchestrator.run_discovery("peaceful orchestral music")

    assert specialists["audio"] == []
    assert result.audio_analysis == []
    # No input songs -> nothing to filter out, so all three candidates survive.
    assert len(result.clusters[0].recommendations) == 3


async def test_divergent_songs_become_separate_clusters(monkeypatch, specialists):
    script(
        monkeypatch,
        turn(
            call("retrieve_candidates", "1", theme="classical", hypothesis="calm", input_songs=[]),
            call("retrieve_candidates", "2", theme="metal", hypothesis="heavy", input_songs=[]),
        ),
        turn(
            call("select_and_diversify", "3", cluster_id="c1"),
            call("select_and_diversify", "4", cluster_id="c2"),
        ),
        AIMessage(content="Two themes."),
    )

    result = await orchestrator.run_discovery("a calm piece and a heavy one")

    assert {c.theme for c in result.clusters} == {"classical", "metal"}
    assert sorted(specialists["retrieval"]) == ["calm", "heavy"]


async def test_tool_error_is_reported_to_the_agent_not_raised(monkeypatch, specialists):
    script(
        monkeypatch,
        # select before any retrieval: the tool must refuse, the run must carry on.
        turn(call("select_and_diversify", "1", cluster_id="c9")),
        AIMessage(content="Sorry, I couldn't find anything."),
    )

    events = [e async for e in orchestrator.stream_discovery("x")]

    done = next(e for e in events if e["type"] == "tool" and e["status"] != "started")
    assert done["status"] == "error"
    assert "Unknown cluster_id" in done["summary"]
    result = events[-1]["data"]
    assert result["clusters"] == []
    assert result["reply"] == "Sorry, I couldn't find anything."


async def test_songs_from_earlier_turns_are_not_repeated(monkeypatch, specialists):
    script(monkeypatch, *FULL_FLOW[1:])
    history = [
        ThreadTurn(
            run_id=uuid.uuid4(),
            message="earlier",
            recommended=[("Song A", "Artist A", "why")],
        )
    ]

    result = await orchestrator.run_discovery("something else", history=history)

    # Song A was recommended earlier; Song X is the input song, dropped by selection.
    assert {r.title for r in result.clusters[0].recommendations} == {"Song B"}


async def test_ruled_out_artists_are_excluded(monkeypatch, specialists):
    script(
        monkeypatch,
        FULL_FLOW[1],
        turn(call("select_and_diversify", "3", cluster_id="c1", exclude_artists=["Artist A"])),
        AIMessage(content="Different artist this time."),
    )

    result = await orchestrator.run_discovery("a different artist please")

    assert {r.title for r in result.clusters[0].recommendations} == {"Song B"}


async def test_session_history_tool_returns_the_conversation(monkeypatch, specialists):
    script(
        monkeypatch,
        turn(call("get_session_history", "1")),
        AIMessage(content="You asked for rock earlier."),
    )
    history = [
        ThreadTurn(
            run_id=uuid.uuid4(),
            message="upbeat rock",
            assistant_text="Here is some rock.",
            recommended=[("Song A", "Artist A", "driving riff")],
        )
    ]

    events = [e async for e in orchestrator.stream_discovery("why Song A?", history=history)]

    done = next(e for e in events if e["type"] == "tool" and e["status"] == "done")
    assert "upbeat rock" in done["summary"]
    assert events[-1]["data"]["clusters"] == []
    assert events[-1]["data"]["reply"] == "You asked for rock earlier."


async def test_empty_final_reply_gets_an_honest_fallback(monkeypatch, specialists):
    script(monkeypatch, AIMessage(content=""))

    result = await orchestrator.run_discovery("???")

    assert result.clusters == []
    assert "another song" in result.reply


async def test_model_failure_before_output_retries_on_fallback(monkeypatch, specialists):
    class Broken(ScriptedModel):
        def _generate(self, *a, **k):
            raise RuntimeError("model retired")

    good = ScriptedModel(responses=[AIMessage(content="ok")])
    monkeypatch.setattr(orchestrator, "get_primary_model", lambda: Broken(responses=[]))
    monkeypatch.setattr(orchestrator, "get_fallback_model", lambda: good)

    result = await orchestrator.run_discovery("hi")

    assert result.reply == "ok"


async def test_explanations_fall_back_when_model_returns_no_structured_output(monkeypatch):
    """run_structured yields None when the model chats instead of calling the function."""
    from app.agents import explanation

    async def none_result(messages, schema):
        return None

    monkeypatch.setattr(explanation, "run_structured", none_result)

    assert await explanation.generate_explanations("h", [make_candidate("A", "B")]) == {}
