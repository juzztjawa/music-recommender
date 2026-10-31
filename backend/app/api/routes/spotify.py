"""Spotify connection (OAuth) and playlist export (FR-16)."""

import logging
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_identity, get_db, get_redis
from app.config import settings
from app.models.identity import Identity
from app.services.interaction_log import log_event
from app.services.runs import get_run_result
from app.services.spotify_export import ExportOutcome, export_to_spotify
from app.services.spotify_oauth import (
    SpotifyAuthError,
    SpotifyNotConfigured,
    consume_state,
    create_authorize_url,
    exchange_code,
    get_access_token,
    is_connected,
    save_tokens,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ExportRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)


def _frontend(run_id: str | None, outcome: str) -> RedirectResponse:
    path = f"/runs/{run_id}" if run_id else "/"
    return RedirectResponse(f"{settings.frontend_base_url}{path}?{urlencode({'spotify': outcome})}")


@router.get("/spotify/status")
async def status(identity: Identity = Depends(get_current_identity)) -> dict:
    return {"connected": is_connected(identity)}


@router.get("/spotify/connect")
async def connect(
    run_id: uuid.UUID | None = None,
    identity: Identity = Depends(get_current_identity),
    redis: Redis = Depends(get_redis),
) -> dict:
    """Returns the Spotify consent URL; the SPA navigates to it. (A plain
    browser redirect could not carry the Authorization header.)"""
    try:
        return {"url": await create_authorize_url(redis, identity.id, run_id)}
    except SpotifyNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/spotify/callback")
async def callback(
    state: str = "",
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    """Spotify redirects the browser here. No JWT: identity comes from `state`."""
    ctx = await consume_state(redis, state) if state else None
    if ctx is None:
        return _frontend(None, "error")
    run_id = ctx.get("run_id")
    if error or not code:
        return _frontend(run_id, "denied")

    identity = (
        await db.execute(select(Identity).where(Identity.id == uuid.UUID(ctx["identity_id"])))
    ).scalar_one_or_none()
    if identity is None:
        return _frontend(run_id, "error")
    try:
        await save_tokens(db, identity, await exchange_code(code))
    except (SpotifyAuthError, httpx.HTTPError):
        logger.exception("Spotify code exchange failed")
        return _frontend(run_id, "error")
    return _frontend(run_id, "connected")


@router.delete("/spotify/connection", status_code=204)
async def disconnect(
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> None:
    await save_tokens(db, identity, None)


@router.post("/runs/{run_id}/export/spotify", response_model=ExportOutcome)
async def export_spotify(
    run_id: uuid.UUID,
    body: ExportRequest | None = None,
    identity: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
) -> ExportOutcome:
    result = await get_run_result(db, identity.id, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        token = await get_access_token(db, identity)
        outcome = await export_to_spotify(token, result, body.name if body else None)
    except SpotifyAuthError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except SpotifyNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except httpx.HTTPError as e:
        logger.exception("Spotify export failed")
        raise HTTPException(status_code=502, detail="Spotify request failed") from e

    await log_event(
        identity.id,
        run_id,
        "export",
        {"format": "spotify", "added": outcome.added, "not_found": len(outcome.not_found)},
    )
    return outcome
