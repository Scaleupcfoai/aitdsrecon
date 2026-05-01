"""Backward-compat wrapper. The real KB is in expense_head_kb.py.

Kept so existing imports (`from tds_knowledge.exemptions import lookup_exemption`)
continue to work without churn.
"""

from .expense_head_kb import lookup_kb as lookup_exemption  # noqa: F401
