"""TDS Reconciliation routes — mounted into the main backend API.

Originally lived at tds-recon/api_server.py as a standalone FastAPI app.
Refactored into an APIRouter so the lekha tds-calculator backend and the
TDS reconciliation backend can run as a single uvicorn process.

Routes (all mounted under /api/...):
  GET  /api/status                 parsed/results/rules readiness
  POST /api/run                    run the pipeline (blocking, returns full result)
  GET  /api/run/stream             run pipeline, stream events as SSE
  GET  /api/run/stream/upload      same but using files staged by /api/upload
  POST /api/upload                 accept multipart form26 + tally files
  GET  /api/results                cached match/checker/summary results
  GET  /api/rules                  learned rules + summary
  POST /api/review                 submit human review decisions
  GET  /api/download/{name}        download a file from data/results/
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["tds-recon"])

BASE = Path(__file__).parent
DATA_DIR = BASE / "data"
RESULTS_DIR = DATA_DIR / "results"
RULES_DIR = DATA_DIR / "rules"
PARSED_DIR = DATA_DIR / "parsed"
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Where /api/upload writes the user-supplied files. /api/run/stream/upload
# reads these.
FORM26_UPLOAD_NAME = "form26_uploaded.xlsx"
TALLY_UPLOAD_NAME = "tally_uploaded.xlsx"

ALLOWED_DOWNLOAD_EXTS = {".csv", ".json", ".xlsx"}


@router.get("/api/status")
def get_status():
    """Check if parsed data and results exist."""
    return {
        "parsed_ready": (PARSED_DIR / "parsed_form26.json").exists(),
        "results_ready": (RESULTS_DIR / "match_results.json").exists(),
        "rules_ready": (RULES_DIR / "learned_rules.json").exists(),
    }


@router.post("/api/run")
def run_pipeline_endpoint():
    """Execute the full reconciliation pipeline and return events + results."""
    from .reconcile import run_pipeline as _run
    result = _run()
    results_data = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results_data[fname.replace(".json", "")] = json.load(f)
    result["results"] = results_data
    return result


@router.post("/api/upload")
async def upload_form26_and_tally(
    form26: UploadFile = File(...),
    tally: UploadFile = File(...),
):
    """Stage Form 26 and Tally files for the next /api/run/stream/upload call.

    Files are saved to data/uploads/ with fixed names so the streaming
    endpoint can find them without juggling session state.
    """
    for f, label in [(form26, "form26"), (tally, "tally")]:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in {".xlsx", ".xls"}:
            raise HTTPException(
                status_code=400,
                detail=f"{label} has unsupported extension '{ext}' (expected .xlsx/.xls)",
            )

    form26_path = UPLOAD_DIR / FORM26_UPLOAD_NAME
    tally_path = UPLOAD_DIR / TALLY_UPLOAD_NAME
    form26_path.write_bytes(await form26.read())
    tally_path.write_bytes(await tally.read())

    return {
        "status": "uploaded",
        "form26": form26.filename,
        "tally": tally.filename,
        "form26_size": form26_path.stat().st_size,
        "tally_size": tally_path.stat().st_size,
    }


def _stream_pipeline(form26_path: str | None, tally_path: str | None):
    """Run the pipeline in a background thread, stream events as SSE.

    The pipeline emits events via the global EventLogger. We poll the
    logger's event list, yielding any new entries as SSE messages.
    """
    from .agents.event_logger import get_logger, reset_logger
    from .reconcile import run_pipeline as _run

    reset_logger()
    logger = get_logger()

    # Result holder for the worker thread.
    result_holder: dict = {}
    error_holder: dict = {}

    def worker():
        try:
            result_holder["value"] = _run(form26_path=form26_path, tally_path=tally_path)
        except Exception as e:  # noqa: BLE001 — surface to the SSE consumer
            error_holder["error"] = f"{type(e).__name__}: {e}"

    async def gen():
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        seen = 0
        # Send a keepalive every ~1s of idleness so the EventSource stays open.
        idle = 0
        while True:
            events = logger.get_events()
            new = events[seen:]
            if new:
                idle = 0
                for ev in new:
                    yield f"data: {json.dumps(ev)}\n\n"
                seen = len(events)
            else:
                idle += 1
                if idle >= 10:  # ~1s of no events
                    yield 'data: {"type":"keepalive"}\n\n'
                    idle = 0

            if not thread.is_alive():
                # Drain any final events posted just before exit.
                events = logger.get_events()
                if seen < len(events):
                    for ev in events[seen:]:
                        yield f"data: {json.dumps(ev)}\n\n"
                    seen = len(events)

                if "error" in error_holder:
                    yield f'data: {json.dumps({"type": "error", "agent": "Pipeline", "message": error_holder["error"]})}\n\n'
                else:
                    payload = {
                        "type": "pipeline_complete",
                        "agent": "Pipeline",
                        "message": "Done",
                        "result": result_holder.get("value", {}),
                    }
                    # Embed cached results so the UI can render without a
                    # follow-up GET.
                    cached = {}
                    for fname in [
                        "match_results.json",
                        "checker_results.json",
                        "reconciliation_summary.json",
                    ]:
                        fpath = RESULTS_DIR / fname
                        if fpath.exists():
                            try:
                                with open(fpath) as f:
                                    cached[fname.replace(".json", "")] = json.load(f)
                            except json.JSONDecodeError:
                                pass
                    payload["results"] = cached
                    yield f"data: {json.dumps(payload)}\n\n"
                return

            await asyncio.sleep(0.1)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/api/run/stream")
def stream_pipeline_cached():
    """Stream pipeline events using already-parsed (cached) data."""
    return _stream_pipeline(form26_path=None, tally_path=None)


@router.get("/api/run/stream/upload")
def stream_pipeline_uploaded():
    """Stream pipeline events using files staged by /api/upload."""
    form26_path = UPLOAD_DIR / FORM26_UPLOAD_NAME
    tally_path = UPLOAD_DIR / TALLY_UPLOAD_NAME
    if not form26_path.exists() or not tally_path.exists():
        raise HTTPException(
            status_code=409,
            detail="No uploaded files found. POST /api/upload first.",
        )
    return _stream_pipeline(form26_path=str(form26_path), tally_path=str(tally_path))


@router.get("/api/results")
def get_results():
    """Read cached results from disk."""
    results = {}
    for fname in ["match_results.json", "checker_results.json", "reconciliation_summary.json"]:
        fpath = RESULTS_DIR / fname
        if fpath.exists():
            with open(fpath) as f:
                results[fname.replace(".json", "")] = json.load(f)
    return results


@router.get("/api/rules")
def get_rules():
    """Get current learned rules."""
    from .agents.learning_agent import load_rules, summarize_rules
    db = load_rules(str(RULES_DIR))
    summary = summarize_rules(str(RULES_DIR))
    return {"rules": db, "summary": summary}


class ReviewDecision(BaseModel):
    vendor: str
    decision: str  # below_threshold, exempt, ignore, alias, section_override
    params: dict = {}
    reason: str = ""


class ReviewRequest(BaseModel):
    decisions: list[ReviewDecision]


@router.post("/api/review")
def submit_review(request: ReviewRequest):
    """Submit human review decisions — apply corrections to affected entries only.

    Does NOT re-run the full pipeline. Instead:
    1. Stores decisions as learned rules
    2. Applies corrections to current unmatched entries
    3. Re-runs only Checker + Reporter on updated results
    """
    from .agents.learning_agent import apply_corrections

    decisions = [d.model_dump() for d in request.decisions]
    result = apply_corrections(str(RULES_DIR), str(RESULTS_DIR), decisions)
    return result


@router.get("/api/download/{name}")
def download_result_file(name: str):
    """Serve a file from data/results/ for download.

    Constrained to known result files to prevent path traversal.
    """
    # Reject any path separator or parent-dir traversal attempts.
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="invalid filename")

    target = RESULTS_DIR / name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"{name} not found")
    if target.suffix.lower() not in ALLOWED_DOWNLOAD_EXTS:
        raise HTTPException(status_code=400, detail="unsupported file type")
    return FileResponse(path=target, filename=name)
