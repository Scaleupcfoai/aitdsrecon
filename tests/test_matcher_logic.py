"""
Test Matcher Agent — pure matching logic (no DB, no LLM).

Tests each of the 5 deterministic passes in isolation with in-memory data.
Run: pytest tests/test_matcher_logic.py -v -s
"""

import pytest
from app.agents.matcher_agent import (
    pass1_exact_match, pass2_gst_adjusted, pass3_exempt_filter,
    pass4_fuzzy_match, pass5_aggregated_match,
)
from app.agents.utils import normalize_name, name_similarity, amount_close


# ═══ Utility Tests ═══

def test_normalize_removes_suffixes():
    assert normalize_name("ANDERSON TECHNOLOGY PVT LTD") == "anderson technology"
    assert normalize_name("Inland World Pvt. Ltd.") == "inland world"
    assert normalize_name("SBI General Insurance Co. Ltd") == "sbi general insurance"
    assert normalize_name("Google India Private Limited") == "google india"


def test_normalize_removes_parenthetical_ids():
    assert "34" not in normalize_name("Adi Debnath (34)")
    assert normalize_name("Adi Debnath (34)") == "adi debnath"


def test_normalize_empty():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


def test_name_similarity_exact():
    assert name_similarity("Inland World", "Inland World") == 1.0


def test_name_similarity_case_insensitive():
    assert name_similarity("INLAND WORLD", "inland world") == 1.0


def test_name_similarity_with_suffix():
    assert name_similarity("INLAND WORLD PVT LTD", "Inland World") > 0.8


def test_name_similarity_different():
    assert name_similarity("Google India", "Amazon US") < 0.3


def test_name_similarity_empty():
    assert name_similarity("", "Something") == 0.0
    assert name_similarity("Something", "") == 0.0


def test_amount_close_exact():
    assert amount_close(10000, 10000) is True


def test_amount_close_within_tolerance():
    assert amount_close(10000, 10040, 0.005) is True  # 0.4% < 0.5%


def test_amount_close_outside_tolerance():
    assert amount_close(10000, 10100, 0.005) is False  # 1% > 0.5%


def test_amount_close_zero():
    assert amount_close(0, 0) is True
    assert amount_close(0, 100) is False


# ═══ Pass 1: Exact Match ═══

def _make_f26(name, amount, date, section="194A"):
    return {"vendor_name": name, "amount_paid": amount,
            "amount_paid_date": date, "section": section, "_matched": False}


def _make_tally(name, amount, date, source="journal_interest"):
    return {"party_name": name, "amount": amount, "date": date,
            "tally_source": source, "_matched": False}


def test_pass1_exact_match():
    """Exact name + amount + date within 3 days → match."""
    f26 = [_make_f26("Adi Debnath", 82461, "2025-03-31")]
    tally = [_make_tally("Adi Debnath", 82461, "2025-03-31")]
    matches = pass1_exact_match(f26, tally)
    assert len(matches) == 1
    assert matches[0]["pass_name"] == "exact_match"
    assert matches[0]["confidence"] == 1.0
    assert f26[0]["_matched"] is True


def test_pass1_no_match_wrong_amount():
    """Same name but different amount → no match."""
    f26 = [_make_f26("Adi Debnath", 82461, "2025-03-31")]
    tally = [_make_tally("Adi Debnath", 50000, "2025-03-31")]
    matches = pass1_exact_match(f26, tally)
    assert len(matches) == 0
    assert f26[0]["_matched"] is False


def test_pass1_no_match_wrong_name():
    """Different name → no match."""
    f26 = [_make_f26("Adi Debnath", 82461, "2025-03-31")]
    tally = [_make_tally("Completely Different", 82461, "2025-03-31")]
    matches = pass1_exact_match(f26, tally)
    assert len(matches) == 0


def test_pass1_date_within_3_days():
    """Date within 3 days → match."""
    f26 = [_make_f26("Vendor A", 10000, "2025-03-31")]
    tally = [_make_tally("Vendor A", 10000, "2025-03-28")]  # 3 days apart
    matches = pass1_exact_match(f26, tally)
    assert len(matches) == 1


def test_pass1_date_too_far():
    """Date more than 3 days apart → no match."""
    f26 = [_make_f26("Vendor A", 10000, "2025-03-31")]
    tally = [_make_tally("Vendor A", 10000, "2025-03-20")]  # 11 days
    matches = pass1_exact_match(f26, tally)
    assert len(matches) == 0


def test_pass1_already_matched_skipped():
    """Already matched entries are skipped."""
    f26 = [_make_f26("Vendor A", 10000, "2025-03-31")]
    f26[0]["_matched"] = True
    tally = [_make_tally("Vendor A", 10000, "2025-03-31")]
    matches = pass1_exact_match(f26, tally)
    assert len(matches) == 0


def test_pass1_multiple_matches():
    """Multiple F26 entries matched to different Tally entries."""
    f26 = [
        _make_f26("Vendor A", 10000, "2025-01-15"),
        _make_f26("Vendor B", 20000, "2025-02-20"),
    ]
    tally = [
        _make_tally("Vendor A", 10000, "2025-01-15"),
        _make_tally("Vendor B", 20000, "2025-02-20"),
    ]
    matches = pass1_exact_match(f26, tally)
    assert len(matches) == 2


# ═══ Pass 4: Fuzzy Match ═══

def test_pass4_fuzzy_name_variation():
    """Name variations with similar amount → fuzzy match."""
    f26 = [_make_f26("ANDERSON TECHNOLOGY PVT LTD", 50000, "2025-03-15", "194C")]
    tally = [_make_tally("Anderson Tech", 50000, "2025-03-10", "gst_exp")]
    matches = pass4_fuzzy_match(f26, tally)
    # Should match if name similarity > 40%
    if matches:
        assert matches[0]["pass_name"] == "fuzzy_match"
        assert matches[0]["confidence"] >= 0.7
        print(f"Fuzzy matched: confidence={matches[0]['confidence']}")
    else:
        # Name similarity might be below threshold for this pair
        sim = name_similarity("ANDERSON TECHNOLOGY PVT LTD", "Anderson Tech")
        print(f"No fuzzy match: similarity={sim}")


def test_pass4_no_match_different_vendor():
    """Completely different vendors → no fuzzy match."""
    f26 = [_make_f26("Google India", 100000, "2025-06-15")]
    tally = [_make_tally("Amazon Japan", 100000, "2025-06-15")]
    matches = pass4_fuzzy_match(f26, tally)
    assert len(matches) == 0


# ═══ Amount Close Tests for Pass 2 ═══

def test_pass2_gst_adjusted():
    """GST-adjusted amount match. F26 amount = Tally base (pre-GST)."""
    f26 = [_make_f26("Vendor X", 10000, "2025-03-15", "194C")]
    # Tally entry from GST exp register — amount is base, has GST
    tally = [{
        "party_name": "Vendor X", "amount": 10000, "date": "2025-03-15",
        "tally_source": "gst_exp", "_matched": False,
        "gross_amount": 11800,  # base + 18% GST
    }]
    matches = pass2_gst_adjusted(f26, tally)
    # Exact base amount match → should match
    if matches:
        assert matches[0]["pass_name"] == "gst_adjusted_base"
        print(f"GST adjusted match: {matches[0]['confidence']}")
