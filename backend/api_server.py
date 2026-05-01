"""Lekha TDS Calculator — FastAPI backend.

Run: uvicorn api_server:app --reload --port 8000

Endpoints:
  GET  /api/health
  POST /api/session/upload                 create session + upload file + kick off a1
  POST /api/session/{session_id}/answer    user answers a pending ask_user, a1 resumes
  GET  /api/session/{session_id}           current session state
  GET  /api/session/{session_id}/stream    SSE trace stream (for live activity UI)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

from auth import get_session_secret, require_user, router as auth_router  # noqa: E402

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

app = FastAPI(title="Lekha TDS Calculator API", version="0.3.0")

# SessionMiddleware must be added BEFORE CORS so it wraps inside.
app.add_middleware(
    SessionMiddleware,
    secret_key=get_session_secret(),
    session_cookie="lekha_session",
    same_site="lax",
    https_only=os.getenv("ENV", "development") == "production",
    max_age=24 * 3600,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


@app.get("/api/health")
def health() -> dict[str, Any]:
    from llm_client import is_configured
    return {
        "status": "ok",
        "service": "lekha-tds-calculator",
        "version": "0.2.0",
        "llm_configured": is_configured(),
    }


# ─── Orchestrator lifecycle ──────────────────────────────────────────────

def _was_called(history: list[dict[str, Any]], tool_name: str) -> bool:
    """Did any model turn call this tool?"""
    for msg in history or []:
        if msg.get("role") != "model":
            continue
        for part in msg.get("parts", []):
            fc = (part or {}).get("function_call") or {}
            if fc.get("name") == tool_name:
                return True
    return False


async def _run_orchestrator_task(session_id: str, initial_task: str) -> None:
    """Run a1's loop in the background. Persists state after each turn."""
    from agent_runtime import MaxStepsExceeded
    from agents.orchestrator import run_orchestrator
    from session import SessionKilled, SessionExpired, load_session
    from tracing import Tracer

    tracer = Tracer(session_id)
    try:
        session = load_session(session_id)
        session.record_llm_call()  # pre-check before the burst
        result = await run_orchestrator(
            task=initial_task,
            tracer=tracer,
            session_id=session_id,
            initial_history=session.orchestrator_history or None,
        )
        session = load_session(session_id)          # reload in case tools mutated it
        session.orchestrator_history = result.chat_history

        if result.escalation and result.escalation.kind == "ask_user":
            session.pending_user_question = result.escalation.payload
            tracer.write({"event": "awaiting_user", "payload": result.escalation.payload})
        elif result.escalation and result.escalation.kind == "proposal_review":
            # b3 already wrote pending_proposals to the session. Surface to UI.
            tracer.write({
                "event": "awaiting_proposal_review",
                "proposal_count": len(session.pending_proposals or []),
            })
        elif result.final_text is not None:
            # Defensive: a1 must call return_final_result before exiting. If we
            # see final text but no return_final_result call in history, Gemini
            # bailed out with a chat-style reply instead of using its tools.
            # Don't mark completed — the user would see a confusing 404 on
            # /results because tds_results may not be populated.
            called_finaliser = _was_called(result.chat_history, "return_final_result")
            if called_finaliser:
                session.completed = True
                session.final_result = {"text": result.final_text}
                tracer.write({"event": "orchestrator_done", "text": result.final_text})
            else:
                session.killed_reason = "orchestrator_emitted_text_without_finalising"
                tracer.write({
                    "event": "orchestrator_error",
                    "error": "Orchestrator emitted text without calling return_final_result. "
                             "Gemini chose to chat instead of using tools. Re-upload to retry.",
                    "text_preview": (result.final_text or "")[:300],
                })

        session.save()
    except (SessionKilled, SessionExpired) as e:
        tracer.write({"event": "session_killed", "reason": str(e)})
    except MaxStepsExceeded as e:
        tracer.write({"event": "max_steps_exceeded", "error": str(e)})
    except Exception as e:  # noqa: BLE001 — catch-all for trace capture
        tracer.write({"event": "orchestrator_error", "error": f"{type(e).__name__}: {e}"})


# ─── Upload + session create ─────────────────────────────────────────────

class UploadResponse(BaseModel):
    session_id: str
    filename: str
    size_bytes: int


@app.post("/api/session/upload", response_model=UploadResponse)
async def upload_and_start(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_user),
) -> UploadResponse:
    from session import create_session

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    contents = await file.read()
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    session = create_session()
    session.user_email = user["email"]
    stored_path = UPLOAD_DIR / f"{session.id}{ext}"
    stored_path.write_bytes(contents)
    session.file_path = str(stored_path)
    session.save()

    initial_task = (
        f"User uploaded an expense file at {stored_path}. "
        "Run the pipeline: start by invoking column_reader."
    )
    background.add_task(_run_orchestrator_task, session.id, initial_task)

    return UploadResponse(
        session_id=session.id,
        filename=file.filename or "",
        size_bytes=len(contents),
    )


# ─── Answer pending question ─────────────────────────────────────────────

class AnswerRequest(BaseModel):
    answer: str
    option_id: str | None = None


@app.post("/api/session/{session_id}/answer")
async def answer_question(
    session_id: str,
    req: AnswerRequest,
    background: BackgroundTasks,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    from agent_runtime import EscalationRequest
    from session import load_session

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    if not session.pending_user_question:
        raise HTTPException(status_code=409, detail="No question awaiting an answer")

    # Inject the answer as a tool_result for a1's last ask_user call.
    answer_payload = {
        "answer": req.answer,
        "option_id": req.option_id,
        "answered_at": time.time(),
    }
    session.orchestrator_history.append({
        "role": "user",
        "parts": [{"function_response": {"name": "ask_user", "response": answer_payload}}],
    })
    session.pending_user_question = None
    session.save()

    # Resume a1 in the background.
    background.add_task(
        _run_orchestrator_task,
        session_id,
        "Continue where you left off.",
    )
    return {"status": "resumed"}


# ─── Session state + SSE stream ──────────────────────────────────────────

@app.get("/api/session/{session_id}")
def get_session(
    session_id: str,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    from session import load_session

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    return {
        "id": session.id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "completed": session.completed,
        "killed_reason": session.killed_reason,
        "column_mapping": session.column_mapping,
        "pending_user_question": session.pending_user_question,
        "final_result": session.final_result,
        "has_tds_results": session.tds_results is not None,
    }


# ─── Proposal review (b3 flow) ─────────────────────────────────────────────

@app.get("/api/session/{session_id}/proposals")
def get_proposals(
    session_id: str,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Frontend reads the pending proposal list to drive the popup loop locally."""
    from session import load_session

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    return {
        "proposals": session.pending_proposals or [],
        "answers_so_far": session.proposal_answers or [],
        "total": len(session.pending_proposals or []),
    }


class ProposalAnswer(BaseModel):
    proposal_index: int
    answer: dict[str, Any]   # {section?, skip_reason?, free_text?, note?, row_ids?}


@app.post("/api/session/{session_id}/proposal/answer")
async def submit_proposal_answer(
    session_id: str,
    req: ProposalAnswer,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Record one user answer. Does NOT resume a1 — that happens on /complete."""
    from session import load_session

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    answers = list(session.proposal_answers or [])
    # Pad to the requested index in case the user skipped ahead.
    while len(answers) <= req.proposal_index:
        answers.append({})
    answers[req.proposal_index] = req.answer
    session.proposal_answers = answers
    session.save()
    return {"recorded": req.proposal_index, "total_answers": len(answers)}


@app.post("/api/session/{session_id}/proposal/complete")
async def complete_proposal_review(
    session_id: str,
    background: BackgroundTasks,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Frontend signals all proposals are answered. Resume a1 with the answers."""
    from session import load_session

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    if not session.pending_proposals:
        raise HTTPException(status_code=409, detail="no pending proposals")

    answers = list(session.proposal_answers or [])
    proposals = session.pending_proposals or []
    # Stitch row_ids into each answer if the frontend didn't.
    enriched = []
    for i, p in enumerate(proposals):
        a = answers[i] if i < len(answers) else {}
        enriched.append({**a, "row_ids": a.get("row_ids") or p.get("row_ids", [])})

    # Inject the answer list as the function_response for surface_proposals_to_user.
    session.orchestrator_history.append({
        "role": "user",
        "parts": [{"function_response": {
            "name": "surface_proposals_to_user",
            "response": {"answers": enriched, "count": len(enriched)},
        }}],
    })
    session.pending_proposals = None
    session.proposal_answers = None
    session.save()

    background.add_task(_run_orchestrator_task, session_id, "Continue with the user's answers.")
    return {"status": "resumed", "answer_count": len(enriched)}


@app.get("/api/session/{session_id}/results")
def get_results(
    session_id: str,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Full TDS results + three aggregated views (Party / Section / Quarter)."""
    from reports import build_views
    from session import load_session

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    if not session.tds_results:
        raise HTTPException(status_code=404, detail="no tds_results yet")
    views = build_views(session.tds_results)
    return {
        "mapping": session.column_mapping,
        "results": session.tds_results.get("results", []),
        "flags": session.tds_results.get("flags", []),
        "diagnostics": session.tds_results.get("diagnostics", {}),
        **views,
    }


@app.get("/api/session/{session_id}/report.xlsx")
def download_report(
    session_id: str,
    user: dict[str, Any] = Depends(require_user),
) -> Response:
    """Download the branded 5-sheet Excel report for this session."""
    from excel_report import generate_report
    from session import load_session

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    if not session.tds_results:
        raise HTTPException(status_code=404, detail="no tds_results yet")
    data = generate_report(session.tds_results)
    filename = f"lekha-tds-{session_id[:8]}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/session/{session_id}/stream")
async def stream_trace(
    session_id: str,
    user: dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    """Tail the JSONL trace and push each new line as an SSE event.

    Client reconnects on EOF; we don't try to be clever about keepalives.
    """
    from session import load_session
    from tracing import Tracer

    session = load_session(session_id)
    try:
        session.assert_owner(user["email"])
    except PermissionError:
        raise HTTPException(status_code=403, detail="not your session")
    tracer = Tracer(session_id)

    async def gen():
        offset = 0
        idle_count = 0
        while True:
            if not tracer.path.exists():
                await asyncio.sleep(0.25)
                continue
            with tracer.path.open() as f:
                f.seek(offset)
                new_lines = f.readlines()
                offset = f.tell()
            if new_lines:
                idle_count = 0
                for line in new_lines:
                    if line.strip():
                        yield f"data: {line.strip()}\n\n"
            else:
                idle_count += 1
                if idle_count > 240:  # ~60s of idleness
                    yield 'data: {"event":"idle_timeout"}\n\n'
                    return
            await asyncio.sleep(0.25)

    return StreamingResponse(gen(), media_type="text/event-stream")
