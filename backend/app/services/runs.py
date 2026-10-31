"""Read side of the FR-19 log: finding a user's past discovery runs.

The durable record of a run is its `recommendation` event in
`interaction_events`. Every lookup is scoped to the caller's identity, so one
tester can never read or export another's batch.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import Feedback
from app.models.interaction_event import InteractionEvent
from app.schemas.feedback import RunSummary


async def get_run_result(
    db: AsyncSession, identity_id: uuid.UUID, run_id: uuid.UUID
) -> dict[str, Any] | None:
    row = await db.execute(
        select(InteractionEvent.payload).where(
            InteractionEvent.identity_id == identity_id,
            InteractionEvent.run_id == run_id,
            InteractionEvent.event_type == "recommendation",
        )
    )
    payload = row.scalar_one_or_none()
    if payload is None:
        return None
    # Streamed runs used to log the whole SSE envelope; unwrap those.
    return payload.get("data", payload) if payload.get("type") == "result" else payload


def _title(query_payload: dict[str, Any]) -> str:
    """What the user asked, for the history list. Older runs stored `songs`."""
    text = query_payload.get("message") or " + ".join(query_payload.get("songs", []))
    return text if len(text) <= 80 else text[:79] + "…"


async def list_runs(db: AsyncSession, identity_id: uuid.UUID, limit: int = 20) -> list[RunSummary]:
    queries = await db.execute(
        select(InteractionEvent.run_id, InteractionEvent.created_at, InteractionEvent.payload)
        .where(
            InteractionEvent.identity_id == identity_id,
            InteractionEvent.event_type == "query",
        )
        .order_by(InteractionEvent.created_at.desc())
        .limit(limit)
    )
    rows = queries.all()
    reactions = {}
    if rows:
        fb = await db.execute(
            select(Feedback.run_id, Feedback.reaction).where(
                Feedback.run_id.in_([r.run_id for r in rows])
            )
        )
        reactions = {run_id: reaction for run_id, reaction in fb.all()}
    return [
        RunSummary(
            run_id=r.run_id,
            created_at=r.created_at,
            title=_title(r.payload),
            thread_id=r.payload.get("thread_id"),
            reaction=reactions.get(r.run_id),
        )
        for r in rows
    ]
