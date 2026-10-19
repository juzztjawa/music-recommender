"""FR-19 interaction logging.

Events are written as they happen (architecture.md §6 step 8), each in its own
short transaction, so a run that dies mid-flow still leaves a usable trace.
Logging must never break the request it observes: failures are logged and
swallowed.
"""

import logging
import uuid
from typing import Any

from app.db import async_session_factory
from app.models.interaction_event import InteractionEvent

logger = logging.getLogger(__name__)


async def log_event(
    identity_id: uuid.UUID, run_id: uuid.UUID, event_type: str, payload: dict[str, Any]
) -> None:
    try:
        async with async_session_factory() as db:
            db.add(
                InteractionEvent(
                    identity_id=identity_id,
                    run_id=run_id,
                    event_type=event_type,
                    payload=payload,
                )
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to write interaction event %s", event_type)
