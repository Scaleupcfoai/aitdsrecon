from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import create_client

from app.dependencies import get_db, get_current_user, UserContext
from app.db.repository import Repository
from app.config import settings

router = APIRouter(tags=["auth"])


class RegisterFirmRequest(BaseModel):
    firm_name: str
    firm_pan: str = ""
    firm_address: str = ""


@router.get("/auth/me")
def get_me(user: UserContext = Depends(get_current_user)):
    print(f"User {user.user_id} authenticated with role {user.role} in firm {user.firm_id}")
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
    # 1. Create the firm in DB
    firm = db.firms.create(
        name=req.firm_name,
        pan_no=req.firm_pan or None,
        address=req.firm_address or None,
    )

    # 2. Update user metadata in Supabase Auth so JWT gets firm_id on next refresh
    try:
        admin_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,  # needs service role key
        )
        admin_client.auth.admin.update_user_by_id(
            user.user_id,
            {"user_metadata": {"firm_id": str(firm.id)}},
        )
    except Exception as e:
        # Firm was created — don't rollback, just warn
        print(f"[warn] Could not update user metadata: {e}")

    return {
        "firm_id": firm.id,
        "firm_name": firm.name,
        "message": "Firm registered successfully.",
    }


@router.get("/auth/health")
def health():
    return {"status": "ok", "auth": "supabase_jwt"}