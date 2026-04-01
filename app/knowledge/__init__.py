"""
Knowledge Base Loader — reads tds_rules.json and provides it to agents + LLM prompts.

Single source of truth for all TDS rules. Every agent reads from here.
Update tds_rules.json when Budget amendments happen — all agents update automatically.

Usage:
    from app.knowledge.loader import knowledge, get_section_rate, get_threshold, get_llm_context

    # Get a specific rate
    rate = get_section_rate("194C", "company")  # returns 2.0

    # Get threshold
    threshold = get_threshold("194A")  # returns {"aggregate_annual": 5000, ...}

    # Get LLM-ready context (injected into every prompt)
    context = get_llm_context()  # returns formatted string with all rules
"""

import json
from functools import lru_cache
from pathlib import Path


KNOWLEDGE_PATH = Path(__file__).parent / "tds_rules.json"


@lru_cache()
def _load_knowledge() -> dict:
    """Load the knowledge base (cached — loaded once)."""
    with open(KNOWLEDGE_PATH) as f:
        return json.load(f)


def knowledge() -> dict:
    """Get the full knowledge base dict."""
    return _load_knowledge()


def get_sections() -> dict:
    """Get all TDS sections with their rules."""
    return knowledge()["sections"]


def get_section(section_code: str) -> dict | None:
    """Get rules for a specific section. Handles 194I(a) → 194I_a format."""
    sections = get_sections()
    # Try exact match first
    if section_code in sections:
        return sections[section_code]
    # Try with parentheses → underscore conversion
    normalized = section_code.replace("(", "_").replace(")", "")
    if normalized in sections:
        return sections[normalized]
    return None


def get_section_rate(section_code: str, entity_type: str = "default") -> float | None:
    """Get TDS rate for a section + entity type.

    Args:
        section_code: e.g. "194C", "194J(b)"
        entity_type: "individual_huf", "company", "firm", "default"

    Returns rate as float (e.g. 2.0 for 2%), or None if not found.
    """
    section = get_section(section_code)
    if not section:
        return None
    rate = section.get("rate", {})
    if isinstance(rate, dict):
        return rate.get(entity_type, rate.get("default"))
    return None


def get_threshold(section_code: str) -> dict | None:
    """Get threshold for a section."""
    section = get_section(section_code)
    if not section:
        return None
    return section.get("threshold")


def get_expense_keywords(section_code: str) -> list[str]:
    """Get expense keywords for a section (for matching expenses to sections)."""
    section = get_section(section_code)
    if not section:
        return []
    return section.get("expense_keywords", [])


def get_penalties() -> dict:
    """Get all penalty provisions."""
    return knowledge()["penalties"]


def get_due_dates() -> dict:
    """Get all due dates."""
    return knowledge()["due_dates"]


def get_ambiguous_expenses() -> dict:
    """Get ambiguous expense classification guide."""
    return knowledge()["ambiguous_expenses"]


def get_entity_type(pan: str) -> str:
    """Derive entity type from PAN 4th character."""
    if not pan or len(pan) < 4:
        return "unknown"
    fourth = pan[3].upper()
    entities = knowledge()["entity_types"]
    for code, info in entities.items():
        if info["pan_4th_char"] == fourth:
            return info["type"]
    return "unknown"


# ═══════════════════════════════════════════════════════════
# LLM Context — formatted string injected into every prompt
# ═══════════════════════════════════════════════════════════

@lru_cache()
def get_llm_context() -> str:
    """Get formatted TDS knowledge for injection into LLM prompts.

    This is the key function — every LLM call includes this context.
    The LLM is instructed to use ONLY this data, not training data.
    """
    kb = knowledge()
    lines = []

    lines.append("## TDS RULES (Verified Source — Income Tax Act 1961, Finance Act 2025)")
    lines.append("")

    # Sections with rates and thresholds
    lines.append("### TDS Sections, Rates, and Thresholds")
    for code, section in kb["sections"].items():
        display_code = code.replace("_", "(").rstrip("ab") + ")" if "_" in code else code
        # Fix: 194I_a → 194I(a), 194J_b → 194J(b)
        if "_a" in code:
            display_code = code.replace("_a", "(a)")
        elif "_b" in code:
            display_code = code.replace("_b", "(b)")

        rate = section.get("rate", {})
        if isinstance(rate, dict) and not rate.get("slab"):
            rate_str = f"{rate.get('default', 'varies')}%"
            if rate.get("individual_huf") != rate.get("company"):
                rate_str = f"{rate.get('individual_huf', '?')}% (individual/HUF), {rate.get('company', '?')}% (company)"
        elif isinstance(rate, dict) and rate.get("slab"):
            rate_str = "As per income tax slab"
        else:
            rate_str = str(rate)

        threshold = section.get("threshold", {})
        thresh_str = threshold.get("description", "No threshold") if isinstance(threshold, dict) else "No threshold"

        lines.append(f"- **{display_code}: {section['name']}** — Rate: {rate_str} | Threshold: {thresh_str}")

    lines.append("")

    # Penalties
    lines.append("### Penalties for Non-Compliance")
    for code, penalty in kb["penalties"].items():
        lines.append(f"- **Section {penalty['section']}** ({penalty['name']}): {penalty.get('rate', penalty.get('range', ''))}")
        if penalty.get("notes"):
            lines.append(f"  Note: {penalty['notes']}")

    lines.append("")

    # Due dates
    lines.append("### Due Dates")
    deposit = kb["due_dates"]["deposit"]
    lines.append(f"- TDS Deposit: {deposit['general']} (March: {deposit['march']})")
    for q, info in kb["due_dates"]["return_filing"].items():
        lines.append(f"- {q} ({info['period']}): Return due by {info['due_date']}")

    lines.append("")

    # Ambiguous expenses
    lines.append("### Ambiguous Expense Classification")
    for expense, guide in kb["ambiguous_expenses"].items():
        lines.append(f"- **{expense.title()}**: {guide['classification_guide']}")

    return "\n".join(lines)


# Build keyword → section mapping from knowledge base
@lru_cache()
def get_expense_to_section_map() -> dict[str, str]:
    """Build a keyword → TDS section mapping from the knowledge base.

    Returns: {"freight": "194C", "interest": "194A", ...}
    """
    mapping = {}
    for code, section in get_sections().items():
        # Convert 194I_a → 194I(a)
        display_code = code
        if "_a" in code:
            display_code = code.replace("_a", "(a)")
        elif "_b" in code:
            display_code = code.replace("_b", "(b)")

        for keyword in section.get("expense_keywords", []):
            mapping[keyword.lower()] = display_code
    return mapping
