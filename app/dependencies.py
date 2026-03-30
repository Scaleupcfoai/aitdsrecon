"""
FastAPI dependencies — injected into route handlers.

Usage in routers:
    @router.get("/api/something")
    def something(db: Repository = Depends(get_db), user = Depends(get_current_user)):
        ...
"""

from app.db.client import get_admin_client
from app.db.repository import Repository
from app.services.llm_client import LLMClient
from app.pipeline.events import EventEmitter


def get_db() -> Repository:
    """Get repository instance. Uses admin client for now (auth added Day 11)."""
    return Repository(client=get_admin_client())


def get_llm() -> LLMClient:
    """Get LLM client instance."""
    return LLMClient()


def get_current_user() -> dict:
    """Get current user. Placeholder — returns hardcoded user until auth is wired (Day 11)."""
    return {
        "user_id": "placeholder-user",
        "email": "dev@lekha.ai",
        "firm_id": "placeholder-firm",
    }
