"""
Test Chat Agent — tool execution, conversation flow.

Run: pytest tests/test_chat_agent.py -v -s
"""

import pytest
from app.agents.chat_agent import ChatAgent
from app.pipeline.events import EventEmitter


class MockDB:
    """Mock DB that returns canned data for tool calls."""
    class MockSummaries:
        def get_by_run(self, run_id):
            class Summary:
                group_key = "executive_summary"
                llm_summary = "56 entries matched. 3 errors found. Rs 1.21L exposure."
                entry_count = 56
                total_amount = 280
                status = "needs_attention"
                section = "ALL"
            return [Summary()]

    class MockMatches:
        def get_by_run(self, run_id):
            class Match:
                id = "match-001"
                tds_entry_id = "tds-001"
                match_type = "exact_match"
                confidence = 1.0
                amount = 82461
                status = "auto_matched"
            return [Match()]

    class MockEntries:
        def get_tds_by_run(self, run_id):
            class TdsEntry:
                id = "tds-001"
                party_name = "Adi Debnath"
                tds_section = "194A"
                gross_amount = 82461
                tds_amount = 8246
                pan = "AAAAA0001A"
            return [TdsEntry()]

    class MockDiscrepancies:
        def get_by_match(self, match_id):
            class Action:
                stage = "section_validation"
                action_status = "proposed"
                llm_reasoning = "Section 194A is correct for interest payment"
                proposed_action = {"action": "No action needed — correctly deducted"}
            return [Action()]

    class MockFeedback:
        class Result:
            id = "fb-001"
        def create(self, **kw):
            return self.Result()

    class MockPatterns:
        class Result:
            id = "pat-001"
        def create(self, **kw):
            return self.Result()

    class MockTable:
        def update(self, data): return self
        def eq(self, k, v): return self
        def execute(self):
            class R:
                data = []
            return R()

    def __init__(self):
        self.summaries = self.MockSummaries()
        self.matches = self.MockMatches()
        self.entries = self.MockEntries()
        self.discrepancies = self.MockDiscrepancies()
        self.feedback = self.MockFeedback()
        self.patterns = self.MockPatterns()
        self._client = self.MockTable()


# ═══ Tool Execution Tests ═══

def test_tool_get_results_summary():
    """get_results_summary returns summary from DB."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1", run_id="run-001")
    result = agent._tool_get_results_summary()

    assert result["entry_count"] == 56
    assert "matched" in result["summary"].lower()
    print(f"Summary: {result['summary']}")


def test_tool_get_match_details():
    """get_match_details returns matches from DB."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1", run_id="run-001")
    result = agent._tool_get_match_details()

    assert result["count"] == 1
    assert result["matches"][0]["match_type"] == "exact_match"
    print(f"Matches: {result['count']}, type: {result['matches'][0]['match_type']}")


def test_tool_get_findings():
    """get_findings returns discrepancy actions from DB."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1", run_id="run-001")
    result = agent._tool_get_findings()

    assert result["total_findings"] >= 1
    assert "section_validation" in result["findings"][0]["stage"]
    print(f"Findings: {result['total_findings']}")


def test_tool_explain_finding():
    """explain_finding returns vendor-specific details."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1", run_id="run-001")
    result = agent._tool_explain_finding("Adi Debnath")

    assert result["vendor"] == "Adi Debnath"
    assert len(result["details"]) >= 1
    assert result["details"][0]["section"] == "194A"
    print(f"Explained: {result['vendor']} — {result['details'][0]['section']}")


def test_tool_no_run_id():
    """Tools return error when no run_id is set."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1", run_id=None)

    assert "error" in agent._tool_get_results_summary()
    assert "error" in agent._tool_get_match_details()
    assert "error" in agent._tool_get_findings()
    print("No run_id — all tools return clear error")


def test_tool_submit_review():
    """submit_review records decision via Learning Agent."""
    db = MockDB()
    events = EventEmitter(run_id="chat")
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1", events=events, run_id="run-001")
    result = agent._tool_submit_review("Xpress Cargo", "below_threshold", "Under threshold")

    assert result["status"] == "recorded"
    assert result["vendor"] == "Xpress Cargo"
    print(f"Review submitted: {result['vendor']} → {result['decision']}")


# ═══ Chat Flow Tests ═══

def test_chat_without_llm():
    """Chat without API key returns helpful error."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1")
    agent._client = None  # simulate no API key

    result = agent.chat("Hello")
    assert "not available" in result.lower()
    print(f"No LLM: {result}")


def test_system_prompt_includes_knowledge():
    """System prompt includes TDS knowledge from knowledge base."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1")
    prompt = agent._build_system_prompt()

    assert "194A" in prompt
    assert "194C" in prompt
    assert "Income Tax Act" in prompt
    assert "ONLY" in prompt  # "Use ONLY the following verified TDS rules"
    assert f"Firm ID: f1" in prompt
    print(f"System prompt: {len(prompt)} chars, includes knowledge base")


def test_conversation_history_maintained():
    """Conversation history tracks messages and can be reset."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1")

    # Manually add to history (since no LLM to call)
    agent.conversation_history.append({"role": "user", "content": "Hello"})
    agent.conversation_history.append({"role": "assistant", "content": "Hi there"})
    assert len(agent.conversation_history) == 2

    agent.reset_history()
    assert len(agent.conversation_history) == 0
    print("History: maintained and resettable")


def test_chat_stream_without_llm():
    """Streaming chat without API key yields error."""
    db = MockDB()
    agent = ChatAgent(db=db, firm_id="f1", company_id="c1")
    agent._client = None

    chunks = list(agent.chat_stream("Hello"))
    full = "".join(chunks)
    assert "not available" in full.lower()
    print(f"Stream without LLM: {full}")
