"""
Test Matcher Agent Pass 6 — LLM-assisted matching.

Tests use mock LLM responses to verify the logic without actual API calls.
Run: pytest tests/test_matcher_llm.py -v -s
"""

import pytest
from app.agents.matcher_agent import MatcherAgent
from app.agents.utils import normalize_name, name_similarity
from app.services.llm_client import LLMClient
from app.pipeline.events import EventEmitter
from app.db.repository import Repository


class MockLLMClient:
    """Mock LLM that returns predefined responses for testing."""

    def __init__(self, responses: list[dict]):
        self._responses = responses
        self._call_count = 0
        self.available = True

    def complete(self, prompt, system="", agent_name="", json_mode=False, **kwargs):
        import json
        result = self.complete_json(prompt, system, agent_name)
        return json.dumps(result) if result else None

    def complete_json(self, prompt, system="", agent_name="", **kwargs):
        if self._call_count < len(self._responses):
            response = self._responses[self._call_count]
            self._call_count += 1
            return response
        return None


# ═══ Unit Tests (no DB, mock LLM) ═══

def test_pass6_llm_confirms_match():
    """LLM confirms a match → entry marked as matched."""
    events = EventEmitter(run_id="test")

    # Mock LLM says "yes, this is a match"
    mock_llm = MockLLMClient([{
        "match_found": True,
        "matched_candidate_index": 0,
        "confidence": 0.85,
        "reasoning": "Same vendor, amount difference is GST component",
        "amount_explanation": "Rs 48,500 + 18% GST = Rs 57,230 ≈ Rs 57,000",
    }])

    # Create a minimal MatcherAgent (won't use DB for this test)
    agent = MatcherAgent.__new__(MatcherAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "Matcher Agent"

    # Unmatched Form 26 entry
    f26_entries = [{
        "vendor_name": "ANDERSON TECHNOLOGY PVT LTD",
        "section": "194C",
        "amount_paid": 57000,
        "amount_paid_date": "2025-03-15",
        "pan": "AAACA1234A",
        "_matched": False,
    }]

    # Candidate Tally entries
    tally_entries = [{
        "party_name": "Anderson Tech",
        "amount": 48500,
        "date": "2025-03-10",
        "tally_source": "gst_exp",
        "_matched": False,
    }]

    matches = agent._pass6_llm_match(f26_entries, tally_entries)

    assert len(matches) == 1
    assert matches[0]["pass_name"] == "llm_match"
    assert matches[0]["confidence"] == 0.85
    assert "GST" in matches[0]["match_details"]["reasoning"]
    assert f26_entries[0]["_matched"] is True
    assert tally_entries[0]["_matched"] is True

    # Check events
    llm_events = [e for e in events.events if e["type"] == "llm_insight"]
    assert len(llm_events) == 1
    print(f"LLM insight: {llm_events[0]['message']}")


def test_pass6_llm_rejects_match():
    """LLM says no match → entry stays unmatched."""
    events = EventEmitter(run_id="test")

    mock_llm = MockLLMClient([{
        "match_found": False,
        "confidence": 0.3,
        "reasoning": "Different vendors despite similar names",
    }])

    agent = MatcherAgent.__new__(MatcherAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "Matcher Agent"

    f26_entries = [{
        "vendor_name": "ANDERSON TECHNOLOGY PVT LTD",
        "section": "194C", "amount_paid": 57000,
        "amount_paid_date": "2025-03-15", "_matched": False,
    }]
    tally_entries = [{
        "party_name": "Anderson Pharma Ltd",
        "amount": 120000, "date": "2025-01-05",
        "tally_source": "purchase", "_matched": False,
    }]

    matches = agent._pass6_llm_match(f26_entries, tally_entries)

    assert len(matches) == 0
    assert f26_entries[0]["_matched"] is False
    print("LLM correctly rejected the match")


def test_pass6_llm_underconfident():
    """LLM confidence < 0.6 → flagged for human review, not auto-matched."""
    events = EventEmitter(run_id="test")

    mock_llm = MockLLMClient([{
        "match_found": True,
        "matched_candidate_index": 0,
        "confidence": 0.45,
        "reasoning": "Possibly the same vendor but amount difference is large",
    }])

    agent = MatcherAgent.__new__(MatcherAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "Matcher Agent"

    f26_entries = [{
        "vendor_name": "SOME VENDOR LTD",
        "section": "194C", "amount_paid": 100000,
        "amount_paid_date": "2025-03-15", "_matched": False,
    }]
    tally_entries = [{
        "party_name": "Some Vendor",
        "amount": 50000, "date": "2025-02-20",
        "tally_source": "gst_exp", "_matched": False,
    }]

    matches = agent._pass6_llm_match(f26_entries, tally_entries)

    assert len(matches) == 0  # not matched — confidence too low
    assert f26_entries[0]["_matched"] is False  # stays unmatched

    # Should have emitted human_needed event
    human_events = [e for e in events.events if e["type"] == "human_needed"]
    assert len(human_events) == 1
    print(f"Human review needed: {human_events[0]['message']}")


def test_pass6_no_candidates():
    """No similar vendors found → skips LLM call entirely."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([])  # should never be called

    agent = MatcherAgent.__new__(MatcherAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "Matcher Agent"

    f26_entries = [{
        "vendor_name": "COMPLETELY UNIQUE VENDOR",
        "section": "194A", "amount_paid": 10000,
        "amount_paid_date": "2025-06-01", "_matched": False,
    }]
    tally_entries = [{
        "party_name": "Totally Different Company",
        "amount": 500000, "date": "2025-01-01",
        "tally_source": "journal_interest", "_matched": False,
    }]

    matches = agent._pass6_llm_match(f26_entries, tally_entries)

    assert len(matches) == 0
    assert mock_llm._call_count == 0  # LLM never called
    print("No candidates found — LLM not called (saved API cost)")


def test_pass6_llm_unavailable():
    """LLM not available → Pass 6 returns None for each call, skips match."""
    events = EventEmitter(run_id="test")

    # MockLLM that returns None (simulating unavailable)
    mock_llm = MockLLMClient([])
    mock_llm.available = True  # available but returns no responses

    agent = MatcherAgent.__new__(MatcherAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "Matcher Agent"

    f26_entries = [{"vendor_name": "Test Vendor Ltd",
                    "section": "194C", "amount_paid": 1000,
                    "amount_paid_date": "2025-01-01", "pan": "",
                    "_matched": False}]
    tally_entries = [{"party_name": "Test Vendor",
                      "amount": 1000, "date": "2025-01-01",
                      "tally_source": "gst_exp", "_matched": False}]

    matches = agent._pass6_llm_match(f26_entries, tally_entries)
    assert len(matches) == 0  # LLM returned None → no match created
    print("LLM unavailable — Pass 6 skipped gracefully")


# ═══ Helper function tests ═══

def test_name_similarity():
    """Verify name similarity scoring."""
    assert name_similarity("ANDERSON TECHNOLOGY PVT LTD", "Anderson Tech") > 0.3
    assert name_similarity("Inland World Pvt. Ltd.", "INLAND WORLD") > 0.8
    assert name_similarity("Completely Different", "Not Related At All") < 0.3
    print("Name similarity: working correctly")


def test_normalize_name():
    """Verify name normalization."""
    assert normalize_name("ANDERSON TECHNOLOGY PVT LTD") == "anderson technology"
    assert normalize_name("Inland World Pvt. Ltd.") == "inland world"
    assert normalize_name("SBI General Insurance Co. Ltd") == "sbi general insurance"
    print("Name normalization: working correctly")
