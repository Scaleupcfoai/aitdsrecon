"""Reconciliation router — run pipeline, get status, stream events."""

import json
import queue
import threading
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.dependencies import get_db, get_current_user
from app.db.repository import Repository
from app.pipeline.orchestrator import run_reconciliation

router = APIRouter(tags=["reconciliation"])

UPLOAD_DIR = Path("data/uploads")


@router.post("/reconciliation/run")
def start_reconciliation(
    company_id: str,
    financial_year: str = "2024-25",
    db: Repository = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Start a reconciliation run (non-streaming). Returns when complete."""
    firm_id = user["firm_id"]
    form26_path = str(UPLOAD_DIR / f"{firm_id}_form26.xlsx")
    tally_path = str(UPLOAD_DIR / f"{firm_id}_tally.xlsx")

    result = run_reconciliation(
        company_id=company_id,
        firm_id=firm_id,
        financial_year=financial_year,
        form26_path=form26_path,
        tally_path=tally_path,
        db=db,
    )
    return result


@router.get("/reconciliation/stream")
def stream_reconciliation(
    company_id: str,
    financial_year: str = "2024-25",
    db: Repository = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Run reconciliation with real-time SSE streaming.

    Each agent event streamed as it happens — LLM calls visible in real-time.
    """
    event_queue = queue.Queue()

    def on_event(event):
        event_queue.put(event)

    firm_id = user["firm_id"]
    form26_path = str(UPLOAD_DIR / f"{firm_id}_form26.xlsx")
    tally_path = str(UPLOAD_DIR / f"{firm_id}_tally.xlsx")

    def run_in_thread():
        result = run_reconciliation(
            company_id=company_id,
            firm_id=firm_id,
            financial_year=financial_year,
            form26_path=form26_path,
            tally_path=tally_path,
            db=db,
            on_event=on_event,
        )
        # Send final results as pipeline_complete event
        event_queue.put({
            "type": "pipeline_complete",
            "agent": "Pipeline",
            "message": f"Complete in {result.get('elapsed_s', 0)}s",
            "summary": result.get("summary", {}),
            "errors": result.get("errors", []),
            "run_id": result.get("run_id", ""),
        })
        event_queue.put(None)  # sentinel

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    def event_generator():
        while True:
            try:
                event = event_queue.get(timeout=60)
                if event is None:
                    break
                yield f"data: {json.dumps(event, default=str)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'keepalive'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/reconciliation/status/{run_id}")
def get_run_status(
    run_id: str,
    db: Repository = Depends(get_db),
):
    """Get current status of a reconciliation run."""
    run = db.runs.get_by_id(run_id)
    if not run:
        return {"error": "Run not found"}
    return {
        "run_id": run.id,
        "status": run.status,
        "processing_status": run.processing_status,
        "current_section": run.current_section,
    }


@router.get("/reconciliation/runs")
def list_runs(
    company_id: str,
    db: Repository = Depends(get_db),
):
    """List all reconciliation runs for a company."""
    runs = db.runs.list_by_company(company_id)
    return [{
        "run_id": r.id,
        "status": r.status,
        "financial_year": r.financial_year,
        "created_at": r.created_at,
    } for r in runs]
