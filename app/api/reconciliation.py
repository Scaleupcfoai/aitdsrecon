"""Reconciliation router — run pipeline, get status, stream events, answer questions."""

import json
import queue
import threading
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_db, get_current_user, UserContext
from app.db.repository import Repository
from app.pipeline.orchestrator import run_reconciliation
from app.pipeline.events import EventEmitter

router = APIRouter(tags=["reconciliation"])

UPLOAD_DIR = Path("data/uploads")


@router.post("/reconciliation/run")
def start_reconciliation(
    company_id: str,
    financial_year: str = "2024-25",
    db: Repository = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Start a reconciliation run (non-streaming). Returns when complete."""
    firm_id = user.firm_id
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
    user: UserContext = Depends(get_current_user),
):
    """Run reconciliation with real-time SSE streaming.

    Each agent event streamed as it happens — LLM calls visible in real-time.
    """
    event_queue = queue.Queue()

    def on_event(event):
        event_queue.put(event)

    firm_id = user.firm_id
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


class AnswerRequest(BaseModel):
    question_id: str
    selected: list[str] = []
    text_input: str | None = None
    confirmed_mappings: list[dict] | None = None  # for column confirmation


@router.post("/answer")
def submit_answer(
    req: AnswerRequest,
    db: Repository = Depends(get_db),
):
    """Submit user answer to a pipeline question.

    For column confirmation: includes confirmed_mappings list.
    For other questions: includes selected options and/or text input.
    """
    answer_data = {
        "selected": req.selected,
        "text_input": req.text_input,
    }

    # If this is a column confirmation, save mappings to DB
    if req.confirmed_mappings:
        answer_data["confirmed_mappings"] = req.confirmed_mappings

        # Save to column_map table with confirmed=True
        from app.matching.cache import MappingCache
        cache = MappingCache(db)

        # Group by file_type
        for mapping in req.confirmed_mappings:
            company_id = mapping.get("company_id", "")
            file_type = mapping.get("file_type", "ledger")
            columns = mapping.get("columns", [])
            if company_id and columns:
                cache.save(
                    company_id=company_id,
                    file_type=file_type,
                    mappings=columns,
                )

    EventEmitter.set_answer(req.question_id, answer_data)
    return {"status": "ok", "question_id": req.question_id}


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
