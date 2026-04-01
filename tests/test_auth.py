"""
Test auth — JWT verification, protected endpoints.

Run: pytest tests/test_auth.py -v -s
"""

import pytest
from app.auth.jwt import verify_token
from app.auth.dependencies import get_current_user, UserContext


# ═══ JWT Verification Tests ═══

def test_verify_empty_token():
    """Empty token raises ValueError."""
    with pytest.raises(ValueError, match="No token"):
        verify_token("")


def test_verify_garbage_token():
    """Random string raises ValueError."""
    with pytest.raises(ValueError, match="Invalid token"):
        verify_token("not-a-real-token")


def test_verify_with_bearer_prefix():
    """Token with 'Bearer ' prefix — prefix stripped, then validated."""
    with pytest.raises(ValueError):
        verify_token("Bearer not-a-real-token")


# ═══ UserContext Tests ═══

def test_user_context_dataclass():
    """UserContext holds user data."""
    user = UserContext(user_id="u1", email="test@firm.com", firm_id="f1")
    assert user.user_id == "u1"
    assert user.email == "test@firm.com"
    assert user.firm_id == "f1"
    assert user.role == "authenticated"  # default
    print(f"UserContext: {user}")


def test_local_dev_no_auth():
    """In local dev, no auth header returns placeholder user."""
    from app.config import settings
    if settings.environment != "local":
        pytest.skip("Only for local environment")

    user = get_current_user(authorization="")
    assert user.user_id == "00000000-0000-0000-0000-000000000001"
    assert user.firm_id == "00000000-0000-0000-0000-000000000001"
    print(f"Local dev user: {user.user_id}")


# ═══ FastAPI Endpoint Tests ═══

def test_health_no_auth():
    """Health endpoint works without auth."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    print(f"Health: {data}")


def test_auth_me_local_dev():
    """GET /auth/me returns placeholder user in local dev."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings

    if settings.environment != "local":
        pytest.skip("Only for local environment")

    client = TestClient(app)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "00000000-0000-0000-0000-000000000001"
    print(f"Auth me: {data}")


def test_companies_endpoint_accessible():
    """GET /companies works in local dev (no auth required)."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.config import settings

    if not settings.supabase_service_role_key:
        pytest.skip("SUPABASE_SERVICE_ROLE_KEY not set")

    client = TestClient(app)
    response = client.get("/api/companies")
    assert response.status_code == 200
    print(f"Companies: {response.json()}")
