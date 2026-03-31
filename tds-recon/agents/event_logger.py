"""
Structured event logger for TDS Recon agents.
Captures agent activity as events that can be streamed to the UI.

Each event: {agent, type, message, timestamp, data}
Types: info, success, warning, error, progress, detail
"""

import threading
import time
from datetime import datetime


class EventLogger:
    def __init__(self):
        self.events = []
        self._start_time = time.time()
        self._on_event = None  # Callback for real-time streaming
        self._pending_questions = {}  # question_id -> {"event": threading.Event, "answer": None}

    def set_callback(self, callback):
        """Set a callback function called on every event emit."""
        self._on_event = callback

    def emit(self, agent: str, message: str, type: str = "info", data: dict | None = None):
        event = {
            "agent": agent,
            "type": type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": int((time.time() - self._start_time) * 1000),
        }
        if data:
            event.update(data)  # Merge data fields into top-level event
        self.events.append(event)
        # Also print for CLI usage
        prefix = {"success": "✓", "warning": "⚠", "error": "✗", "detail": "  ├─"}.get(type, "●")
        print(f"  {prefix} [{agent}] {message}")
        # Fire callback for real-time streaming
        if self._on_event:
            self._on_event(event)

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

    def agent_done(self, agent: str, message: str = "Done", **kwargs):
        self.emit(agent, message, "agent_done", kwargs.get("data"))

    def question(self, agent, question_id, question, options, allow_text_input=True, multi_select=False, timeout=300):
        """Emit a question and block until user answers. Returns the answer dict."""
        wait_event = threading.Event()
        self._pending_questions[question_id] = {"event": wait_event, "answer": None}

        self.emit(agent, question, "question", data={
            "question_id": question_id,
            "options": options,
            "allow_text_input": allow_text_input,
            "multi_select": multi_select,
        })

        # Block until answer received (or timeout)
        wait_event.wait(timeout=timeout)
        answer = self._pending_questions.pop(question_id, {}).get("answer")
        return answer

    def set_answer(self, question_id, answer):
        """Called by the API endpoint when user submits an answer."""
        if question_id in self._pending_questions:
            self._pending_questions[question_id]["answer"] = answer
            self._pending_questions[question_id]["event"].set()

    def get_events(self) -> list[dict]:
        return self.events

    def clear(self):
        self.events = []
        self._start_time = time.time()


# Global logger instance
_logger = EventLogger()


def get_logger() -> EventLogger:
    return _logger


def reset_logger() -> EventLogger:
    global _logger
    _logger = EventLogger()
    return _logger
