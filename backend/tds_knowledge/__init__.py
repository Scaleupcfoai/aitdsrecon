"""TDS knowledge base — rates, thresholds, section classification, PAN utilities.

Sourced from aitdsrecon/tds-recon/agents/tds_checker_agent.py. Kept as a
self-contained module so the calculator doesn't cross-import from the recon repo.
"""

from .rates import TDS_RATES, expected_rate, entity_type_from_pan
from .thresholds import TDS_THRESHOLDS, get_deposit_due_date
from .section_classifier import (
    SECTION_EXPENSE_MAP,
    AMBIGUOUS_EXPENSE_HEADS,
    classify_expense_head,
)
from .pan_utils import is_valid_pan, normalize_name

__all__ = [
    "TDS_RATES",
    "TDS_THRESHOLDS",
    "SECTION_EXPENSE_MAP",
    "AMBIGUOUS_EXPENSE_HEADS",
    "expected_rate",
    "entity_type_from_pan",
    "get_deposit_due_date",
    "classify_expense_head",
    "is_valid_pan",
    "normalize_name",
]
