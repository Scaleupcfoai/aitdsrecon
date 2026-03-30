"""Company router — CRUD for companies under a CA firm."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.dependencies import get_db, get_current_user, UserContext
from app.db.repository import Repository

router = APIRouter(tags=["company"])


class CreateCompanyRequest(BaseModel):
    company_name: str
    pan: str
    tan: str = ""
    gstin: str = ""
    address: str = ""
    state_code: str = ""
    company_type: str = "company"


@router.get("/companies")
def list_companies(
    db: Repository = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """List all companies for the current firm."""
    companies = db.companies.list_by_firm(user.firm_id)
    return [{"id": c.id, "company_name": c.company_name, "pan": c.pan,
             "company_type": c.company_type} for c in companies]


@router.post("/companies")
def create_company(
    req: CreateCompanyRequest,
    db: Repository = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Create a new company under the current firm."""
    company = db.companies.create(
        firm_id=user.firm_id,
        company_name=req.company_name,
        pan=req.pan,
        tan=req.tan or None,
        gstin=req.gstin or None,
        address=req.address or None,
        state_code=req.state_code or None,
        company_type=req.company_type,
    )
    return {"id": company.id, "company_name": company.company_name, "pan": company.pan}


@router.get("/companies/{company_id}")
def get_company(
    company_id: str,
    db: Repository = Depends(get_db),
):
    """Get company details."""
    company = db.companies.get_by_id(company_id)
    if not company:
        return {"error": "Company not found"}
    return {"id": company.id, "company_name": company.company_name,
            "pan": company.pan, "company_type": company.company_type}
