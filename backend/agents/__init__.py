"""Three-agent architecture.

  orchestrator (a1)  <->  user (via FastAPI)
       |
       +---- column_reader (b1) — fingerprint + mapping
       |
       +---- tds_calculator (b2) — batch TDS + flag resolution

Isolation:
  - column_reader never imports from tds_calculator and vice versa.
  - Only orchestrator imports both.
  - Each agent's runtime only executes tools from its own tools.py registry.
"""
