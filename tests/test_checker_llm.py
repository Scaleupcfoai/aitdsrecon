"""
Test TDS Checker Agent LLM integration — section classification + remediation.

Run: pytest tests/test_checker_llm.py -v -s
"""

import pytest
from app.agents.tds_checker_agent import TdsCheckerAgent, check_section, check_rate
from app.pipeline.events import EventEmitter


class MockLLMClient:
    def __init__(self, responses):
        self._responses = responses
        self._call_count = 0
        self.available = True

    def complete(self, prompt, system="", agent_name="", json_mode=False, **kw):
        import json
        r = self.complete_json(prompt, system, agent_name)
        return json.dumps(r) if r else None

    def complete_json(self, prompt, system="", agent_name="", **kw):
        if self._call_count < len(self._responses):
            r = self._responses[self._call_count]
            self._call_count += 1
            return r
        return None


# ═══ LLM Section Classification Tests ═══

def test_llm_classifies_advertisement_as_194c():
    """LLM classifies 'Advertisement' expense as 194C (works contract)."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([{
        "correct_section": "194C",
        "confidence": 0.85,
        "reasoning": "Advertisement for printing/production work is 194C works contract",
        "is_current_correct": True,
    }])

    agent = TdsCheckerAgent.__new__(TdsCheckerAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "TDS Checker"

    ambiguous_findings = [{
        "check": "section_validation",
        "severity": "warning",
        "status": "review",
        "vendor": "ANDREAL INNOVATION PVT LTD",
        "form26_section": "194C",
        "expense_heads": ["Advertisement"],
        "message": "Ambiguous expense: Advertisement",
    }]

    agent._llm_classify_sections(ambiguous_findings)

    # LLM confirmed 194C is correct → severity downgraded to info
    assert ambiguous_findings[0]["severity"] == "info"
    assert "confirmed" in ambiguous_findings[0]["message"].lower()
    print(f"Result: {ambiguous_findings[0]['message']}")

    # Check SSE event
    insights = [e for e in events.events if e["type"] == "llm_insight"]
    assert len(insights) == 1


def test_llm_reclassifies_to_194jb():
    """LLM says 'Advertisement' should be 194J(b), not 194C."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([{
        "correct_section": "194J(b)",
        "confidence": 0.8,
        "reasoning": "Creative/professional advertising services fall under 194J(b)",
        "is_current_correct": False,
    }])

    agent = TdsCheckerAgent.__new__(TdsCheckerAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "TDS Checker"

    findings = [{
        "check": "section_validation", "severity": "warning", "status": "review",
        "vendor": "CREATIVE AGENCY LTD", "form26_section": "194C",
        "expense_heads": ["Advertisement"], "message": "Ambiguous",
    }]

    agent._llm_classify_sections(findings)

    assert findings[0]["severity"] == "error"  # upgraded — wrong section
    assert "194J(b)" in findings[0]["message"]
    print(f"Result: {findings[0]['message']}")


def test_llm_unsure_about_section():
    """LLM has low confidence → stays as warning, flagged for human."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([{
        "correct_section": "194C",
        "confidence": 0.4,
        "reasoning": "Could be either 194C or 194J(b), need invoice details",
        "is_current_correct": False,
    }])

    agent = TdsCheckerAgent.__new__(TdsCheckerAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "TDS Checker"

    findings = [{
        "check": "section_validation", "severity": "warning", "status": "review",
        "vendor": "SOME VENDOR", "form26_section": "194C",
        "expense_heads": ["Software"], "message": "Ambiguous",
    }]

    agent._llm_classify_sections(findings)

    assert findings[0]["severity"] == "warning"  # stays as warning
    human_events = [e for e in events.events if e["type"] == "human_needed"]
    assert len(human_events) == 1
    print(f"Flagged for human review: {human_events[0]['message']}")


# ═══ LLM Remediation Tests ═══

def test_llm_writes_remediation():
    """LLM writes actionable remediation for error findings."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([{
        "remediations": [{
            "finding_index": 0,
            "what_is_wrong": "TDS not deducted on brokerage payment",
            "why_it_matters": "Non-deduction attracts penalty u/s 271C + interest u/s 201(1A)",
            "action_steps": [
                "Deduct TDS at 2% on brokerage amount",
                "Deposit TDS with interest at 1% per month",
                "File revised TDS return for the applicable quarter"
            ],
            "deadline": "Before filing next quarterly return",
            "penalty_risk": "Rs 16,845 TDS + Rs 1,685 interest (approx)",
            "priority": "high",
        }]
    }])

    agent = TdsCheckerAgent.__new__(TdsCheckerAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "TDS Checker"

    error_findings = [{
        "severity": "error", "check": "missing_tds",
        "vendor": "Kamal Kishor Bagri", "expected_section": "194H",
        "aggregate_amount": 16845,
        "message": "No Form 26 entry found for Kamal Kishor Bagri under 194H",
    }]

    agent._llm_write_remediations(error_findings)

    assert "remediation" in error_findings[0]
    rem = error_findings[0]["remediation"]
    assert rem["priority"] == "high"
    assert len(rem["action_steps"]) >= 2
    assert "271C" in rem["why_it_matters"]
    print(f"Remediation: {rem['what_is_wrong']}")
    print(f"  Steps: {rem['action_steps']}")
    print(f"  Penalty: {rem['penalty_risk']}")


def test_llm_remediation_unavailable():
    """No LLM → findings still correct, no remediation field."""
    events = EventEmitter(run_id="test")
    mock_llm = MockLLMClient([])  # returns None

    agent = TdsCheckerAgent.__new__(TdsCheckerAgent)
    agent.llm = mock_llm
    agent.events = events
    agent.agent_name = "TDS Checker"

    error_findings = [{
        "severity": "error", "check": "missing_tds",
        "vendor": "Test Vendor", "message": "Missing TDS",
        "aggregate_amount": 50000,
    }]

    agent._llm_write_remediations(error_findings)

    # No remediation added (LLM returned None)
    assert "remediation" not in error_findings[0]
    print("LLM unavailable — findings preserved without remediation")


# ═══ Deterministic Check Tests (verify they still work) ═══

def test_deterministic_section_check():
    """Section validation works without LLM."""
    match = {
        "form26_entry": {"section": "194C", "vendor_name": "Test"},
        "tally_entries": [{"expense_heads": {"Freight Charges": 5000}}],
    }
    result = check_section(match)
    # Freight under 194C should be OK → no finding
    assert result is None
    print("Deterministic section check: freight under 194C = OK")


def test_deterministic_rate_check():
    """Rate validation works without LLM."""
    match = {
        "form26_entry": {
            "section": "194C", "vendor_name": "Test",
            "pan": "AAACA1234A",  # 4th char 'C' = company → 2%
            "tax_rate_pct": 2.0, "amount_paid": 100000, "tax_deducted": 2000,
        },
        "tally_entries": [],
    }
    result = check_rate(match)
    # 194C company at 2% is correct → no finding
    assert result is None
    print("Deterministic rate check: 194C company at 2% = OK")
