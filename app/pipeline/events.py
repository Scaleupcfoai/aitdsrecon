"""
EventEmitter — scoped per reconciliation run.

Replaces the global singleton EventLogger from the MVP.
Each pipeline run gets its own emitter with its own event list.
Events can be streamed to UI via SSE callback.

Event types for frontend rendering:
- agent_start: Agent begins work → show agent header with spinner
- agent_done: Agent complete → show checkmark, elapsed time
- info: General status → show as log line
- detail: Sub-step detail → show indented under agent
- success: Positive result → show with green checkmark
- warning: Non-critical issue → show with yellow warning
- error: Critical issue → show with red X
- llm_call: LLM is being called → show "💭 Asking LLM..." with preview
- llm_response: LLM responded → show response time + token count
- llm_insight: LLM produced a user-visible insight → show prominently in chat
- human_needed: Decision requires human review → show with action button
- pipeline_complete: All agents done → show final summary

Usage:
    emitter = EventEmitter(run_id="abc-123")
    emitter.agent_start("Parser Agent", "Starting...")
    emitter.detail("Parser Agent", "Found 85 entries")
    emitter.agent_done("Parser Agent", "Complete")
"""

import time
from datetime import datetime


# All valid event types — frontend uses these to decide rendering
EVENT_TYPES = {
    "agent_start",    # Agent header with spinner
    "agent_done",     # Agent complete with checkmark
    "info",           # General log line
    "detail",         # Indented sub-step
    "success",        # Green checkmark result
    "warning",        # Yellow warning
    "error",          # Red error
    "llm_call",       # "💭 Asking LLM..." — shows model + prompt preview
    "llm_response",   # "LLM responded" — shows timing + tokens
    "llm_insight",    # User-visible insight from LLM — rendered prominently
    "human_needed",   # Needs human decision — rendered with action button
    "pipeline_complete",  # Final event with summary
    "question",           # Pipeline needs user input — renders with options
}


# Pending answers — shared between SSE thread and answer endpoint
_pending_answers: dict[str, dict | None] = {}


class EventEmitter:
    """Emits structured events for a single pipeline run."""

    def __init__(self, run_id: str = "", callback=None):
        self.run_id = run_id
        self.events = []
        self._start_time = time.time()
        self._callback = callback

    def emit(self, agent: str, message: str, event_type: str = "info", data: dict | None = None):
        event = {
            "run_id": self.run_id,
            "agent": agent,
            "type": event_type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": int((time.time() - self._start_time) * 1000),
        }
        if data:
            event["data"] = data
        self.events.append(event)

        # Print for CLI/logs
        prefix = {
            "success": "✓", "warning": "⚠", "error": "✗",
            "detail": "  ├─", "llm_call": "  💭", "llm_response": "  ✦",
            "llm_insight": "  🔍", "human_needed": "  👤",
        }.get(event_type, "●")
        print(f"  {prefix} [{agent}] {message}")

        # Fire callback for SSE streaming
        if self._callback:
            self._callback(event)

    def info(self, agent: str, message: str, **kwargs):
        self.emit(agent, message, "info", kwargs.get("data"))

    def success(self, agent: str, message: str, **kwargs):
        self.emit(agent, message, "success", kwargs.get("data"))

    def detail(self, agent: str, message: str, **kwargs):
        self.emit(agent, message, "detail", kwargs.get("data"))

    def warning(self, agent: str, message: str, **kwargs):
        self.emit(agent, message, "warning", kwargs.get("data"))

    def error(self, agent: str, message: str, **kwargs):
        self.emit(agent, message, "error", kwargs.get("data"))

    def agent_start(self, agent: str, message: str = "Starting..."):
        self.emit(agent, message, "agent_start")

    def agent_done(self, agent: str, message: str = "Done"):
        self.emit(agent, message, "agent_done")

    def question(
        self,
        agent: str,
        message: str,
        question_id: str,
        options: list[dict],
        allow_text_input: bool = True,
        multi_select: bool = False,
        timeout_seconds: int = 300,
    ) -> dict | None:
        """Emit a question event and block until the user answers.

        Args:
            agent: which agent is asking
            message: question text
            question_id: unique ID for this question
            options: [{id, label, description}, ...]
            allow_text_input: allow free text answer
            multi_select: allow multiple selections
            timeout_seconds: how long to wait (default 300s = 5 minutes)

        Returns:
            User's answer: {selected: [ids], text_input: str | None}
            or None if timeout
        """
        self.emit(agent, message, "question", {
            "question_id": question_id,
            "options": options,
            "allow_text_input": allow_text_input,
            "multi_select": multi_select,
        })

        # Block and wait for answer
        _pending_answers[question_id] = None

        import time
        polls = timeout_seconds * 2  # 0.5s per poll
        for _ in range(polls):
            if _pending_answers.get(question_id) is not None:
                answer = _pending_answers.pop(question_id)
                self.emit(agent, f"User answered: {answer.get('selected', [])}", "info")
                return answer
            time.sleep(0.5)

        # Timeout
        _pending_answers.pop(question_id, None)
        self.emit(agent, "Question timed out — using default action", "warning")
        return None

    @staticmethod
    def set_answer(question_id: str, answer: dict):
        """Set the answer for a pending question (called from API endpoint)."""
        _pending_answers[question_id] = answer

    def get_events(self) -> list[dict]:
        return self.events
