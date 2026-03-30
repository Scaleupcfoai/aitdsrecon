"""
Test Column Mapper — Approach 1 (fuzzy → auto-map if >=0.8 → LLM for <0.8).

Run: pytest tests/test_column_mapper.py -v -s
"""

import pytest
from pathlib import Path
from app.services.column_mapper import (
    read_file_headers, fuzzy_match_columns, llm_map_uncertain,
    ColumnMapper, TDS_FIELDS, LEDGER_FIELDS, AUTO_MAP_THRESHOLD,
)
from app.services.llm_client import LLMClient
from app.pipeline.events import EventEmitter

SAMPLE_FORM26 = "data/hpc/Form 26 - Deduction Register....xlsx"
SAMPLE_TALLY = "data/hpc/Tally extract.xlsx"


# ═══ Header Detection ═══

def test_read_form26_headers():
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 not found")
    sheets = read_file_headers(SAMPLE_FORM26)
    assert len(sheets) >= 1
    assert sheets[0]["header_row"] == 4
    print(f"Form 26: {len(sheets[0]['headers'])} columns, header at row {sheets[0]['header_row']}")


def test_read_tally_headers():
    if not Path(SAMPLE_TALLY).exists():
        pytest.skip("Sample Tally not found")
    sheets = read_file_headers(SAMPLE_TALLY)
    assert len(sheets) >= 3
    for s in sheets:
        print(f"  {s['sheet_name']}: {len(s['headers'])} cols at row {s['header_row']}")


# ═══ Fuzzy Matching ═══

def test_fuzzy_exact_match():
    headers = [{"name": "Name", "col_index": 1}]
    results = fuzzy_match_columns(headers, TDS_FIELDS)
    assert results[0]["confidence"] == 1.0
    assert results[0]["suggested_field"] == "party_name"


def test_fuzzy_contains_match():
    headers = [{"name": "Amount Paid / Credited", "col_index": 1}]
    results = fuzzy_match_columns(headers, TDS_FIELDS)
    assert results[0]["confidence"] >= 0.7
    assert results[0]["suggested_field"] == "gross_amount"


def test_fuzzy_no_match():
    headers = [{"name": "XYZ Random Column", "col_index": 1}]
    results = fuzzy_match_columns(headers, TDS_FIELDS)
    assert results[0]["confidence"] < 0.5


# ═══ Approach 1: Auto-map vs LLM split ═══

def test_approach1_split():
    """High confidence auto-maps, low confidence goes to LLM."""
    headers = [
        {"name": "Name", "col_index": 1},           # exact → 1.0 → auto-map
        {"name": "Section", "col_index": 2},         # exact → 1.0 → auto-map
        {"name": "Some Random Col", "col_index": 3}, # low → LLM
    ]
    results = fuzzy_match_columns(headers, TDS_FIELDS)

    auto = [r for r in results if r["confidence"] >= AUTO_MAP_THRESHOLD]
    uncertain = [r for r in results if r["confidence"] < AUTO_MAP_THRESHOLD]

    assert len(auto) == 2  # Name + Section
    assert len(uncertain) == 1  # Random col
    print(f"Auto-mapped: {len(auto)}, Uncertain (→ LLM): {len(uncertain)}")


def test_approach1_form26_columns():
    """Test split on real Form 26 headers."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 not found")
    sheets = read_file_headers(SAMPLE_FORM26)
    results = fuzzy_match_columns(sheets[0]["headers"], TDS_FIELDS)

    auto = [r for r in results if r["confidence"] >= AUTO_MAP_THRESHOLD]
    uncertain = [r for r in results if r["confidence"] < AUTO_MAP_THRESHOLD]

    print(f"\nForm 26 Approach 1 split:")
    print(f"  Auto-mapped (>={AUTO_MAP_THRESHOLD}): {len(auto)}")
    for r in auto:
        print(f"    {r['col_name']:35s} → {r['suggested_field']:20s} ({r['confidence']:.2f})")
    print(f"  Uncertain (→ LLM): {len(uncertain)}")
    for r in uncertain:
        print(f"    {r['col_name']:35s} → {r['suggested_field']:20s} ({r['confidence']:.2f})")

    assert len(auto) >= 2  # At least Name + Section should auto-map


# ═══ LLM for uncertain columns ═══

def test_llm_maps_uncertain_columns():
    """LLM correctly maps columns that fuzzy couldn't."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 not found")
    from app.config import settings
    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY not set")

    sheets = read_file_headers(SAMPLE_FORM26)
    sheet = sheets[0]
    results = fuzzy_match_columns(sheet["headers"], TDS_FIELDS)
    uncertain = [r for r in results if r["confidence"] < AUTO_MAP_THRESHOLD]

    if not uncertain:
        pytest.skip("No uncertain columns to test LLM with")

    events = EventEmitter(run_id="test")
    llm = LLMClient(events=events)
    llm_results = llm_map_uncertain(uncertain, sheet["sheet_name"], sheet["sample_rows"], llm)

    print(f"\nLLM mapped {len(llm_results)} uncertain columns:")
    for m in llm_results:
        print(f"  {m.get('col_name', '?'):35s} → {m.get('field', '?'):20s} ({m.get('confidence', 0):.2f}) {m.get('reason', '')}")

    assert len(llm_results) == len(uncertain)

    # Check events were emitted
    llm_events = [e for e in events.events if e["type"] == "llm_call"]
    assert len(llm_events) >= 1
    print(f"  LLM calls made: {len(llm_events)}")


def test_llm_fallback_when_unavailable():
    """Without LLM, uncertain columns flagged for review."""
    uncertain = [
        {"col_name": "Mystery Col", "col_index": 1, "suggested_field": "unknown",
         "confidence": 0.3, "method": "sequence"},
    ]
    results = llm_map_uncertain(uncertain, "test", [], llm=None)
    assert len(results) == 1
    assert results[0]["field"] == "unknown"


# ═══ Full Pipeline ═══

def test_full_pipeline_form26():
    """End-to-end: read → fuzzy → LLM for uncertain → final mappings."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 not found")
    from app.config import settings
    if not settings.groq_api_key:
        pytest.skip("GROQ_API_KEY not set")

    events = EventEmitter(run_id="test")
    llm = LLMClient(events=events)
    mapper = ColumnMapper(llm=llm)
    result = mapper.map_file(SAMPLE_FORM26, file_type="tds")

    assert len(result["sheets"]) >= 1
    sheet = result["sheets"][0]
    stats = sheet.get("stats", {})

    print(f"\nFull pipeline — Form 26:")
    print(f"  Total columns: {stats.get('total_columns', 0)}")
    print(f"  Auto-mapped: {stats.get('auto_mapped', 0)}")
    print(f"  LLM-mapped: {stats.get('llm_mapped', 0)}")
    print(f"  Needs review: {stats.get('needs_review', 0)}")
    for m in sheet["mappings"]:
        review = " ⚠ REVIEW" if m.get("needs_review") else ""
        print(f"  {m['col_name']:35s} → {m['field']:20s} ({m['confidence']:.2f} {m['source']}){review}")
