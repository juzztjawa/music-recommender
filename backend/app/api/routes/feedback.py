"""Batch feedback (FR-13). Stored and logged only — it does not change
recommendations (FR-13.2 / FR-14: no cross-session personalization)."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_identity, get_db
from app.models.feedback import Feedback
from app.models.identity import Identity
from app.schemas.feedback import FeedbackRequest, FeedbackResponse
from app.services.interaction_log import log_event
from app.services.runs import get_run_result

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackRequest,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    if await get_run_result(db, identity.id, body.run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    existing = (
        await db.execute(select(Feedback).where(Feedback.run_id == body.run_id))
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            Feedback(
                identity_id=identity.id,
                run_id=body.run_id,
                reaction=body.reaction,
                comment=body.comment,
            )
        )
    else:
        existing.reaction = body.reaction
        existing.comment = body.comment
    await db.commit()

    await log_event(identity.id, body.run_id, "feedback", body.model_dump(mode="json"))
    return FeedbackResponse(run_id=body.run_id, reaction=body.reaction, comment=body.comment)
