"""a1 — Orchestrator agent. The only agent the user talks to.

Drives the full pipeline:
  upload received  ->  invoke_column_reader  ->  (user confirms if b1 escalates)
  ->  invoke_tds_calculator  ->  (user resolves flags one at a time)
  ->  return_final_result

Only a1 has web_search. b1 and b2 cannot use it directly — they escalate
to a1, and a1 decides whether to research or ask the user.
"""

from .agent import run_orchestrator  # noqa: F401
