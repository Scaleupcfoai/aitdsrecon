"""b2 — TDS Calculator agent.

Responsibility: given uploaded file + column mapping, compute TDS per row and
return (results + flags). Does NOT resolve flags — that's a1's job.

Tools:
  - calculate_batch               deterministic whole-file pass (primary)
  - lookup_rate / classify_section / check_threshold / apply_206aa  (drill-down)
  - ask_orchestrator              mid-loop escalation (rare)
"""

from .agent import run_tds_calculator  # noqa: F401
from .core import calculate_batch      # noqa: F401
