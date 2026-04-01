"""
Test API endpoints — verify all routers respond correctly.

Run: pytest tests/test_api_endpoints.py -v -s
"""

import pytest


# ═══ Health + Auth ═══

def test_health(test_client):
    """Health endpoint returns 200."""
    r = test_client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["version"] == "3.0.0"
    print(f"Health: {data}")


def test_auth_health(test_client):
    """Auth health returns 200."""
    r = test_client.get("/api/auth/health")
    assert r.status_code == 200


def test_auth_me(test_client):
    """Auth me returns user context (local dev placeholder)."""
    r = test_client.get("/api/auth/me")
    assert r.status_code == 200
    data = r.json()
    assert "user_id" in data
    assert "firm_id" in data
    print(f"Me: {data}")


# ═══ OpenAPI Docs ═══

def test_docs_available(test_client):
    """Swagger docs endpoint accessible."""
    r = test_client.get("/docs")
    assert r.status_code == 200


def test_openapi_schema(test_client):
    """OpenAPI schema has all expected paths."""
    r = test_client.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    paths = list(schema["paths"].keys())

    expected = ["/api/health", "/api/auth/me", "/api/upload",
                "/api/reconciliation/run", "/api/chat"]
    for ep in expected:
        assert ep in paths, f"Missing endpoint: {ep}"

    print(f"API has {len(paths)} endpoints")


# ═══ Chat ═══

def test_chat_no_llm(test_client):
    """Chat returns message even without LLM (local dev may not have Groq)."""
    from app.config import settings
    if not settings.supabase_service_role_key:
        pytest.skip("No service role key — chat needs DB")
    r = test_client.post("/api/chat", json={
        "message": "Hello",
        "company_id": "test",
    })
    assert r.status_code == 200
    data = r.json()
    assert "response" in data
    print(f"Chat response: {data['response'][:80]}")


def test_chat_reset(test_client):
    """Chat reset clears history."""
    r = test_client.post("/api/chat/reset")
    assert r.status_code == 200
    assert r.json()["status"] == "reset"


# ═══ Company ═══

def test_companies_list(test_client):
    """Companies list endpoint responds."""
    from app.config import settings
    if not settings.supabase_service_role_key:
        pytest.skip("No service role key")
    r = test_client.get("/api/companies")
    assert r.status_code == 200


# ═══ Reports ═══

def test_report_summary_no_run(test_client):
    """Report summary for non-existent run returns error."""
    from app.config import settings
    if not settings.supabase_service_role_key:
        pytest.skip("No service role key")
    r = test_client.get("/api/reports/fake-run-id/summary")
    assert r.status_code == 200
    data = r.json()
    # Either error or empty list
    assert isinstance(data, (list, dict))


def test_report_download_not_found(test_client):
    """Download non-existent report returns error."""
    r = test_client.get("/api/reports/fake-run/download/tds_recon_report.xlsx")
    assert r.status_code == 200
    data = r.json()
    assert "error" in data


def test_report_download_invalid_file(test_client):
    """Download invalid filename returns error."""
    r = test_client.get("/api/reports/fake-run/download/malicious.sh")
    assert r.status_code == 200
    data = r.json()
    assert "error" in data
    assert "not available" in data["error"]
