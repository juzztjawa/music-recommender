"""Application configuration via pydantic-settings.

All values are read from environment variables (or a `.env` file in the
backend directory). Never hardcode secrets here.
"""

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    app_name: str = "Project Orchestra"
    environment: str = "development"  # development | production
    debug: bool = True

    # --- Database (PostgreSQL) ---
    database_url: str = Field(
        default="postgresql+asyncpg://orchestra:orchestra@localhost:5433/orchestra",
        description=(
            "Async SQLAlchemy URL for PostgreSQL "
            "(host port 5433 avoids clashing with a local Postgres on 5432)"
        ),
    )

    # --- Redis ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (session state + rate limiting)",
    )

    # --- LLM (Ollama Cloud) ---
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama endpoint. Set to your Ollama Cloud base URL to use :cloud models.",
    )
    ollama_api_key: str = Field(
        default="",
        description="Ollama Cloud API key (empty for local Ollama)",
    )
    ollama_primary_model: str = "deepseek-v4-flash:0731-cloud"
    ollama_fallback_model: str = "deepseek-v4-flash:0731-cloud"
    ollama_request_timeout_seconds: float = Field(
        default=60.0,
        description=(
            "Live-discovered: ChatOllama has no default timeout, so a single "
            "stalled call (any of the several per request, across an agent's "
            "tool loop) can hang a request indefinitely with no recovery."
        ),
    )

    # --- Retrieval providers (FR-6) ---
    # All optional: a provider without credentials is simply not offered to the
    # Retrieval & Evidence Agent as a tool (FR-6.1 already requires dynamic
    # provider selection, so "not configured" is just one more input to that).
    spotify_client_id: str = ""
    spotify_client_secret: str = ""

    youtube_api_key: str = ""

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "orchestra-recommender/0.1"

    lastfm_api_key: str = ""

    # musicbrainzngs and ytmusicapi have no built-in request timeout (the
    # httpx-based clients above already set one directly) — this bounds the
    # caller's wait around their asyncio.to_thread calls instead.
    provider_call_timeout_seconds: float = 20.0

    # MusicBrainz needs no credentials, only a good-citizen User-Agent
    # (name/version/contact) per their API usage policy.
    musicbrainz_contact: str = "orchestra-recommender-dev@example.com"

    # YouTube Music (ytmusicapi) search works unauthenticated — no setting needed.

    # --- Audio Analysis (FR-3.2/3.4, architecture.md §4/§9) ---
    # Music Flamingo hosting (Modal/RunPod) is still an open call (§9 item 3)
    # — unset by default. Absence must not block recommendations (FR-3.2), so
    # this follows the same optional/"*NotConfigured" pattern as the
    # retrieval providers above rather than being treated as required.
    music_flamingo_endpoint_url: str = ""
    music_flamingo_api_key: str = ""
    music_flamingo_timeout_seconds: int = Field(
        default=90,
        description="Generous timeout for serverless GPU cold starts (~20-45s per §9)",
    )

    # --- Auth (magic link + JWT) ---
    jwt_secret: str = Field(
        default=_DEFAULT_JWT_SECRET,
        description="Secret used to sign JWTs. MUST be overridden in production.",
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    magic_link_expire_minutes: int = 15

    # --- Rate limiting (Phase 7, architecture.md §7) ---
    # Discovery limits are shared across /discover, /retrieve, /analyze-audio
    # since all three draw on the same YouTube quota + Ollama Cloud balance.
    rate_limit_discovery_per_identity_per_hour: int = 5
    rate_limit_discovery_global_per_day: int = 40
    rate_limit_request_link_per_ip_per_hour: int = 5

    @model_validator(mode="after")
    def _forbid_default_jwt_secret_in_production(self) -> "Settings":
        if self.environment == "production" and self.jwt_secret == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET is still the default placeholder — set a real secret "
                "before running with ENVIRONMENT=production."
            )
        return self

    # --- Email (magic link delivery) ---
    email_from: str = "orchestra@example.com"
    # Dev stub logs the link instead of sending it (see app/clients/email.py).
    # Swap in Resend or SMTP config here before real testers go live.

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Frontend (magic link target) ---
    frontend_base_url: str = Field(
        default="http://localhost:5173",
        description="Base URL the magic link points at, e.g. {base}/verify?token=...",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
