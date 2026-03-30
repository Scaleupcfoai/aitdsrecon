"""Upload router — file upload + column mapping."""

import shutil
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, Depends

from app.dependencies import get_db, get_llm, get_current_user
from app.db.repository import Repository
from app.services.llm_client import LLMClient
from app.services.column_mapper import ColumnMapper

router = APIRouter(tags=["upload"])

UPLOAD_DIR = Path("data/uploads")


@router.post("/upload")
async def upload_files(
    form26: UploadFile = File(...),
    tally: UploadFile = File(...),
    db: Repository = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Upload Form 26 and Tally XLSX files."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    form26_path = UPLOAD_DIR / f"{user['firm_id']}_form26.xlsx"
    tally_path = UPLOAD_DIR / f"{user['firm_id']}_tally.xlsx"

    with open(form26_path, "wb") as f:
        shutil.copyfileobj(form26.file, f)
    with open(tally_path, "wb") as f:
        shutil.copyfileobj(tally.file, f)

    return {
        "status": "uploaded",
        "form26": {"name": form26.filename, "path": str(form26_path)},
        "tally": {"name": tally.filename, "path": str(tally_path)},
    }


@router.post("/upload/map-columns")
async def map_columns(
    file_path: str,
    file_type: str = "auto",
    company_id: str = "",
    db: Repository = Depends(get_db),
    llm: LLMClient = Depends(get_llm),
):
    """Run column mapper on an uploaded file. Returns mappings with review flags."""
    mapper = ColumnMapper(repo=db, llm=llm)
    result = mapper.map_file(file_path, company_id=company_id, file_type=file_type)
    return result
