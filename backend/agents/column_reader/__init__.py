"""b1 — Column Reader agent.

Responsibility: given an uploaded expense file, produce a canonical column
mapping (Date / Vendor / PAN / Amount / Description / PaymentMode).

Tools (deterministic):
  - fingerprint_columns(path)       headers + 5 samples per column
  - read_headers(path)              just headers
  - read_samples(path, n)           just the first N rows
  - ask_orchestrator(question, ...) escalate on genuine doubt (e.g. Amount
                                     column might be GST-inclusive)

The agent reasons between tool calls. It is responsible for its own
confidence: no external threshold. If the mapping is clear from fingerprint,
it emits the mapping immediately. If a column looks ambiguous, it escalates.
"""

from .agent import run_column_reader
from .prompt import SYSTEM_PROMPT

__all__ = ["run_column_reader", "SYSTEM_PROMPT"]
