"""FastAPI application entrypoint.

Wires up lifespan (DB/Redis), CORS, and routers. Phase 1 exposes only the
health endpoint; auth, discovery, feedback, and export routers are mounted
as they are built.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health
from app.config import settings
from app.redis import redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify Redis is reachable (DB connectivity is checked lazily
    # per-request via the health endpoint; migrations run separately via Alembic).
    try:
        await redis_client.ping()
    except Exception:  # noqa: BLE001 - surface as a warning, don't crash boot
        print("WARNING: Redis not reachable at startup")
    yield
    # Shutdown: close Redis connection.
    await redis_client.aclose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
