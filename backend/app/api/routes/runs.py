"""Run history and export (FR-15, FR-16): list a tester's past batches, fetch
one, and download it as CSV or JSON."""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_identity, get_db
from app.models.identity import Identity
from app.schemas.feedback import RunSummary
from app.services.export import to_csv, to_json
from app.services.interaction_log import log_event
from app.services.runs import get_run_result, list_runs

router = APIRouter()


@router.get("/runs", response_model=list[RunSummary])
async def runs(
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> list[RunSummary]:
    return await list_runs(db, identity.id)


async def _result_or_404(db: AsyncSession, identity: Identity, run_id: uuid.UUID) -> dict[str, Any]:
    result = await get_run_result(db, identity.id, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return {**await _result_or_404(db, identity, run_id), "run_id": str(run_id)}


@router.get("/runs/{run_id}/export")
async def export_run(
    run_id: uuid.UUID,
    format: Literal["csv", "json"] = Query(default="csv"),
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await _result_or_404(db, identity, run_id)
    await log_event(identity.id, run_id, "export", {"format": format})
    body, media_type = (
        (to_csv(result), "text/csv") if format == "csv" else (to_json(result), "application/json")
    )
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="orchestra-{run_id}.{format}"'},
    )
