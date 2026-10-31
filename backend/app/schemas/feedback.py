"""Feedback and run-history models (FR-13, FR-15, FR-16)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Reaction = Literal["loved_it", "pretty_good", "mixed", "missed"]


class FeedbackRequest(BaseModel):
    run_id: uuid.UUID
    reaction: Reaction
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    run_id: uuid.UUID
    reaction: Reaction
    comment: str | None = None


class RunSummary(BaseModel):
    run_id: uuid.UUID
    created_at: datetime
    title: str
    thread_id: uuid.UUID | None = None
    reaction: Reaction | None = None
