"""
Shared utilities for matching agents.

Pure functions — no database, no file I/O. Used by Matcher and other agents.
Preserved from MVP (tds-recon/agents/matcher_agent.py).
"""

import re
from datetime import datetime

# Amount tolerance for fuzzy matching
FUZZY_AMOUNT_TOLERANCE = 0.005  # 0.5%
FUZZY_DATE_DAYS = 30
GST_RATES = [0.18, 0.12, 0.05, 0.28]


def parse_date(d) -> datetime | None:
    """Parse date from ISO string or datetime object."""
    if isinstance(d, datetime):
        return d
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d)
        except ValueError:
            return None
    return None


def normalize_name(name: str) -> str:
    """Normalize vendor name: lowercase, strip suffixes, remove IDs."""
    if not name:
        return ""
    n = name.lower().strip()
    for suffix in ["pvt. ltd.", "pvt ltd", "private limited", "ltd.", "ltd",
                   "llp", "lp", "inc.", "inc", "co.", "company"]:
        n = n.replace(suffix, "")
    n = re.sub(r"\(\d+\)", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def name_similarity(a: str, b: str) -> float:
    """Token-overlap similarity between two names."""
    tokens_a = set(normalize_name(a).split())
    tokens_b = set(normalize_name(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / min(len(tokens_a), len(tokens_b))


def amount_close(a: float, b: float, tolerance: float = FUZZY_AMOUNT_TOLERANCE) -> bool:
    """Check if two amounts are within tolerance (default 0.5%)."""
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tolerance


def get_month_key(d) -> str:
    """Get YYYY-MM key from a date for monthly grouping."""
    dt = parse_date(d)
    return dt.strftime("%Y-%m") if dt else ""
