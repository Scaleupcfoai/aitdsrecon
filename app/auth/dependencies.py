"""
Auth dependencies for FastAPI — extract user from JWT in request headers.

Usage in routers:
    from app.auth.dependencies import get_current_user, UserContext

    @router.get("/something")
    def something(user: UserContext = Depends(get_current_user)):
        print(user.firm_id)
"""

from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.auth.jwt import verify_token
from app.config import settings


@dataclass
class UserContext:
    """Authenticated user context extracted from JWT."""
    user_id: str
    email: str
    firm_id: str
    role: str = "authenticated"


def get_current_user(authorization: str = Header(default="")) -> UserContext:
    """Extract and verify user from Authorization header.

    In local dev with no auth configured, returns a placeholder user.
    In staging/production, requires a valid Supabase JWT.

    Raises HTTPException 401 if token is missing or invalid.
    """
    # If no auth header and we're in local dev, return placeholder
    if not authorization and settings.environment == "local":
        return UserContext(
            user_id="local-dev-user",
            email="dev@lekha.ai",
            firm_id="local-dev-firm",
            role="authenticated",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    try:
        payload = verify_token(authorization)
        return UserContext(
            user_id=payload["user_id"],
            email=payload["email"],
            firm_id=payload.get("firm_id", ""),
            role=payload.get("role", "authenticated"),
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def require_firm_id(user: UserContext = None) -> UserContext:
    """Ensure user has a firm_id. Used for endpoints that need firm context."""
    if not user or not user.firm_id:
        raise HTTPException(
            status_code=403,
            detail="No firm associated with this account. Complete registration first."
        )
    return user
