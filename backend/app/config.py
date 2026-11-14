"""Application configuration via pydantic-settings.

All values are read from environment variables (or a `.env` file in the
backend directory). Never hardcode secrets here.
"""

from functools import lru_cache
from typing import Literal

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
    # development: link only in the backend log. test: the sign-in link is also
    # returned to the UI (no email server needed). production: never exposed.
    environment: Literal["development", "test", "production"] = "development"
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
    ollama_primary_model: str = "glm-5.3-flash:cloud"
    ollama_fallback_model: str = "glm-5.3-flash:cloud"
    ollama_request_timeout_seconds: float | None = Field(
        default=None,
        description=(
            "Read timeout for a model call, i.e. the longest silence tolerated "
            "while waiting for the next streamed chunk. None (default) waits as "
            "long as the model needs: a reasoning model can think for minutes "
            "before its first token. Runaway requests are bounded by the "
            "retrieval tool/round budgets and discovery_timeout_seconds."
        ),
    )
    ollama_connect_timeout_seconds: float = Field(
        default=15.0,
        description="Connection timeout only; fails fast when Ollama is unreachable.",
    )

    # --- Retrieval providers (FR-6) ---
    # All optional: a provider without credentials is simply not offered to the
    # Retrieval & Evidence Agent as a tool (FR-6.1 already requires dynamic
    # provider selection, so "not configured" is just one more input to that).
    spotify_client_id: str = ""
    spotify_client_secret: str = ""

    youtube_api_key: str = ""

    lastfm_api_key: str = ""

    # Reddit via Composio's managed OAuth app (docs/10-reddit-composio.md). Reddit API
    # credentials of our own are not needed: sign in once with `scripts/composio_reddit_check.py`.
    composio_api_key: str = ""
    composio_user_id: str = "orchestra-backend"  # the Composio "user" the Reddit login belongs to
    composio_reddit_connected_account_id: str = ""  # optional; pin when several Reddit logins exist
    reddit_max_comment_chars: int = 400

    # User-built playlist evidence (docs/09-playlist-evidence.md). Spotify publishes
    # no numeric limits, so these keep one request to a bounded number of calls:
    # worst case = searches + fetches * pages  (default 6 + 15 * 2 = 36).
    spotify_playlist_concurrency: int = 4
    playlist_max_searches: int = 6
    playlist_max_fetches: int = 15
    playlist_max_tracks: int = 200  # per playlist; 2 pages of 100
    # Score multiplier for Spotify-owned (editorial) playlists vs user-built (=1.0).
    playlist_editorial_weight: float = 0.25

    # Playlist export (FR-16) uses the same Spotify app but the Authorization
    # Code flow. Spotify rejects `localhost` redirect URIs: use the loopback IP
    # and register this exact string in the Spotify developer dashboard.
    spotify_redirect_uri: str = "http://127.0.0.1:8000/api/spotify/callback"

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
    # Modal proxy token (Modal-Key / Modal-Secret): lets the request past Modal's edge check,
    # which rejects unauthenticated calls before a GPU container starts.
    music_flamingo_proxy_key: str = ""
    music_flamingo_proxy_secret: str = ""
    music_flamingo_timeout_seconds: int = Field(
        default=600,
        description=(
            "Whole-call timeout for the captioning endpoint. Must exceed a worst-case Modal "
            "cold start (measured up to ~180 s when no GPU is free) plus inference."
        ),
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
    # Chat messages (intent parsing only; a discovery additionally draws on the budget above).
    rate_limit_chat_per_identity_per_hour: int = 60

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

    # --- Supervisor agent ---
    # Optional wall-clock limit for one discovery request. Off by default: runs
    # are bounded by the step budgets below instead. If set and exceeded, the
    # request ends gracefully with whatever finished plus an explanatory
    # message (it never errors out).
    discovery_timeout_seconds: float | None = None
    # Bounds the supervisor's model<->tools loop.
    agent_recursion_limit: int = 40
    # Retrieval sub-agent budget (FR-6.2). Live, with no budget it kept issuing
    # searches for 10 minutes without ever answering; each model round is slow,
    # the searches are not. After `retrieval_max_tool_calls` calls it is told to
    # finish; `retrieval_max_model_rounds` is the hard backstop.
    retrieval_max_tool_calls: int = 60
    retrieval_max_model_rounds: int = 20
    # Reddit allowances inside that budget (stated in the retrieval prompt and
    # enforced in app/tools/retrieval.py).
    retrieval_max_reddit_searches: int = 6
    retrieval_max_reddit_threads: int = 4

    # --- Observability (Phase 7b) ---
    # Empty URI disables MLflow tracing entirely; the DB event log (FR-19)
    # is always on.
    mlflow_tracking_uri: str = ""
    mlflow_experiment_name: str = "orchestra"

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
