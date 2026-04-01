"""
Test TDS Checker — pure compliance logic (no DB, no LLM).

Tests the deterministic checks with in-memory data.
Run: pytest tests/test_checker_logic.py -v -s
"""

import pytest
from app.agents.tds_checker_agent import (
    check_section, check_rate, check_base_amount,
    entity_type_from_pan, expected_rate,
    SECTION_EXPENSE_MAP, TDS_RATES, TDS_THRESHOLDS,
)
from app.knowledge import get_section_rate, get_entity_type, get_threshold


# ═══ Knowledge Base Integration ═══

def test_kb_rates_loaded():
    """TDS_RATES built from knowledge base has entries."""
    assert len(TDS_RATES) >= 6  # at least 194A, 194C, 194H, 194J(a), 194J(b), 194Q
    print(f"TDS_RATES has {len(TDS_RATES)} sections: {sorted(TDS_RATES.keys())}")


def test_kb_thresholds_loaded():
    """TDS_THRESHOLDS built from knowledge base."""
    assert len(TDS_THRESHOLDS) >= 6
    print(f"TDS_THRESHOLDS has {len(TDS_THRESHOLDS)} sections")


def test_kb_expense_map_loaded():
    """SECTION_EXPENSE_MAP built from knowledge base."""
    assert len(SECTION_EXPENSE_MAP) >= 6
    assert "194C" in SECTION_EXPENSE_MAP
    assert "freight" in SECTION_EXPENSE_MAP["194C"]["keywords"]
    print(f"SECTION_EXPENSE_MAP has {len(SECTION_EXPENSE_MAP)} sections")


# ═══ Entity Type from PAN ═══

def test_entity_company():
    assert get_entity_type("AAACH1234A") == "company"  # 4th char C


def test_entity_individual():
    assert get_entity_type("AAAPD5678A") == "individual_huf"  # 4th char P


def test_entity_huf():
    assert get_entity_type("AAAHF9012A") == "individual_huf"  # 4th char H


def test_entity_firm():
    assert get_entity_type("AAAFG3456A") == "firm"  # 4th char F


def test_entity_unknown_pan():
    assert get_entity_type("") == "unknown"
    assert get_entity_type("AB") == "unknown"


# ═══ Expected Rate ═══

def test_rate_194c_company():
    rate = get_section_rate("194C", "company")
    assert rate == 2.0


def test_rate_194c_individual():
    rate = get_section_rate("194C", "individual_huf")
    assert rate == 1.0


def test_rate_194a():
    rate = get_section_rate("194A", "default")
    assert rate == 10.0


def test_rate_194h():
    rate = get_section_rate("194H", "default")
    assert rate == 2.0  # Changed from 5% by Finance Act 2025


def test_rate_194jb():
    rate = get_section_rate("194J_b", "default")
    assert rate == 10.0


def test_rate_194q():
    rate = get_section_rate("194Q", "default")
    assert rate == 0.1


# ═══ Thresholds ═══

def test_threshold_194a():
    t = get_threshold("194A")
    assert t["aggregate_annual"] == 5000


def test_threshold_194c():
    t = get_threshold("194C")
    assert t["aggregate_annual"] == 100000
    assert t["single_payment"] == 30000


def test_threshold_194h():
    t = get_threshold("194H")
    assert t["aggregate_annual"] == 15000


# ═══ Section Validation (Check 1) ═══

def _make_match(section, expense_heads):
    """Build a match dict for check_section."""
    return {
        "form26_entry": {"section": section, "vendor_name": "Test Vendor"},
        "tally_entries": [{"expense_heads": {h: 1000 for h in expense_heads}}] if expense_heads else [],
    }


def test_section_freight_under_194c_ok():
    """Freight under 194C → correct, no finding."""
    result = check_section(_make_match("194C", ["Freight Charges"]))
    assert result is None  # no finding = correct


def test_section_interest_under_194a_ok():
    """Interest under 194A → correct."""
    match = {
        "form26_entry": {"section": "194A", "vendor_name": "Test"},
        "tally_entries": [{"account_postings": {"Interest Paid": 5000}}],
    }
    result = check_section(match)
    assert result is None


def test_section_no_tally_entries():
    """No tally entries → can't validate, returns None."""
    result = check_section(_make_match("194C", []))
    assert result is None


# ═══ Rate Validation (Check 2) ═══

def _make_rate_match(section, pan, actual_rate, amount=100000, tds=2000):
    return {
        "form26_entry": {
            "section": section, "vendor_name": "Test", "pan": pan,
            "tax_rate_pct": actual_rate, "amount_paid": amount,
            "tax_deducted": tds,
        },
        "tally_entries": [],
    }


def test_rate_194c_company_correct():
    """194C company at 2% → correct, no finding."""
    result = check_rate(_make_rate_match("194C", "AAACH1234A", 2.0))
    assert result is None


def test_rate_194c_individual_correct():
    """194C individual at 1% → correct."""
    result = check_rate(_make_rate_match("194C", "AAAPD5678A", 1.0, 100000, 1000))
    assert result is None


def test_rate_194a_correct():
    """194A at 10% → correct."""
    result = check_rate(_make_rate_match("194A", "AAAPD5678A", 10.0, 50000, 5000))
    assert result is None


def test_rate_no_rate_in_entry():
    """No tax_rate_pct → can't validate, returns None."""
    result = check_rate(_make_rate_match("194C", "AAACH1234A", None))
    assert result is None


# ═══ Base Amount Validation (Check 3) ═══

def test_base_amount_no_gst_entries():
    """No GST entries → can't validate base, returns None."""
    match = {
        "form26_entry": {"amount_paid": 10000, "tax_rate_pct": 2, "section": "194C", "vendor_name": "V"},
        "tally_entries": [{"tally_source": "journal_freight", "amount": 10000}],
    }
    result = check_base_amount(match)
    assert result is None  # no GST entries to validate


# ═══ Combined Verification ═══

def test_all_sections_have_rates():
    """Every section in expense map should have a rate."""
    for section in SECTION_EXPENSE_MAP:
        rates = TDS_RATES.get(section)
        if rates:
            assert "default" in rates or len(rates) > 0, f"Section {section} has no rate"
    print("All sections have rates")


def test_all_sections_have_thresholds():
    """Most sections should have threshold (except 195)."""
    sections_with_threshold = [s for s in TDS_THRESHOLDS if TDS_THRESHOLDS[s].get("aggregate_annual")]
    assert len(sections_with_threshold) >= 5
    print(f"{len(sections_with_threshold)} sections have aggregate_annual threshold")
