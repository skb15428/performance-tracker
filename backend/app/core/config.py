from functools import lru_cache
from pathlib import Path

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Absolute path so the MCP server works no matter which directory Claude launches it from.
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    database_url: str = f"sqlite+aiosqlite:///{BACKEND_DIR / 'goalcoach.db'}"
    # The single user the local MCP server acts as (created on first use).
    owner_email: str = "me@example.com"
    jwt_secret: str = "change-me"
    jwt_lifetime_seconds: int = 60 * 60 * 24 * 14
    # Fernet key used to encrypt per-user API keys. Generate with
    # `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
    fernet_key: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"

    jobs_secret: str = "change-me-too"
    # Single-user app: keep sign-ups off on a public deployment (create the owner with scripts/set_password.py).
    allow_registration: bool = False
    # Public HTTPS URL of this API (e.g. https://goalcoach-api.onrender.com). When set, the MCP server is also
    # served remotely at {public_url}/mcp with OAuth, so Claude on web/mobile can use it.
    public_url: str = ""

    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # Scoring knobs
    llm_weight: float = 0.5

    @field_validator("database_url")
    @classmethod
    def asyncpg_url(cls, url: str) -> str:
        """Accept plain Postgres URLs (e.g. Neon's `postgresql://...?sslmode=require`) and adapt them for asyncpg."""
        if url.startswith(("postgres://", "postgresql://")):
            url = "postgresql+asyncpg://" + url.split("://", 1)[1]
        if not url.startswith("postgresql+asyncpg://"):
            return url
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query))
        if "sslmode" in query:
            query["ssl"] = query.pop("sslmode")
        query.pop("channel_binding", None)
        return urlunsplit(parts._replace(query=urlencode(query)))


@lru_cache
def get_settings() -> Settings:
    return Settings()
