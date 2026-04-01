"""
FastAPI dependencies — injected into route handlers.

Auth: uses Supabase JWT verification from app/auth/.
DB: uses admin client (service_role) for backend operations.
LLM: creates LLM client instance.

Usage in routers:
    @router.get("/api/something")
    def something(db = Depends(get_db), user = Depends(get_current_user)):
        ...
"""

from app.db.client import get_admin_client
from app.db.repository import Repository
from app.services.llm_client import LLMClient

# Re-export auth dependencies so routers can import from one place
from app.auth.dependencies import get_current_user, UserContext, require_firm_id


def get_db() -> Repository:
    """Get repository instance with admin client (backend operations)."""
    return Repository(client=get_admin_client())


def get_llm() -> LLMClient:
    """Get LLM client instance."""
    return LLMClient()
