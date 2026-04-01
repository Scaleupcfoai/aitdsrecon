"""
Supabase client — connections used by all repositories.

Two clients:
- anon client: uses anon key, RLS applies (for user-facing API requests)
- admin client: uses service_role key, bypasses RLS (for backend operations + tests)

Usage:
    from app.db.client import get_client, get_admin_client
    client = get_client()           # RLS enforced (for API endpoints)
    admin = get_admin_client()      # RLS bypassed (for agents + tests)
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache()
def get_client() -> Client:
    """Anon client — RLS enforced. Use for user-facing API requests."""
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@lru_cache()
def get_admin_client() -> Client:
    """Admin client — RLS bypassed. Use for backend agents, tests, and migrations.

    Requires SUPABASE_SERVICE_ROLE_KEY in .env.
    """
    key = settings.supabase_service_role_key
    if not key:
        raise ValueError(
            "SUPABASE_SERVICE_ROLE_KEY is required for admin operations. "
            "Find it in Supabase Dashboard → Settings → API → service_role key."
        )
    return create_client(settings.supabase_url, key)
