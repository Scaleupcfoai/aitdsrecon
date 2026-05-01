"""b3 — Flag Resolver agent.

Sits between b2 (TDS Calculator) and the user. b2 returns flag groups; b3 turns
each group into a rich, ready-to-confirm proposal:
  - check_known_exemptions  deterministic KB lookup (telecom, utility, postal, ...)
  - research_descriptions   one batched Gemini-grounded call covering everything not in the KB
  - propose_resolutions     compose the final per-group proposal payload

Output goes to a1 (orchestrator). a1 uses surface_proposals_to_user to walk
the user through each proposal one at a time. b3 never asks the user directly.

Isolation: b3 is the only agent with access to exemptions KB + grounded research
in this domain. b2 stays a pure calculator. b1 stays a file reader.
"""

from .agent import run_flag_resolver  # noqa: F401
