"""
Shared test fixtures — used across all test files.

Provides:
- MockLLMClient: returns predefined responses (no API calls)
- MockDB: minimal DB mock for unit tests
- test_client: FastAPI TestClient for API tests
- repo: real Supabase repository (for integration tests)
"""

import pytest
from fastapi.testclient import TestClient

from app.pipeline.events import EventEmitter


# ═══════════════════════════════════════════════════════════
# Mock LLM Client — reusable across all agent tests
# ═══════════════════════════════════════════════════════════

class MockLLMClient:
    """Mock LLM that returns predefined responses. No API calls."""

    def __init__(self, responses: list | None = None):
        self._responses = responses or []
        self._call_count = 0
        self.available = True
        self.calls = []  # track what was called

    def complete(self, prompt, system="", agent_name="", json_mode=False,
                 include_knowledge=True, **kw):
        import json
        self.calls.append({"method": "complete", "prompt": prompt[:100], "agent": agent_name})
        r = self.complete_json(prompt, system, agent_name, include_knowledge=include_knowledge)
        return json.dumps(r) if r else None

    def complete_json(self, prompt, system="", agent_name="",
                      include_knowledge=True, **kw):
        self.calls.append({"method": "complete_json", "prompt": prompt[:100], "agent": agent_name})
        if self._call_count < len(self._responses):
            r = self._responses[self._call_count]
            self._call_count += 1
            return r
        return None


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def mock_llm():
    """Default mock LLM with empty responses."""
    return MockLLMClient()


@pytest.fixture
def events():
    """Fresh event emitter for each test."""
    return EventEmitter(run_id="test-run")


@pytest.fixture
def test_client():
    """FastAPI test client. Uses local dev auth (no JWT needed)."""
    from app.main import app
    return TestClient(app)


@pytest.fixture
def repo():
    """Real Supabase repository (for integration tests).
    Requires SUPABASE_SERVICE_ROLE_KEY in .env."""
    from app.config import settings
    if not settings.supabase_service_role_key:
        pytest.skip("SUPABASE_SERVICE_ROLE_KEY not set — skipping integration test")
    from app.db.client import get_admin_client
    from app.db.repository import Repository
    return Repository(client=get_admin_client())


@pytest.fixture
def test_firm(repo):
    """Create a test firm and clean up after."""
    firm = repo.firms.create("Integration Test Firm", pan_no="AAAIT0001A")
    yield firm
    try:
        repo._client.table("ca_firm").delete().eq("id", firm.id).execute()
    except Exception:
        pass


@pytest.fixture
def test_company(repo, test_firm):
    """Create a test company under the test firm."""
    return repo.companies.create(
        firm_id=test_firm.id,
        company_name="Integration Test Co",
        pan="AAAITC001A",
        company_type="company",
    )
