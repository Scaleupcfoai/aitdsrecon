"""
Test Reporter Agent LLM integration — narrative summaries.

Run: pytest tests/test_reporter_llm.py -v -s
"""

import pytest
from app.agents.reporter_agent import ReporterAgent
from app.pipeline.events import EventEmitter


class MockLLMClient:
    def __init__(self, responses):
        self._responses = responses
        self._call_count = 0
        self.available = True

    def complete(self, prompt, system="", agent_name="", json_mode=False, **kw):
        if self._call_count < len(self._responses):
            r = self._responses[self._call_count]
            self._call_count += 1
            return r
        return None

    def complete_json(self, prompt, system="", agent_name="", **kw):
        import json
        r = self.complete(prompt, system, agent_name)
        return json.loads(r) if r else None


class MockDB:
    """Minimal mock for DB operations."""
    class MockSummaries:
        def bulk_insert(self, data): pass
    class MockRuns:
        def update_status(self, run_id, status): pass

    def __init__(self):
        self.summaries = self.MockSummaries()
        self.runs = self.MockRuns()


def test_narrative_generated():
    """LLM generates a professional narrative summary."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([
        "TDS Reconciliation for FY 2024-25 is complete. Out of 56 Form 26 entries in scope, "
        "all 56 have been matched with corresponding Tally records, achieving a 100% match rate. "
        "Additionally, 224 below-threshold entries were correctly identified as exempt.\n\n"
        "Three critical compliance issues require immediate attention: Kamal Kishor Bagri, "
        "Kochar Tradelink LLP, and Pukesh Sharma have brokerage payments under Section 194H "
        "where TDS has not been deducted. Total exposure is Rs 1,21,397.\n\n"
        "Recommended action: Deduct TDS at 2% on these brokerage amounts and deposit with "
        "interest u/s 201(1A) at 1% per month. File revised TDS returns for the applicable quarters."
    ])

    agent = ReporterAgent.__new__(ReporterAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "Reporter Agent"
    agent.financial_year = "2024-25"
    agent.company_id = "test-company"

    match_summary = {"matched": 56, "below_threshold": 224, "total_resolved": 280, "total_form26": 56}
    checker_summary = {"summary": {"total": 8, "errors": 3, "warnings": 5, "exposure": 121397}}
    findings = [
        {"severity": "error", "vendor": "Kamal Kishor Bagri", "message": "Missing TDS under 194H"},
        {"severity": "error", "vendor": "Kochar Tradelink LLP", "message": "Missing TDS under 194H"},
        {"severity": "error", "vendor": "Pukesh Sharma", "message": "Missing TDS under 194H"},
    ]

    narrative = agent._generate_narrative(match_summary, checker_summary, findings)

    assert narrative is not None
    assert len(narrative) > 100
    assert "194H" in narrative or "brokerage" in narrative
    assert "121,397" in narrative or "1,21,397" in narrative
    print(f"Narrative ({len(narrative)} chars):")
    print(narrative[:300])

    # Check SSE events
    # (narrative generation itself doesn't emit — the run() method does)


def test_narrative_in_summary():
    """Narrative is included in the summary dict returned by run()."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient(["This is the executive summary narrative."])
    mock_db = MockDB()

    agent = ReporterAgent.__new__(ReporterAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.db = mock_db
    agent.agent_name = "Reporter Agent"
    agent.run_id = "test-run"
    agent.company_id = "test-company"
    agent.financial_year = "2024-25"

    summary = agent.run(
        match_summary={"matched": 56, "total_resolved": 280},
        checker_summary={"summary": {"errors": 0, "warnings": 0, "exposure": 0}},
        matches=[],
        findings=[],
        output_dir="/tmp/test_reports",
    )

    assert "narrative" in summary
    assert summary["narrative"] == "This is the executive summary narrative."
    print(f"Summary has narrative: {summary['narrative'][:50]}...")


def test_narrative_without_llm():
    """Without LLM, reports still generate, no narrative field."""
    events = EventEmitter(run_id="test")
    mock_db = MockDB()

    agent = ReporterAgent.__new__(ReporterAgent)
    agent.llm = None
    agent.events = events
    agent.db = mock_db
    agent.agent_name = "Reporter Agent"
    agent.run_id = "test-run"
    agent.company_id = "test-company"
    agent.financial_year = "2024-25"

    summary = agent.run(
        match_summary={"matched": 56, "total_resolved": 280},
        checker_summary={"summary": {"errors": 0}},
        matches=[],
        findings=[],
        output_dir="/tmp/test_reports_nollm",
    )

    assert "narrative" not in summary
    print("No LLM — reports generated without narrative")


def test_narrative_llm_failure():
    """LLM fails → reports still generated, no crash."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([])  # returns None
    mock_db = MockDB()

    agent = ReporterAgent.__new__(ReporterAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.db = mock_db
    agent.agent_name = "Reporter Agent"
    agent.run_id = "test-run"
    agent.company_id = "test-company"
    agent.financial_year = "2024-25"

    summary = agent.run(
        match_summary={"matched": 10},
        checker_summary={"summary": {"errors": 2, "exposure": 50000}},
        matches=[],
        findings=[{"severity": "error", "vendor": "Test", "message": "Missing TDS"}],
        output_dir="/tmp/test_reports_fail",
    )

    # Should not crash, just no narrative
    assert "narrative" not in summary
    print("LLM failed — reports generated gracefully")
