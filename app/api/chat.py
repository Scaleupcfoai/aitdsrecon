"""Chat router — conversational AI endpoint with SSE streaming."""

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies import get_db, get_current_user, UserContext
from app.db.repository import Repository
from app.agents.chat_agent import ChatAgent

router = APIRouter(tags=["chat"])

# In-memory chat sessions (per user). Production: move to DB.
_chat_sessions: dict[str, ChatAgent] = {}


class ChatMessage(BaseModel):
    message: str
    company_id: str = ""
    run_id: str = ""


@router.post("/chat")
def send_chat(
    msg: ChatMessage,
    db: Repository = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Send a message and get a complete response."""
    agent = _get_or_create_session(user, msg.company_id, msg.run_id, db)
    response = agent.chat(msg.message)
    return {"response": response}


@router.post("/chat/stream")
def stream_chat(
    msg: ChatMessage,
    db: Repository = Depends(get_db),
    user: UserContext = Depends(get_current_user),
):
    """Send a message and stream the response via SSE."""
    agent = _get_or_create_session(user, msg.company_id, msg.run_id, db)

    def generate():
        for chunk in agent.chat_stream(msg.message):
            yield f"data: {json.dumps({'type': 'chat_token', 'content': chunk})}\n\n"
        yield f"data: {json.dumps({'type': 'chat_done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.post("/chat/reset")
def reset_chat(user: UserContext = Depends(get_current_user)):
    """Clear conversation history."""
    session_key = user.user_id
    if session_key in _chat_sessions:
        _chat_sessions[session_key].reset_history()
    return {"status": "reset"}


def _get_or_create_session(user: UserContext, company_id: str, run_id: str,
                            db: Repository) -> ChatAgent:
    """Get existing chat session or create new one."""
    session_key = user.user_id
    if session_key not in _chat_sessions:
        _chat_sessions[session_key] = ChatAgent(
            db=db, firm_id=user.firm_id,
            company_id=company_id or "default",
            run_id=run_id or None,
        )
    else:
        # Update run_id if provided
        if run_id:
            _chat_sessions[session_key].run_id = run_id
        if company_id:
            _chat_sessions[session_key].company_id = company_id
    return _chat_sessions[session_key]
