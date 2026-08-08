"""Application configuration via pydantic-settings.

All values are read from environment variables (or a `.env` file in the
backend directory). Never hardcode secrets here.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        description="Async SQLAlchemy URL for PostgreSQL (host port 5433 avoids clashing with a local Postgres on 5432)",
    )

    # --- Redis ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (session state + rate limiting)",
    )

    # --- LLM (Ollama Cloud) ---
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama endpoint (local or Ollama Cloud base URL)",
    )
    ollama_api_key: str = Field(
        default="",
        description="Ollama Cloud API key (empty for local Ollama)",
    )
    ollama_primary_model: str = "kimi-k3:cloud"
    ollama_fallback_model: str = "deepseek-v4-flash:cloud"

    # --- Auth (magic link + JWT) ---
    jwt_secret: str = Field(
        default="change-me-in-production",
        description="Secret used to sign JWTs. MUST be overridden in production.",
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    magic_link_expire_minutes: int = 15

    # --- Email (magic link delivery) ---
    email_from: str = "orchestra@example.com"
    # SMTP or Resend config goes here once the sender is chosen.

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
