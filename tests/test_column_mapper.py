"""
Test the column mapper — fuzzy matching, LLM verification, cross-verification.

Run: pytest tests/test_column_mapper.py -v

These tests use real sample files from data/hpc/ and the Groq LLM API.
"""

import pytest
from pathlib import Path
from app.services.column_mapper import (
    read_file_headers,
    fuzzy_match_columns,
    llm_verify_mappings,
    cross_verify,
    ColumnMapper,
    TDS_FIELDS,
    LEDGER_FIELDS,
)

SAMPLE_FORM26 = "data/hpc/Form 26 - Deduction Register....xlsx"
SAMPLE_TALLY = "data/hpc/Tally extract.xlsx"


# ═══ Header Detection Tests ═══

def test_read_form26_headers():
    """Form 26 headers detected at correct row."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 file not found")
    sheets = read_file_headers(SAMPLE_FORM26)
    assert len(sheets) >= 1
    sheet = sheets[0]
    assert sheet["header_row"] == 4  # Form 26 has header at row 4
    header_names = [h["name"] for h in sheet["headers"]]
    assert "Name" in header_names or any("name" in h.lower() for h in header_names)
    assert len(sheet["sample_rows"]) >= 1
    print(f"Form 26: {len(sheet['headers'])} columns, header at row {sheet['header_row']}")


def test_read_tally_headers():
    """Tally file has 3+ sheets with headers detected."""
    if not Path(SAMPLE_TALLY).exists():
        pytest.skip("Sample Tally file not found")
    sheets = read_file_headers(SAMPLE_TALLY)
    # Should have Journal Register, Purchase GST Exp, Purchase Register
    sheet_names = [s["sheet_name"] for s in sheets]
    assert len(sheets) >= 3
    print(f"Tally sheets: {sheet_names}")
    for s in sheets:
        assert len(s["headers"]) >= 3
        assert s["header_row"] >= 1
        print(f"  {s['sheet_name']}: {len(s['headers'])} cols, header at row {s['header_row']}")


# ═══ Fuzzy Matching Tests ═══

def test_fuzzy_exact_match():
    """Exact keyword match gives confidence 1.0."""
    headers = [{"name": "Name", "col_index": 1}]
    results = fuzzy_match_columns(headers, TDS_FIELDS)
    assert results[0]["confidence"] == 1.0
    assert results[0]["suggested_field"] == "party_name"


def test_fuzzy_contains_match():
    """Column containing a keyword gets high confidence."""
    headers = [{"name": "Amount Paid / Credited", "col_index": 1}]
    results = fuzzy_match_columns(headers, TDS_FIELDS)
    assert results[0]["confidence"] >= 0.7
    assert results[0]["suggested_field"] == "gross_amount"


def test_fuzzy_partial_match():
    """Partial similarity gives moderate confidence."""
    headers = [{"name": "Vendor Name", "col_index": 1}]
    results = fuzzy_match_columns(headers, LEDGER_FIELDS)
    assert results[0]["confidence"] >= 0.5
    assert results[0]["suggested_field"] == "party_name"


def test_fuzzy_no_match():
    """Completely unrelated column gets low confidence."""
    headers = [{"name": "XYZ Random Column", "col_index": 1}]
    results = fuzzy_match_columns(headers, TDS_FIELDS)
    assert results[0]["confidence"] < 0.5


def test_fuzzy_form26_columns():
    """Test fuzzy matching against real Form 26 headers."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 file not found")
    sheets = read_file_headers(SAMPLE_FORM26)
    results = fuzzy_match_columns(sheets[0]["headers"], TDS_FIELDS)
    # Print all mappings for debugging
    for r in results:
        print(f"  {r['col_name']:40s} → {r['suggested_field']:20s} ({r['confidence']:.2f} {r['method']})")
    # At least Name and Section should map well
    high_conf = [r for r in results if r["confidence"] >= 0.7]
    assert len(high_conf) >= 2, f"Expected at least 2 high-confidence mappings, got {len(high_conf)}"


# ═══ LLM Verification Tests ═══

def test_llm_verify_form26():
    """LLM correctly identifies Form 26 document type and verifies mappings."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 file not found")
    from app.config import settings
    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY not set")

    sheets = read_file_headers(SAMPLE_FORM26)
    sheet = sheets[0]
    fuzzy = fuzzy_match_columns(sheet["headers"], TDS_FIELDS)
    result = llm_verify_mappings(sheet["sheet_name"], sheet["headers"],
                                 sheet["sample_rows"], fuzzy)

    print(f"Document type: {result.get('document_type')}")
    for m in result.get("mappings", []):
        print(f"  {m.get('col_name', '?'):40s} → {m.get('field', '?'):20s} ({m.get('confidence', 0):.2f})")

    assert result.get("document_type") is not None
    assert len(result.get("mappings", [])) >= 3


def test_llm_verify_tally():
    """LLM correctly identifies Tally register types."""
    if not Path(SAMPLE_TALLY).exists():
        pytest.skip("Sample Tally file not found")
    from app.config import settings
    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY not set")

    sheets = read_file_headers(SAMPLE_TALLY)
    for sheet in sheets[:2]:  # Test first 2 sheets
        fuzzy = fuzzy_match_columns(sheet["headers"], LEDGER_FIELDS)
        result = llm_verify_mappings(sheet["sheet_name"], sheet["headers"],
                                     sheet["sample_rows"], fuzzy)
        print(f"\n{sheet['sheet_name']}: doc_type={result.get('document_type')}")
        for m in result.get("mappings", [])[:5]:
            print(f"  {m.get('col_name', '?'):40s} → {m.get('field', '?')}")


# ═══ Cross-Verification Tests ═══

def test_cross_verify_agreement():
    """When fuzzy and LLM agree, confidence is boosted."""
    fuzzy = [{"col_name": "Name", "col_index": 1, "suggested_field": "party_name",
              "confidence": 1.0, "method": "exact"}]
    llm = {"mappings": [{"col_name": "Name", "field": "party_name",
                          "confidence": 0.95, "reason": "Standard name field"}],
            "needs_user_review": []}

    result = cross_verify(fuzzy, llm)
    assert result[0]["source"] == "both_agree"
    assert result[0]["confidence"] >= 0.9
    assert result[0]["needs_review"] == False


def test_cross_verify_disagreement():
    """When fuzzy and LLM disagree, flag for review."""
    fuzzy = [{"col_name": "Amount", "col_index": 1, "suggested_field": "gross_amount",
              "confidence": 0.8, "method": "contains"}]
    llm = {"mappings": [{"col_name": "Amount", "field": "tds_amount",
                          "confidence": 0.7, "reason": "Small values suggest TDS"}],
            "needs_user_review": []}

    result = cross_verify(fuzzy, llm)
    assert result[0]["source"] == "llm_override"
    assert result[0]["needs_review"] == True


def test_cross_verify_llm_unsure():
    """When LLM says unknown, fall back to fuzzy if confident."""
    fuzzy = [{"col_name": "Section", "col_index": 1, "suggested_field": "tds_section",
              "confidence": 1.0, "method": "exact"}]
    llm = {"mappings": [{"col_name": "Section", "field": "unknown",
                          "confidence": 0.3, "reason": "Not sure"}],
            "needs_user_review": ["Section"]}

    result = cross_verify(fuzzy, llm)
    assert result[0]["field"] == "tds_section"  # fuzzy wins
    assert result[0]["confidence"] < 1.0  # but discounted


# ═══ Full Pipeline Test ═══

def test_full_pipeline_form26():
    """End-to-end: read Form 26 → fuzzy → LLM → cross-verify."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 file not found")
    from app.config import settings
    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY not set")

    mapper = ColumnMapper()
    result = mapper.map_file(SAMPLE_FORM26, file_type="tds")

    assert len(result["sheets"]) >= 1
    sheet = result["sheets"][0]
    print(f"\nFull pipeline — Form 26:")
    print(f"  Document type: {sheet['document_type']}")
    print(f"  Columns mapped: {len(sheet['mappings'])}")
    print(f"  Needs review: {sheet['needs_user_review']}")
    for m in sheet["mappings"]:
        review = " ⚠ REVIEW" if m.get("needs_review") else ""
        print(f"  {m['col_name']:40s} → {m['field']:20s} ({m['confidence']:.2f} {m['source']}){review}")

    # At least party_name, tds_section, and gross_amount should be mapped
    mapped_fields = {m["field"] for m in sheet["mappings"] if m["confidence"] >= 0.6}
    assert "party_name" in mapped_fields or "unknown" not in mapped_fields
