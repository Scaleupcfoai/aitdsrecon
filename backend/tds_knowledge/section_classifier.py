"""Thin wrapper over expense_head_kb. Kept for backward compatibility.

The unified KB is the single source of truth. This module exposes the older
classify_expense_head() / SECTION_EXPENSE_MAP / AMBIGUOUS_EXPENSE_HEADS API
so existing callers keep working, but the data flows from expense_head_kb.
"""

from __future__ import annotations

from .expense_head_kb import KB_ENTRIES, lookup_kb

# Reverse-engineer keyword sets per section for the legacy SECTION_EXPENSE_MAP API.
SECTION_EXPENSE_MAP: dict[str, dict] = {}
for kw, rec in KB_ENTRIES:
    if rec.get("action") == "apply" and rec.get("section"):
        sec = rec["section"]
        SECTION_EXPENSE_MAP.setdefault(sec, {"keywords": set(), "description": ""})
        SECTION_EXPENSE_MAP[sec]["keywords"].add(kw)

AMBIGUOUS_EXPENSE_HEADS: dict[str, dict] = {}
for kw, rec in KB_ENTRIES:
    if rec.get("action") == "ask":
        AMBIGUOUS_EXPENSE_HEADS[kw] = {
            "likely_sections": [opt.split()[0] for opt in (rec.get("alt_options") or []) if opt.startswith("194")],
            "note": rec.get("rationale", ""),
        }


def classify_expense_head(description: str) -> list[str]:
    """Return likely TDS sections for a description.

    Backward-compatible API:
      - exact section name(s) for apply-actions
      - 'unknown' when KB has no hit
      - alt sections (parsed from options) for ask-actions
    """
    hit = lookup_kb(description)
    if not hit:
        return ["unknown"]
    if hit["action"] == "apply" and hit.get("section"):
        return [hit["section"]]
    if hit["action"] == "ask":
        sections = [opt.split()[0] for opt in (hit.get("alt_options") or []) if opt.startswith("194")]
        return sections or ["unknown"]
    # skip → caller treats as a different code path; legacy wants 'unknown'
    return ["unknown"]
