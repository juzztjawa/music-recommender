"""Chat models: request, the LLM's parsed intent, and stored thread shapes."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    thread_id: uuid.UUID | None = Field(
        default=None, description="Omit to start a new thread; pass it to continue one"
    )
    # Explicit option overrides from the UI; None lets the intent step decide.
    include_live: bool | None = None
    include_covers: bool | None = None
    target_count: int | None = Field(default=None, ge=1, le=25)


class ThreadSummary(BaseModel):
    thread_id: uuid.UUID
    title: str
    updated_at: datetime
    turns: int


class Turn(BaseModel):
    run_id: uuid.UUID
    created_at: datetime
    message: str
    assistant_text: str | None = None
    # A stored DiscoveryResult, or None for text-only replies and failed runs.
    result: dict[str, Any] | None = None
    status: Literal["ok", "reply", "failed"]
    reaction: str | None = None


class Thread(BaseModel):
    thread_id: uuid.UUID
    turns: list[Turn]
