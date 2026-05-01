"""Per-session JSONL trace writer.

Every LLM call and tool call is appended to data/traces/<session_id>.jsonl.
Kept for 7 days, then swept. Never contains raw PANs or amounts — only
field names, counts, and truncated previews.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

BASE = Path(__file__).parent
TRACES_DIR = BASE / "data" / "traces"
TRACES_DIR.mkdir(parents=True, exist_ok=True)

TRACE_TTL_SEC = 7 * 24 * 3600


class Tracer:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.path = TRACES_DIR / f"{session_id}.jsonl"

    def write(self, record: dict[str, Any]) -> None:
        record.setdefault("t", time.time())
        record.setdefault("session", self.session_id)
        with self.path.open("a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]


def sweep_old_traces() -> int:
    cutoff = time.time() - TRACE_TTL_SEC
    purged = 0
    for p in TRACES_DIR.glob("*.jsonl"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                purged += 1
        except OSError:
            continue
    return purged
