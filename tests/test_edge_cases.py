"""
Edge case tests — every breakable path across all layers.

Run: pytest tests/test_edge_cases.py -v -s
"""

import pytest
from app.agents.parser_agent import safe_float, clean_name, to_date_str, classify_expense
from app.agents.utils import normalize_name, name_similarity, amount_close
from app.services.llm_client import LLMClient
from app.pipeline.events import EventEmitter
from app.knowledge import get_section_rate, get_entity_type, get_threshold


# ═══════════════════════════════════════════════════════════
# Parser Edge Cases
# ═══════════════════════════════════════════════════════════

class TestSafeFloat:
    def test_none(self):
        assert safe_float(None) == 0.0

    def test_zero(self):
        assert safe_float(0) == 0.0

    def test_negative(self):
        assert safe_float(-5000) == -5000.0

    def test_string_number(self):
        assert safe_float("10000") == 10000.0

    def test_string_with_commas(self):
        assert safe_float("1,00,000") == 100000.0

    def test_string_with_spaces(self):
        assert safe_float(" 5000 ") == 5000.0

    def test_empty_string(self):
        assert safe_float("") == 0.0

    def test_dash_string(self):
        assert safe_float("-") == 0.0

    def test_non_numeric_string(self):
        assert safe_float("hello") == 0.0

    def test_boolean(self):
        assert safe_float(True) == 1.0

    def test_integer(self):
        assert safe_float(42) == 42.0


class TestCleanName:
    def test_standard_form26(self):
        r = clean_name("Adi Debnath (34); PAN: AAAAA0001A")
        assert r["name"] == "Adi Debnath"
        assert r["pan"] == "AAAAA0001A"
        assert r["id"] == "34"

    def test_pan_only(self):
        r = clean_name("Some Vendor; PAN: BBBBB2222B")
        assert r["name"] == "Some Vendor"
        assert r["pan"] == "BBBBB2222B"

    def test_plain_name(self):
        r = clean_name("Plain Vendor Name")
        assert r["name"] == "Plain Vendor Name"
        assert r["pan"] == ""

    def test_empty(self):
        r = clean_name("")
        assert r["name"] == ""

    def test_none(self):
        r = clean_name(None)
        assert r["name"] == ""

    def test_unicode_name(self):
        r = clean_name("राम कुमार (5); PAN: AAAPK1234A")
        assert r["pan"] == "AAAPK1234A"

    def test_special_characters(self):
        r = clean_name("M/s. O'Brien & Associates; PAN: AAAPA9999A")
        assert "O'Brien" in r["name"]


class TestToDateStr:
    def test_none(self):
        assert to_date_str(None) is None

    def test_datetime(self):
        from datetime import datetime
        assert to_date_str(datetime(2025, 3, 31)) == "2025-03-31"

    def test_date(self):
        from datetime import date
        assert to_date_str(date(2025, 3, 31)) == "2025-03-31"

    def test_string(self):
        assert to_date_str("2025-03-31T12:00:00") == "2025-03-31"

    def test_number(self):
        result = to_date_str(45000)  # Excel serial date
        assert result is not None  # should not crash


class TestClassifyExpense:
    def test_freight(self):
        assert classify_expense("Freight Charges") == "freight_expense"

    def test_interest(self):
        assert classify_expense("Interest Paid") == "interest_payment"

    def test_brokerage(self):
        assert classify_expense("Brokerage and Commission") == "brokerage"

    def test_professional(self):
        assert classify_expense("Audit Fees") == "professional_fees"

    def test_unknown(self):
        assert classify_expense("Random Column XYZ") == "other"

    def test_empty(self):
        assert classify_expense("") == "other"

    def test_none(self):
        assert classify_expense(None) == "other"

    def test_case_insensitive(self):
        assert classify_expense("FREIGHT CHARGES") == "freight_expense"


# ═══════════════════════════════════════════════════════════
# Matcher Edge Cases
# ═══════════════════════════════════════════════════════════

class TestNormalizeName:
    def test_whitespace_only(self):
        assert normalize_name("   ") == ""

    def test_special_chars(self):
        result = normalize_name("M/s. Test & Co.")
        assert "m/s. test &" in result

    def test_multiple_suffixes(self):
        assert normalize_name("ABC Pvt. Ltd. Inc.") == "abc"

    def test_parenthetical_numbers(self):
        assert "34" not in normalize_name("Vendor (34)")


class TestNameSimilarity:
    def test_one_empty(self):
        assert name_similarity("", "Something") == 0.0
        assert name_similarity("Something", "") == 0.0

    def test_both_empty(self):
        assert name_similarity("", "") == 0.0

    def test_single_word_match(self):
        assert name_similarity("Google", "Google India") >= 0.5

    def test_suffix_ignored(self):
        assert name_similarity("ABC Pvt Ltd", "ABC Private Limited") == 1.0


class TestAmountClose:
    def test_both_zero(self):
        assert amount_close(0, 0) is True

    def test_one_zero(self):
        assert amount_close(0, 100) is False
        assert amount_close(100, 0) is False

    def test_negative_amounts(self):
        assert amount_close(-1000, -1000) is True
        assert amount_close(-1000, -1005, 0.01) is True

    def test_very_small(self):
        assert amount_close(0.01, 0.01) is True

    def test_very_large(self):
        assert amount_close(10000000, 10000000) is True


# ═══════════════════════════════════════════════════════════
# Checker Edge Cases
# ═══════════════════════════════════════════════════════════

class TestKnowledgeBase:
    def test_unknown_section(self):
        assert get_section_rate("194Z", "default") is None

    def test_empty_section(self):
        assert get_section_rate("", "default") is None

    def test_empty_pan(self):
        assert get_entity_type("") == "unknown"

    def test_short_pan(self):
        assert get_entity_type("AB") == "unknown"

    def test_threshold_nonexistent_section(self):
        assert get_threshold("999") is None

    def test_all_sections_have_name(self):
        from app.knowledge import get_sections
        for code, section in get_sections().items():
            assert "name" in section, f"Section {code} missing name"


# ═══════════════════════════════════════════════════════════
# LLM Client Edge Cases
# ═══════════════════════════════════════════════════════════

class TestLLMEdgeCases:
    def test_complete_json_empty_string(self):
        """LLM returns empty string → None."""
        llm = LLMClient.__new__(LLMClient)
        llm._client = None
        llm.events = None
        result = llm.complete_json("")
        assert result is None

    def test_complete_json_plain_text(self):
        """LLM returns non-JSON text → None."""
        events = EventEmitter(run_id="test")
        llm = LLMClient(events=events)

        # Monkey-patch complete to return non-JSON
        original = llm.complete
        llm.complete = lambda *a, **kw: "This is not JSON at all"
        result = llm.complete_json("test")
        assert result is None
        llm.complete = original

    def test_complete_json_markdown_wrapped(self):
        """LLM wraps JSON in markdown → extracted."""
        events = EventEmitter(run_id="test")
        llm = LLMClient(events=events)

        llm.complete = lambda *a, **kw: '```json\n{"key": "value"}\n```'
        result = llm.complete_json("test")
        assert result == {"key": "value"}

    def test_complete_json_array_response(self):
        """LLM returns JSON array → first element extracted."""
        events = EventEmitter(run_id="test")
        llm = LLMClient(events=events)

        llm.complete = lambda *a, **kw: '[{"a": 1}, {"b": 2}]'
        result = llm.complete_json("test")
        assert result == {"a": 1}

    def test_complete_json_string_confidence(self):
        """LLM returns confidence as string → converted to float."""
        events = EventEmitter(run_id="test")
        llm = LLMClient(events=events)

        llm.complete = lambda *a, **kw: '{"confidence": "0.85", "field": "amount"}'
        result = llm.complete_json("test")
        assert result["confidence"] == 0.85
        assert isinstance(result["confidence"], float)

    def test_complete_unavailable(self):
        """No API key → returns None, no crash."""
        llm = LLMClient.__new__(LLMClient)
        llm._client = None
        llm.events = None
        assert llm.complete("hello") is None
        assert llm.complete_json("hello") is None
        assert llm.available is False


# ═══════════════════════════════════════════════════════════
# API Edge Cases
# ═══════════════════════════════════════════════════════════

class TestAPIEdgeCases:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_invalid_report_filename(self, client):
        """Download with malicious filename → rejected."""
        r = client.get("/api/reports/run-1/download/malicious.sh")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data
        assert "not available" in data["error"]

    def test_download_nonexistent_run(self, client):
        """Download report for fake run → error."""
        r = client.get("/api/reports/nonexistent/download/tds_recon_report.xlsx")
        data = r.json()
        assert "error" in data

    def test_empty_chat_message(self, client):
        """Empty chat message → handled gracefully."""
        from app.config import settings
        if not settings.supabase_service_role_key:
            pytest.skip("No service role key")
        r = client.post("/api/chat", json={"message": ""})
        assert r.status_code == 200

    def test_health_always_works(self, client):
        """Health endpoint works regardless of config."""
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_openapi_has_all_endpoints(self, client):
        """OpenAPI schema has minimum expected endpoints."""
        r = client.get("/openapi.json")
        paths = list(r.json()["paths"].keys())
        assert len(paths) >= 15  # at least 15 endpoints

    def test_chat_reset_without_session(self, client):
        """Resetting chat without active session → no crash."""
        r = client.post("/api/chat/reset")
        assert r.status_code == 200
        assert r.json()["status"] == "reset"
