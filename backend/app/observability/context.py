"""Who/what a run belongs to, shared by the DB recorder and MLflow tagging."""

import uuid
from contextvars import ContextVar

from pydantic import BaseModel

# Set by each orchestrator node so a tool/LLM call can say which stage made it
# (LangChain callbacks know their parent run, not our stage names). Context
# variables are copied into asyncio tasks, so this holds inside gather().
current_stage: ContextVar[str | None] = ContextVar("current_stage", default=None)


class TraceContext(BaseModel):
    identity_id: uuid.UUID
    run_id: uuid.UUID
    session_id: uuid.UUID | None = None
