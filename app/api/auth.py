"""Auth router — placeholder until Day 11 (Supabase Auth + JWT)."""

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user

router = APIRouter(tags=["auth"])


@router.get("/auth/me")
def get_me(user: dict = Depends(get_current_user)):
    """Return current user info. Placeholder — returns hardcoded user."""
    return user


@router.get("/auth/health")
def health():
    """Health check — no auth required."""
    return {"status": "ok", "auth": "placeholder"}
