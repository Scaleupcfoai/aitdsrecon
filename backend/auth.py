"""Google OAuth (OIDC) + local dev bypass.

Two modes:
  - Real OAuth: set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in .env.
  - Dev bypass: if those are missing, `/auth/dev-login` returns a fake user.
    Hidden entirely in production; gated by an explicit env flag.

Routes mounted under /auth/*:
  GET  /auth/me                    current user (or 401)
  GET  /auth/google/login          redirect to Google consent
  GET  /auth/google/callback       exchange code, set session cookie, redirect to UI
  POST /auth/logout                clear session cookie
  POST /auth/dev-login             dev-only shortcut (disabled in production)

The user's email is stored in the Starlette session (signed cookie). Downstream
routes pick it up via `Depends(require_user)`.
"""

from __future__ import annotations

import os
import secrets
from typing import Any

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])


def _frontend_url() -> str:
    return os.getenv("FRONTEND_URL", "http://localhost:5173")


def _oauth_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def _dev_bypass_allowed() -> bool:
    """Dev bypass is ON only when OAuth isn't configured AND we're not running in prod."""
    if _oauth_configured():
        return False
    return os.getenv("ENV", "development") != "production"


# ── Authlib OAuth client (lazy — only initialised when credentials are present) ──
oauth = OAuth()
if _oauth_configured():
    oauth.register(
        name="google",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


# ── Dependency for protected routes ──

def require_user(request: Request) -> dict[str, Any]:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return user


def current_user_optional(request: Request) -> dict[str, Any] | None:
    return request.session.get("user")


# ── Routes ──

@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    user = request.session.get("user")
    if not user:
        return {
            "authenticated": False,
            "oauth_configured": _oauth_configured(),
            "dev_bypass": _dev_bypass_allowed(),
        }
    return {
        "authenticated": True,
        "user": user,
        "oauth_configured": _oauth_configured(),
        "dev_bypass": _dev_bypass_allowed(),
    }


@router.get("/google/login")
async def google_login(request: Request):
    if not _oauth_configured():
        raise HTTPException(
            status_code=503,
            detail="Google OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    redirect_uri = os.getenv(
        "OAUTH_REDIRECT_URI",
        str(request.url_for("google_callback")),
    )
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request):
    if not _oauth_configured():
        raise HTTPException(status_code=503, detail="Google OAuth not configured.")
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"oauth_error: {e.error}")
    user_info = token.get("userinfo") or {}
    email = user_info.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="google_returned_no_email")
    request.session["user"] = {
        "email": email,
        "name": user_info.get("name"),
        "picture": user_info.get("picture"),
        "auth_via": "google",
    }
    return RedirectResponse(url=_frontend_url())


class DevLoginRequest(BaseModel):
    email: str
    name: str | None = None


@router.post("/dev-login")
def dev_login(req: DevLoginRequest, request: Request) -> dict[str, Any]:
    if not _dev_bypass_allowed():
        raise HTTPException(
            status_code=403,
            detail="dev bypass is disabled (either OAuth is configured or ENV=production).",
        )
    request.session["user"] = {
        "email": req.email,
        "name": req.name or req.email.split("@")[0],
        "picture": None,
        "auth_via": "dev_bypass",
    }
    return {"authenticated": True, "user": request.session["user"]}


@router.post("/logout")
def logout(request: Request) -> dict[str, Any]:
    request.session.pop("user", None)
    return {"authenticated": False}


def get_session_secret() -> str:
    """Load session secret from env or generate an ephemeral one (dev only)."""
    sec = os.getenv("SESSION_SECRET")
    if sec:
        return sec
    # Ephemeral — if the server restarts, everyone logs out. Fine for local dev.
    # Log a warning exactly once.
    if not hasattr(get_session_secret, "_warned"):
        print(
            "[auth] WARNING: SESSION_SECRET not set. Generated an ephemeral one. "
            "Set SESSION_SECRET in .env for persistent sessions.",
            flush=True,
        )
        get_session_secret._warned = True  # type: ignore[attr-defined]
    return secrets.token_urlsafe(48)
