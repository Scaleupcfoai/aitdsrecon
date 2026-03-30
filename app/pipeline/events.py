"""
EventEmitter — scoped per reconciliation run.

Replaces the global singleton EventLogger from the MVP.
Each pipeline run gets its own emitter with its own event list.
Events can be streamed to UI via SSE callback.

Usage:
    emitter = EventEmitter(run_id="abc-123")
    emitter.agent_start("Parser Agent", "Starting...")
    emitter.detail("Parser Agent", "Found 85 entries")
    emitter.agent_done("Parser Agent", "Complete")
"""

import time
from datetime import datetime


class EventEmitter:
    """Emits structured events for a single pipeline run.

    Not global — each run_pipeline() call creates a new one.
    Optionally calls a callback on every event (for SSE streaming).
    """

    def __init__(self, run_id: str = "", callback=None):
        self.run_id = run_id
        self.events = []
        self._start_time = time.time()
        self._callback = callback  # called on every emit (for SSE)

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
        prefix = {"success": "✓", "warning": "⚠", "error": "✗", "detail": "  ├─"}.get(event_type, "●")
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

    def get_events(self) -> list[dict]:
        return self.events
