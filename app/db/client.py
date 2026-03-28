"""
Supabase client — single connection used by all repositories.

Usage:
    from app.db.client import get_client
    client = get_client()
    result = client.table("ca_firm").select("*").execute()
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import settings


@lru_cache()
def get_client() -> Client:
    """Get or create the Supabase client (cached — created once, reused forever)."""
    return create_client(settings.supabase_url, settings.supabase_anon_key)
