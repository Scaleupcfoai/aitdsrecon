"""Session store with 24h TTL and runaway protection.

Layout:
  data/sessions/<session_id>.json   — single JSON blob per session
  data/traces/<session_id>.jsonl    — append-only trace (written by Tracer)
  data/uploads/<session_id>.<ext>   — the uploaded file

Kill switches (HARD STOP):
  - 24h TTL (measured from session create)
  - 20 LLM calls within a 120s sliding window -> RuntimeError
  - Any single subagent invocation exceeding 60s -> timeout

No background thread. TTL sweep runs opportunistically when sessions are touched.
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

BASE = Path(__file__).parent
SESSIONS_DIR = BASE / "data" / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

SESSION_TTL_SEC = 24 * 3600
# Tally uploads do a legitimate burst: b1 setup (8-10 turns) + b2 (2 turns) +
# a1 orchestration (4-6 turns) = ~20 turns before first user interaction.
# Bump to 40 to avoid false-positive kills; still catches true runaways.
RATE_LIMIT_CALLS = 40
RATE_LIMIT_WINDOW_SEC = 120
SUBAGENT_TIMEOUT_SEC = 60


class SessionKilled(RuntimeError):
    pass


class SessionExpired(RuntimeError):
    pass


@dataclass
class PendingEscalation:
    """A subagent is suspended waiting on an answer routed through the orchestrator."""
    kind: str                             # "ask_orchestrator" | "ask_user"
    from_agent: str                       # "column_reader" | "tds_calculator"
    payload: dict[str, Any]
    chat_history: list[dict[str, Any]]    # subagent history to resume with
    created_at: float = field(default_factory=time.time)


@dataclass
class Session:
    id: str
    created_at: float
    updated_at: float
    user_email: str | None = None                     # owner — set on upload, checked on read
    file_path: str | None = None
    column_mapping: dict[str, str] | None = None      # flat-file b1 output
    extracted_rows: list[dict[str, Any]] | None = None  # Tally b1 output (pre-extracted rows)
    pan_policy: str | None = None                     # 'apply_206aa' | 'assume_pan' for Tally files
    tds_results: dict[str, Any] | None = None         # b2's output: {results, flags, aggregates, diagnostics}
    pending_proposals: list[dict[str, Any]] | None = None   # b3's enriched flag proposals awaiting user
    proposal_answers: list[dict[str, Any]] | None = None    # user's per-proposal selections
    orchestrator_history: list[dict[str, Any]] = field(default_factory=list)
    pending_escalation: PendingEscalation | None = None
    pending_user_question: dict[str, Any] | None = None
    llm_call_timestamps: list[float] = field(default_factory=list)
    completed: bool = False
    killed_reason: str | None = None
    final_result: dict[str, Any] | None = None

    def path(self) -> Path:
        return SESSIONS_DIR / f"{self.id}.json"

    def save(self) -> None:
        self.updated_at = time.time()
        data = asdict(self)
        if self.pending_escalation is not None:
            data["pending_escalation"] = asdict(self.pending_escalation)
        self.path().write_text(json.dumps(data, default=str))

    def record_llm_call(self) -> None:
        """Append a timestamp and enforce the sliding-window rate limit."""
        now = time.time()
        self.llm_call_timestamps.append(now)
        # Drop entries outside the window.
        cutoff = now - RATE_LIMIT_WINDOW_SEC
        self.llm_call_timestamps = [t for t in self.llm_call_timestamps if t >= cutoff]
        if len(self.llm_call_timestamps) >= RATE_LIMIT_CALLS:
            self.killed_reason = (
                f"rate_limit: {RATE_LIMIT_CALLS} LLM calls in <{RATE_LIMIT_WINDOW_SEC}s"
            )
            self.save()
            raise SessionKilled(self.killed_reason)

    def assert_alive(self) -> None:
        if self.killed_reason:
            raise SessionKilled(self.killed_reason)
        if time.time() - self.created_at > SESSION_TTL_SEC:
            self.killed_reason = "ttl_expired"
            self.save()
            raise SessionExpired("session expired after 24h")

    def assert_owner(self, user_email: str) -> None:
        """Raise PermissionError if user_email doesn't match the session owner.

        Owner is set on upload. Older sessions without an owner are treated as
        unowned (any authenticated user can access). Once ENV=production we
        should tighten this to strict ownership.
        """
        if self.user_email and self.user_email != user_email:
            raise PermissionError("session belongs to a different user")


def create_session() -> Session:
    now = time.time()
    s = Session(id=uuid.uuid4().hex, created_at=now, updated_at=now)
    s.save()
    return s


def load_session(session_id: str) -> Session:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise KeyError(f"session not found: {session_id}")
    data = json.loads(path.read_text())
    pending = data.pop("pending_escalation", None)
    s = Session(**data)
    if pending:
        s.pending_escalation = PendingEscalation(**pending)
    s.assert_alive()
    return s


def sweep_expired() -> int:
    """Delete session files older than TTL. Returns count purged."""
    cutoff = time.time() - SESSION_TTL_SEC
    purged = 0
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            if data.get("created_at", 0) < cutoff:
                p.unlink()
                purged += 1
        except (json.JSONDecodeError, OSError):
            continue
    return purged
