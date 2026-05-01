"""
Structured event logger for TDS Recon agents.
Captures agent activity as events that can be streamed to the UI.

Each event: {agent, type, message, timestamp, data}
Types: info, success, warning, error, progress, detail
"""

import time
from datetime import datetime


class EventLogger:
    def __init__(self):
        self.events = []
        self._start_time = time.time()

    def emit(self, agent: str, message: str, type: str = "info", data: dict | None = None):
        event = {
            "agent": agent,
            "type": type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "elapsed_ms": int((time.time() - self._start_time) * 1000),
        }
        if data:
            event["data"] = data
        self.events.append(event)
        # Also print for CLI usage
        prefix = {"success": "✓", "warning": "⚠", "error": "✗", "detail": "  ├─"}.get(type, "●")
        print(f"  {prefix} [{agent}] {message}")

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
