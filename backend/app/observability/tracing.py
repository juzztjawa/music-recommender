"""MLflow tracing setup (Phase 7b).

`mlflow.langchain.autolog()` hooks LangChain/LangGraph's callback system, so
the whole graph — every node, the Retrieval agent's tool loop, each LLM call
with prompt, output and token usage — shows up as one trace in the MLflow UI
with no changes to the agents. Disabled when MLFLOW_TRACKING_URI is empty.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import mlflow

from app.config import settings
from app.observability.context import TraceContext

logger = logging.getLogger(__name__)

_enabled = False


def setup_tracing() -> None:
    global _enabled
    if not settings.mlflow_tracking_uri:
        logger.info("MLflow tracing disabled (MLFLOW_TRACKING_URI unset)")
        return
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_experiment(settings.mlflow_experiment_name)
    mlflow.langchain.autolog()
    _enabled = True
    logger.info("MLflow tracing -> %s", settings.mlflow_tracking_uri)


@contextmanager
def root_span(ctx: TraceContext | None, message: str) -> Iterator[None]:
    """One MLflow trace per discovery run, tagged by login session and user,
    and findable by `run_id` (the key that joins it to `interaction_events`).

    The autolog'd LangGraph spans nest under this span. It must be entered and
    exited in a single task, so it can't wrap a generator that yields.
    """
    if not _enabled:
        yield
        return
    with mlflow.start_span(name="discovery", span_type="CHAIN") as span:
        span.set_inputs({"message": message})
        if ctx is not None:
            try:
                mlflow.update_current_trace(
                    session_id=str(ctx.session_id) if ctx.session_id else None,
                    user=str(ctx.identity_id),
                    tags={"run_id": str(ctx.run_id), "message": message[:250]},
                )
            except Exception:
                logger.exception("Failed to tag MLflow trace")
        yield
