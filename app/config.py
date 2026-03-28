"""
Application configuration — all settings from environment variables.

Usage:
    from app.config import settings
    print(settings.supabase_url)

Settings are loaded from .env file (local dev) or environment variables (production).
Never hardcode secrets or URLs in code — always use this module.
"""

from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All application configuration.

    Values come from environment variables or .env file.
    Required fields (no default) will raise an error if missing.
    """

    # ── Supabase ──
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str = ""

    # ── Database (direct PostgreSQL connection for performance-critical queries) ──
    database_url: str = ""

    # ── Anthropic (added later — empty string means disabled) ──
    anthropic_api_key: str = ""

    # ── File Storage ──
    storage_backend: Literal["local", "supabase"] = "local"
    local_storage_path: str = "data/uploads"

    # ── Security ──
    cors_origins: list[str] = ["http://localhost:5173"]

    # ── Environment ──
    environment: Literal["local", "staging", "production"] = "local"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Global settings instance — import this everywhere
settings = Settings()
