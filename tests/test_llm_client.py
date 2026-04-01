"""
Test LLM Client — verify connection, event emission, error handling.

Run: pytest tests/test_llm_client.py -v -s
"""

import pytest
from app.services.llm_client import LLMClient
from app.pipeline.events import EventEmitter


@pytest.fixture
def events():
    return EventEmitter(run_id="test-run")


@pytest.fixture
def llm(events):
    return LLMClient(events=events)


def test_llm_client_available(llm):
    """LLM client reports availability based on API key."""
    from app.config import settings
    if settings.groq_api_key:
        assert llm.available is True
        print("LLM client: available (Groq key set)")
    else:
        assert llm.available is False
        print("LLM client: not available (no key)")


def test_llm_complete_simple(llm, events):
    """Basic LLM call returns a response."""
    if not llm.available:
        pytest.skip("No LLM API key")

    result = llm.complete(
        prompt="What TDS section applies to interest on a bank fixed deposit? Reply in one line.",
        system="You are a TDS expert.",
        agent_name="Test Agent",
    )

    assert result is not None
    assert len(result) > 10
    assert "194A" in result or "194" in result
    print(f"LLM response: {result}")

    # Check events were emitted
    assert len(events.events) >= 2  # llm_call + llm_response
    assert events.events[0]["type"] == "llm_call"
    assert events.events[1]["type"] == "llm_response"
    print(f"Events emitted: {len(events.events)}")


def test_llm_complete_json(llm):
    """JSON mode returns parsed dict."""
    if not llm.available:
        pytest.skip("No LLM API key")

    result = llm.complete_json(
        prompt='What is the TDS rate for 194C for a company? Respond: {"section": "194C", "rate": X}',
        system="You are a tax calculator. Respond in JSON only.",
        agent_name="Test Agent",
    )

    assert result is not None
    assert isinstance(result, dict)
    assert "rate" in result or "section" in result
    print(f"JSON response: {result}")


def test_llm_graceful_fallback():
    """LLM with no API key returns None gracefully."""
    llm = LLMClient.__new__(LLMClient)
    llm._client = None
    llm.events = None

    result = llm.complete("Hello", agent_name="Test")
    assert result is None


def test_llm_events_contain_metadata(llm, events):
    """SSE events contain model name and timing."""
    if not llm.available:
        pytest.skip("No LLM API key")

    llm.complete("Say hello", agent_name="Test Agent")

    call_event = events.events[0]
    assert call_event["type"] == "llm_call"
    assert "model" in call_event.get("data", {})
    assert "prompt_length" in call_event.get("data", {})

    response_event = events.events[1]
    assert response_event["type"] == "llm_response"
    assert "elapsed_ms" in response_event.get("data", {})
    print(f"Call event data: {call_event.get('data')}")
    print(f"Response event data: {response_event.get('data')}")
