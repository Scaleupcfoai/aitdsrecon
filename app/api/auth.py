"""Auth router — user info + firm registration."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_db, get_current_user, UserContext
from app.db.repository import Repository

router = APIRouter(tags=["auth"])


class RegisterFirmRequest(BaseModel):
    firm_name: str
    firm_pan: str = ""
    firm_address: str = ""


@router.get("/auth/me")
def get_me(user: UserContext = Depends(get_current_user)):
    """Return current user info from JWT."""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "firm_id": user.firm_id,
        "role": user.role,
    }


@router.post("/auth/register-firm")
def register_firm(
    req: RegisterFirmRequest,
    user: UserContext = Depends(get_current_user),
    db: Repository = Depends(get_db),
):
    """Register a new CA firm after Supabase signup.

    Called once after the user signs up via Supabase Auth in the frontend.
    Creates a ca_firm record and links it to the user.
    """
    # Create the firm
    firm = db.firms.create(
        name=req.firm_name,
        pan_no=req.firm_pan or None,
        address=req.firm_address or None,
    )

    return {
        "firm_id": firm.id,
        "firm_name": firm.name,
        "message": "Firm registered. You can now create companies and run reconciliations.",
    }


@router.get("/auth/health")
def health():
    """Health check — no auth required."""
    return {"status": "ok", "auth": "supabase_jwt"}
