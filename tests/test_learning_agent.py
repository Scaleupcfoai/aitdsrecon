"""
Test Learning Agent — record decisions, extract patterns, similarity search.

Run: pytest tests/test_learning_agent.py -v -s
"""

import pytest
from app.agents.learning_agent import LearningAgent
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


class MockDB:
    """Minimal mock DB for testing without Supabase."""
    class MockFeedback:
        class FeedbackResult:
            def __init__(self):
                self.id = "feedback-001"
        def create(self, **kw):
            return self.FeedbackResult()

    class MockPatterns:
        class PatternResult:
            def __init__(self):
                self.id = "pattern-001"
        def create(self, **kw):
            return self.PatternResult()

    class MockTable:
        def __init__(self):
            self._data = []
        def update(self, data):
            self._last_update = data
            return self
        def eq(self, field, value):
            return self
        def execute(self):
            class R:
                data = []
            return R()
        def select(self, *args):
            return self
        def or_(self, *args):
            return self
        def rpc(self, *args, **kw):
            return self

    def __init__(self):
        self.feedback = self.MockFeedback()
        self.patterns = self.MockPatterns()
        self._client = self.MockTable()

    def table(self, name):
        return self._client


def _make_agent(mock_llm=None, mock_db=None):
    events = EventEmitter(run_id="test-run")
    agent = LearningAgent.__new__(LearningAgent)
    agent.run_id = "test-run"
    agent.company_id = "test-company"
    agent.firm_id = "test-firm"
    agent.financial_year = "2024-25"
    agent.db = mock_db or MockDB()
    agent.events = events
    agent.llm = mock_llm
    agent.agent_name = "Learning Agent"
    return agent


# ═══ Record Decision Tests ═══

def test_record_decision_with_pattern():
    """Human decision → stored + LLM extracts pattern."""
    mock_llm = MockLLMClient([{
        "pattern_type": "below_threshold",
        "description": "Small logistics vendor under 194C threshold",
        "conditions": {
            "vendor_keywords": ["xpress", "cargo", "logistics"],
            "section": "194C",
            "amount_range": {"min": 0, "max": 100000},
        },
        "action": "below_threshold",
        "confidence": 0.85,
        "similar_vendors_hint": "VRL Logistics, Safexpress, other small transport vendors",
    }])

    agent = _make_agent(mock_llm=mock_llm)
    result = agent.record_decision(
        vendor="Xpress Cargo",
        decision_type="below_threshold",
        params={"section": "194C", "amount": 1500},
        reason="Annual payment only Rs 1,500 — well below Rs 1L threshold",
    )

    assert result["feedback_id"] == "feedback-001"
    assert result["pattern_id"] == "pattern-001"

    # Check events
    insights = [e for e in agent.events.events if e["type"] == "llm_insight"]
    assert len(insights) == 1
    assert "logistics" in insights[0]["message"].lower()
    print(f"Pattern extracted: {insights[0]['message']}")


def test_record_decision_without_llm():
    """Decision stored even without LLM — no pattern extracted."""
    agent = _make_agent(mock_llm=None)
    result = agent.record_decision(
        vendor="Test Vendor",
        decision_type="ignore",
        reason="Not TDS applicable",
    )

    assert result["feedback_id"] == "feedback-001"
    assert result["pattern_id"] is None
    print("Decision stored without LLM — no pattern extracted")


# ═══ Pattern Extraction Tests ═══

def test_pattern_extraction_output():
    """LLM returns structured pattern with conditions."""
    mock_llm = MockLLMClient([{
        "pattern_type": "vendor_category",
        "description": "Insurance companies — typically under 194D or 194I",
        "conditions": {
            "vendor_keywords": ["insurance", "general insurance", "life insurance"],
            "section": "194D",
        },
        "action": "section_override",
        "confidence": 0.9,
        "similar_vendors_hint": "SBI General, HDFC Ergo, LIC",
    }])

    agent = _make_agent(mock_llm=mock_llm)
    pattern_id = agent._extract_pattern(
        vendor="SBI General Insurance Co. Ltd",
        decision_type="section_override",
        params={"section": "194D", "amount": 63000},
        reason="This is insurance premium, not contractor payment",
    )

    assert pattern_id == "pattern-001"
    print("Pattern extracted successfully")


# ═══ Pseudo-Embedding Tests ═══

def test_pseudo_embedding_dimensions():
    """Pseudo-embedding has correct dimensions (1536)."""
    agent = _make_agent()
    embedding = agent._text_to_pseudo_embedding("test text")
    assert len(embedding) == 1536
    assert all(-1.0 <= v <= 1.0 for v in embedding)
    print(f"Embedding: {len(embedding)} dimensions, range [{min(embedding):.2f}, {max(embedding):.2f}]")


def test_pseudo_embedding_deterministic():
    """Same input → same embedding."""
    agent = _make_agent()
    e1 = agent._text_to_pseudo_embedding("same input")
    e2 = agent._text_to_pseudo_embedding("same input")
    assert e1 == e2
    print("Deterministic: same input → same embedding")


def test_pseudo_embedding_different():
    """Different input → different embedding."""
    agent = _make_agent()
    e1 = agent._text_to_pseudo_embedding("input A")
    e2 = agent._text_to_pseudo_embedding("input B")
    assert e1 != e2
    print("Different inputs → different embeddings")


# ═══ Apply Learned Rules Tests ═══

def test_apply_below_threshold_rule():
    """Learned below_threshold rule marks matching entries."""
    agent = _make_agent()

    # Mock get_learned_rules to return a rule
    agent.get_learned_rules = lambda: [{
        "id": "rule-001",
        "pattern_type": "below_threshold",
        "conditions": {"vendor_keywords": ["xpress", "cargo"], "section": "194C"},
        "action": "below_threshold",
        "description": "Small logistics vendor",
        "usage_count": 5,
    }]

    ledger_entries = [
        {"party_name": "Xpress Cargo", "amount": 1500},
        {"party_name": "Some Other Vendor", "amount": 50000},
        {"party_name": "Xpress Cargo Express", "amount": 800},
    ]

    result = agent.apply_learned_rules([], ledger_entries)

    assert result["below_threshold_count"] == 2  # both Xpress entries
    assert result["ignored_count"] == 0
    assert ledger_entries[0].get("_below_threshold") is True
    assert ledger_entries[1].get("_below_threshold") is None  # unaffected
    assert ledger_entries[2].get("_below_threshold") is True
    print(f"Applied: {result['below_threshold_count']} below-threshold, {result['ignored_count']} ignored")


def test_apply_ignore_rule():
    """Learned ignore rule marks matching entries."""
    agent = _make_agent()

    agent.get_learned_rules = lambda: [{
        "id": "rule-002",
        "pattern_type": "ignore_rule",
        "conditions": {"vendor_keywords": ["salary", "bonus"]},
        "action": "ignore",
        "description": "Salary payments — not TDS applicable via 194C",
        "usage_count": 10,
    }]

    ledger_entries = [
        {"party_name": "Salary & Bonus Account", "amount": 500000},
        {"party_name": "Freight Charges", "amount": 10000},
    ]

    result = agent.apply_learned_rules([], ledger_entries)

    assert result["ignored_count"] == 1
    assert ledger_entries[0].get("_ignored") is True
    assert ledger_entries[1].get("_ignored") is None
    print(f"Applied: {result['ignored_count']} ignored")


def test_no_rules_available():
    """No rules → nothing applied, no crash."""
    agent = _make_agent()
    agent.get_learned_rules = lambda: []

    result = agent.apply_learned_rules([], [{"party_name": "Test", "amount": 1000}])

    assert result["applied_count"] == 0
    print("No rules — nothing applied")
