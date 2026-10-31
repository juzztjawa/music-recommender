"""Chat threads, stored in the FR-19 `interaction_events` log (no new table).

A thread is a set of runs sharing `payload["thread_id"]` on their `query`
event. Runs from before chat existed have no thread id; each is treated as a
one-turn thread whose id is its run id, so old history still opens.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import Feedback
from app.models.interaction_event import InteractionEvent
from app.schemas.chat import Thread, ThreadSummary, Turn

MAX_CONTEXT_TURNS = 6
DETAILED_TURNS = 2  # most recent turns get explanations in the intent context


@dataclass
class ThreadTurn:
    run_id: uuid.UUID
    message: str
    songs: list[str] = field(default_factory=list)
    guidance: str | None = None
    assistant_text: str | None = None
    # (title, artist, explanation)
    recommended: list[tuple[str, str, str]] = field(default_factory=list)


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("data", payload) if payload.get("type") == "result" else payload


def _in_thread(thread_id: uuid.UUID):
    tid = InteractionEvent.payload["thread_id"].astext
    return or_(tid == str(thread_id), and_(tid.is_(None), InteractionEvent.run_id == thread_id))


async def _events_by_run(
    db: AsyncSession, identity_id: uuid.UUID, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, dict[str, Any]]]:
    if not run_ids:
        return {}
    rows = await db.execute(
        select(InteractionEvent.run_id, InteractionEvent.event_type, InteractionEvent.payload)
        .where(
            InteractionEvent.identity_id == identity_id,
            InteractionEvent.run_id.in_(run_ids),
            InteractionEvent.event_type.in_(["recommendation", "assistant_message", "error"]),
        )
        .order_by(InteractionEvent.created_at)
    )
    out: dict[uuid.UUID, dict[str, dict[str, Any]]] = {}
    for run_id, event_type, payload in rows.all():
        out.setdefault(run_id, {})[event_type] = payload
    return out


async def _thread_queries(db: AsyncSession, identity_id: uuid.UUID, thread_id: uuid.UUID):
    rows = await db.execute(
        select(InteractionEvent.run_id, InteractionEvent.created_at, InteractionEvent.payload)
        .where(
            InteractionEvent.identity_id == identity_id,
            InteractionEvent.event_type == "query",
            _in_thread(thread_id),
        )
        .order_by(InteractionEvent.created_at)
    )
    return rows.all()


def _message_of(payload: dict[str, Any]) -> str:
    return payload.get("message") or " + ".join(payload.get("songs", [])) or "(empty)"


async def load_history(
    db: AsyncSession, identity_id: uuid.UUID, thread_id: uuid.UUID
) -> list[ThreadTurn]:
    queries = (await _thread_queries(db, identity_id, thread_id))[-MAX_CONTEXT_TURNS:]
    events = await _events_by_run(db, identity_id, [q.run_id for q in queries])
    turns = []
    for q in queries:
        ev = events.get(q.run_id, {})
        result = _unwrap(ev["recommendation"]) if "recommendation" in ev else None
        recommended = [
            (r["title"], r["artist"], r.get("explanation", ""))
            for c in (result or {}).get("clusters", [])
            for r in c.get("recommendations", [])
        ]
        turns.append(
            ThreadTurn(
                run_id=q.run_id,
                message=_message_of(q.payload),
                songs=q.payload.get("songs", []),
                guidance=q.payload.get("guidance"),
                assistant_text=ev.get("assistant_message", {}).get("text"),
                recommended=recommended,
            )
        )
    return turns


def render_context(history: list[ThreadTurn]) -> str:
    """Compact text the intent LLM reads. Recent turns include explanations
    (so it can answer questions about them); older ones just titles."""
    lines: list[str] = []
    for i, t in enumerate(history):
        detailed = i >= len(history) - DETAILED_TURNS
        lines.append(f"User: {t.message}")
        if t.songs:
            lines.append(f"  (searched reference songs: {'; '.join(t.songs)})")
        if t.guidance:
            lines.append(f"  (steering applied: {t.guidance})")
        if t.assistant_text:
            lines.append(f"Assistant: {t.assistant_text}")
        for title, artist, why in t.recommended:
            lines.append(f"  - {title} — {artist}" + (f": {why[:200]}" if detailed and why else ""))
    return "\n".join(lines)


def previously_recommended(history: list[ThreadTurn]) -> list[str]:
    """'title artist' strings for no-repeat filtering."""
    return [f"{title} {artist}" for t in history for title, artist, _ in t.recommended]


async def list_threads(
    db: AsyncSession, identity_id: uuid.UUID, limit: int = 40
) -> list[ThreadSummary]:
    rows = await db.execute(
        select(InteractionEvent.run_id, InteractionEvent.created_at, InteractionEvent.payload)
        .where(InteractionEvent.identity_id == identity_id, InteractionEvent.event_type == "query")
        .order_by(InteractionEvent.created_at.desc())
        .limit(limit * 5)
    )
    threads: dict[uuid.UUID, dict[str, Any]] = {}
    for run_id, created_at, payload in rows.all():  # newest first
        raw = payload.get("thread_id")
        tid = uuid.UUID(raw) if raw else run_id
        t = threads.setdefault(tid, {"updated_at": created_at, "turns": 0, "title": ""})
        t["turns"] += 1
        t["title"] = _message_of(payload)  # last write = oldest message = the opener
    summaries = [
        ThreadSummary(
            thread_id=tid, title=t["title"][:80], updated_at=t["updated_at"], turns=t["turns"]
        )
        for tid, t in threads.items()
    ]
    return summaries[:limit]


async def get_thread(
    db: AsyncSession, identity_id: uuid.UUID, thread_id: uuid.UUID
) -> Thread | None:
    queries = await _thread_queries(db, identity_id, thread_id)
    if not queries:
        return None
    run_ids = [q.run_id for q in queries]
    events = await _events_by_run(db, identity_id, run_ids)
    fb = await db.execute(
        select(Feedback.run_id, Feedback.reaction).where(Feedback.run_id.in_(run_ids))
    )
    reactions = dict(fb.all())
    turns = []
    for q in queries:
        ev = events.get(q.run_id, {})
        result = _unwrap(ev["recommendation"]) if "recommendation" in ev else None
        if result is not None:
            status = "ok"
        elif q.payload.get("songs"):
            status = "failed"
        elif "assistant_message" in ev:
            status = "reply"
        else:
            status = "failed"
        turns.append(
            Turn(
                run_id=q.run_id,
                created_at=q.created_at,
                message=_message_of(q.payload),
                assistant_text=ev.get("assistant_message", {}).get("text"),
                result={**result, "run_id": str(q.run_id)} if result else None,
                status=status,
                reaction=reactions.get(q.run_id),
            )
        )
    return Thread(thread_id=thread_id, turns=turns)


__all__ = [
    "ThreadTurn",
    "get_thread",
    "list_threads",
    "load_history",
    "previously_recommended",
    "render_context",
]
