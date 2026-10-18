"""Dev-only helper: mint a fresh JWT for a given email without clicking a real
magic link. Requires the API server running locally and reachable at
API_BASE_URL, and Redis reachable at settings.redis_url (docker-compose).

Usage (from backend/):
    uv run python scripts/get_dev_token.py you@example.com

Prints the raw access_token JSON, same shape as POST /api/auth/verify.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from redis.asyncio import Redis

from app.config import settings
from app.services.auth import MAGIC_LINK_KEY_PREFIX

API_BASE_URL = "http://localhost:8000"


async def get_dev_token(email: str) -> dict:
    async with httpx.AsyncClient(base_url=API_BASE_URL) as client:
        resp = await client.post("/api/auth/request-link", json={"email": email})
        resp.raise_for_status()

        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            token = None
            async for key in redis.scan_iter(f"{MAGIC_LINK_KEY_PREFIX}*"):
                if await redis.get(key) == email:
                    token = key.removeprefix(MAGIC_LINK_KEY_PREFIX)
                    break
        finally:
            await redis.aclose()

        if token is None:
            raise RuntimeError(
                f"No pending magic-link token found for {email} — is the server "
                "actually running and pointed at this Redis instance?"
            )

        verify_resp = await client.post("/api/auth/verify", json={"token": token})
        verify_resp.raise_for_status()
        return verify_resp.json()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: uv run python scripts/get_dev_token.py <email>", file=sys.stderr)
        sys.exit(1)

    result = asyncio.run(get_dev_token(sys.argv[1]))
    print(result)
