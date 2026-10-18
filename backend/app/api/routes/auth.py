"""Magic-link auth endpoints (FR-18): no password, email-verified access."""

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import enforce_request_link_rate_limit, get_current_identity, get_db, get_redis
from app.clients.email import send_magic_link_email
from app.config import settings
from app.models.identity import Identity
from app.schemas.auth import RequestLinkRequest, TokenResponse, VerifyRequest
from app.services.auth import (
    consume_magic_link_token,
    create_access_token,
    create_session,
    generate_magic_link_token,
    get_or_create_identity,
    store_magic_link_token,
)

router = APIRouter()


@router.post(
    "/auth/request-link",
    status_code=200,
    dependencies=[Depends(enforce_request_link_rate_limit)],
)
async def request_link(
    body: RequestLinkRequest,
    redis: Redis = Depends(get_redis),
) -> dict:
    token = generate_magic_link_token()
    await store_magic_link_token(redis, token, body.email)

    magic_link_url = f"{settings.frontend_base_url}/verify?token={token}"
    await send_magic_link_email(body.email, magic_link_url)

    # Always 200, regardless of anything about the email — avoids enumeration.
    return {"message": "If that email is valid, a magic link has been sent."}


@router.post("/auth/verify", response_model=TokenResponse)
async def verify(
    body: VerifyRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> TokenResponse:
    email = await consume_magic_link_token(redis, body.token)
    if email is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    identity = await get_or_create_identity(db, email)
    await create_session(db, identity.id)
    access_token = create_access_token(identity.id)

    return TokenResponse(access_token=access_token)


@router.get("/auth/me")
async def me(identity: Identity = Depends(get_current_identity)) -> dict:
    return {"id": str(identity.id), "email": identity.email}
