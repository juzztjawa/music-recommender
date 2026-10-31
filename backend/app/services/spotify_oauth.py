"""Spotify Authorization Code flow for playlist export (FR-16).

Separate from `app/clients/spotify.py`, which uses app-only Client
Credentials for catalog search. Here the user logs in on Spotify and we hold
their tokens: encrypted at rest in `identities.spotify_oauth_token`, refreshed
when close to expiry.

The `state` parameter is a one-time random value kept in Redis (10 min) that
maps the callback back to the identity — the callback is a plain browser
redirect, so it has no JWT to prove who is calling.
"""

import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.identity import Identity

logger = logging.getLogger(__name__)

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = "playlist-modify-private playlist-modify-public"
STATE_PREFIX = "spotify_oauth_state:"
STATE_TTL_SECONDS = 600
# Refresh a little early so a token never expires mid-export.
EXPIRY_MARGIN_SECONDS = 60


class SpotifyNotConfigured(RuntimeError):
    pass


class SpotifyAuthError(RuntimeError):
    """Token exchange/refresh was rejected, or the user must reconnect."""


def _fernet() -> Fernet:
    # Derived from the JWT secret so there is one secret to manage. Changing
    # JWT_SECRET therefore makes stored Spotify tokens unreadable (the user
    # just reconnects).
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.jwt_secret.encode()).digest())
    return Fernet(key)


def encrypt_tokens(tokens: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(tokens).encode()).decode()


def decrypt_tokens(blob: str) -> dict[str, Any] | None:
    try:
        return json.loads(_fernet().decrypt(blob.encode()))
    except (InvalidToken, ValueError):
        return None


def _require_configured() -> tuple[str, str]:
    if not (settings.spotify_client_id and settings.spotify_client_secret):
        raise SpotifyNotConfigured("SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET are not set")
    return settings.spotify_client_id, settings.spotify_client_secret


async def create_authorize_url(
    redis: Redis, identity_id: uuid.UUID, return_run_id: uuid.UUID | None = None
) -> str:
    client_id, _ = _require_configured()
    state = secrets.token_urlsafe(32)
    await redis.set(
        f"{STATE_PREFIX}{state}",
        json.dumps(
            {
                "identity_id": str(identity_id),
                "run_id": str(return_run_id) if return_run_id else None,
            }
        ),
        ex=STATE_TTL_SECONDS,
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "scope": SCOPES,
            "redirect_uri": settings.spotify_redirect_uri,
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def consume_state(redis: Redis, state: str) -> dict[str, Any] | None:
    """Single-use: read and delete."""
    raw = await redis.getdel(f"{STATE_PREFIX}{state}")
    return json.loads(raw) if raw else None


async def _token_request(
    data: dict[str, str], client: httpx.AsyncClient | None = None
) -> dict[str, Any]:
    client_id, client_secret = _require_configured()
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(TOKEN_URL, data=data, auth=(client_id, client_secret))
    finally:
        if owns_client:
            await client.aclose()
    if resp.status_code != 200:
        logger.warning("Spotify token endpoint %s: %s", resp.status_code, resp.text[:200])
        raise SpotifyAuthError(f"Spotify token endpoint returned {resp.status_code}")
    return resp.json()


def _to_stored(payload: dict[str, Any], previous_refresh: str | None = None) -> dict[str, Any]:
    return {
        "access_token": payload["access_token"],
        # A refresh response may omit a new refresh token: keep the old one.
        "refresh_token": payload.get("refresh_token") or previous_refresh,
        "expires_at": time.time() + int(payload.get("expires_in", 3600)),
        "scope": payload.get("scope", ""),
    }


async def exchange_code(code: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    payload = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
        },
        client,
    )
    return _to_stored(payload)


async def save_tokens(db: AsyncSession, identity: Identity, tokens: dict[str, Any] | None) -> None:
    identity.spotify_oauth_token = encrypt_tokens(tokens) if tokens else None
    db.add(identity)
    await db.commit()


def is_connected(identity: Identity) -> bool:
    return bool(
        identity.spotify_oauth_token and decrypt_tokens(identity.spotify_oauth_token) is not None
    )


async def get_access_token(
    db: AsyncSession, identity: Identity, client: httpx.AsyncClient | None = None
) -> str:
    """A valid access token for the identity, refreshing it if needed.

    Raises SpotifyAuthError when the user has not connected or the grant was
    revoked — in the latter case the stored tokens are cleared so the UI shows
    "connect" again instead of failing forever.
    """
    tokens = decrypt_tokens(identity.spotify_oauth_token) if identity.spotify_oauth_token else None
    if tokens is None:
        raise SpotifyAuthError("Spotify is not connected")

    if tokens["expires_at"] - time.time() > EXPIRY_MARGIN_SECONDS:
        return tokens["access_token"]

    if not tokens.get("refresh_token"):
        await save_tokens(db, identity, None)
        raise SpotifyAuthError("Spotify session expired; reconnect")
    try:
        payload = await _token_request(
            {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, client
        )
    except SpotifyAuthError:
        logger.warning("Spotify refresh rejected; clearing stored tokens")
        await save_tokens(db, identity, None)
        raise
    refreshed = _to_stored(payload, previous_refresh=tokens["refresh_token"])
    await save_tokens(db, identity, refreshed)
    return refreshed["access_token"]
