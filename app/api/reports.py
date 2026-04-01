"""Reports router — download generated reports."""

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.dependencies import get_db
from app.db.repository import Repository

router = APIRouter(tags=["reports"])

REPORTS_DIR = Path("data/reports")


@router.get("/reports/{run_id}/summary")
def get_summary(run_id: str, db: Repository = Depends(get_db)):
    """Get reconciliation summary from DB."""
    summaries = db.summaries.get_by_run(run_id)
    if not summaries:
        return {"error": "No summary found. Run the pipeline first."}
    return [{"section": s.section, "group_key": s.group_key,
             "entry_count": s.entry_count, "llm_summary": s.llm_summary,
             "status": s.status} for s in summaries]


@router.get("/reports/{run_id}/findings")
def get_findings(run_id: str, db: Repository = Depends(get_db)):
    """Get compliance findings from DB."""
    matches = db.matches.get_by_run(run_id)
    findings = []
    for m in matches:
        actions = db.discrepancies.get_by_match(m.id)
        for a in actions:
            findings.append({
                "stage": a.stage, "action_status": a.action_status,
                "llm_reasoning": a.llm_reasoning,
                "proposed_action": a.proposed_action,
            })
    return {"count": len(findings), "findings": findings}


@router.get("/reports/{run_id}/download/{filename}")
def download_report(run_id: str, filename: str):
    """Download a report file (CSV, XLSX, JSON)."""
    allowed = {
        "tds_recon_report.xlsx",
        "reconciliation_report.csv",
        "findings_report.csv",
        "reconciliation_summary.json",
    }
    if filename not in allowed:
        return {"error": f"File not available: {filename}"}
    fpath = REPORTS_DIR / filename
    if not fpath.exists():
        return {"error": "File not found. Run the pipeline first."}
    return FileResponse(path=str(fpath), filename=filename,
                        media_type="application/octet-stream")
