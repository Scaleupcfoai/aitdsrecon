"""
Test the repository layer — CRUD operations against real Supabase.

Run: pytest tests/test_db_repository.py -v

These tests use your real Supabase project. They create test data,
verify it, then clean it up. Safe to run multiple times.
"""

import pytest
from app.db.client import get_admin_client
from app.db.repository import Repository


@pytest.fixture
def repo():
    """Create a repository using admin client (bypasses RLS for tests)."""
    return Repository(client=get_admin_client())


# ── Connection Test ──

def test_supabase_connection(repo):
    """Verify we can connect to Supabase and query a table."""
    result = repo._client.table("ca_firm").select("id", count="exact").limit(0).execute()
    assert result.count is not None  # connection works, got a count back


@pytest.fixture
def test_firm(repo):
    """Create a test firm and clean up after."""
    firm = repo.firms.create("Test Firm - Pytest", pan_no="AAATF0001A")
    yield firm
    # Cleanup: delete the firm (cascades to company, etc.)
    repo._client.table("ca_firm").delete().eq("id", firm.id).execute()


@pytest.fixture
def test_company(repo, test_firm):
    """Create a test company under the test firm."""
    company = repo.companies.create(
        firm_id=test_firm.id,
        company_name="Test Company Pvt Ltd",
        pan="AAATC0001A",
        company_type="company",
    )
    return company


@pytest.fixture
def test_run(repo, test_company):
    """Create a test reconciliation run."""
    run = repo.runs.create(
        company_id=test_company.id,
        financial_year="2024-25",
        quarter="ALL",
    )
    return run


# ── Firm Tests ──

def test_create_firm(repo, test_firm):
    """Create a firm and verify it exists."""
    assert test_firm.id  # UUID generated
    assert test_firm.name == "Test Firm - Pytest"
    assert test_firm.pan_no == "AAATF0001A"


def test_get_firm_by_id(repo, test_firm):
    """Retrieve a firm by ID."""
    found = repo.firms.get_by_id(test_firm.id)
    assert found is not None
    assert found.name == test_firm.name


def test_get_firm_not_found(repo):
    """Non-existent firm returns None."""
    found = repo.firms.get_by_id("00000000-0000-0000-0000-000000000000")
    assert found is None


# ── Company Tests ──

def test_create_company(repo, test_company, test_firm):
    """Create a company and verify it belongs to the firm."""
    assert test_company.id
    assert test_company.ca_firm_id == test_firm.id
    assert test_company.company_name == "Test Company Pvt Ltd"


def test_list_companies_by_firm(repo, test_company, test_firm):
    """List companies for a firm."""
    companies = repo.companies.list_by_firm(test_firm.id)
    assert len(companies) >= 1
    assert any(c.id == test_company.id for c in companies)


# ── Run Tests ──

def test_create_run(repo, test_run, test_company):
    """Create a reconciliation run."""
    assert test_run.id
    assert test_run.company_id == test_company.id
    assert test_run.financial_year == "2024-25"
    assert test_run.status == "uploading"


def test_update_run_status(repo, test_run):
    """Update run status."""
    updated = repo.runs.update_status(test_run.id, "processing")
    assert updated.status == "processing"


def test_list_runs_by_company(repo, test_run, test_company):
    """List runs for a company."""
    runs = repo.runs.list_by_company(test_company.id)
    assert len(runs) >= 1
    assert any(r.id == test_run.id for r in runs)


# ── Entry Tests ──

def test_bulk_insert_tds_entries(repo, test_run, test_company):
    """Bulk insert 50 TDS entries and query them back."""
    entries = [
        {
            "reconciliation_run_id": test_run.id,
            "company_id": test_company.id,
            "financial_year": "2024-25",
            "party_name": f"Vendor {i}",
            "pan": f"AAAPV{i:04d}A",
            "tds_section": "194C" if i % 2 == 0 else "194A",
            "tds_amount": 1000.0 + i * 100,
            "gross_amount": 50000.0 + i * 1000,
        }
        for i in range(50)
    ]

    count = repo.entries.bulk_insert_tds(entries)
    assert count == 50

    # Query back by run_id
    results = repo.entries.get_tds_by_run(test_run.id)
    assert len(results) == 50

    # Query by section
    section_194c = repo.entries.get_tds_by_section(test_run.id, "194C")
    section_194a = repo.entries.get_tds_by_section(test_run.id, "194A")
    assert len(section_194c) == 25  # even numbers
    assert len(section_194a) == 25  # odd numbers


def test_bulk_insert_ledger_entries(repo, test_run, test_company):
    """Bulk insert ledger entries."""
    entries = [
        {
            "reconciliation_run_id": test_run.id,
            "company_id": test_company.id,
            "financial_year": "2024-25",
            "party_name": f"Expense Vendor {i}",
            "expense_type": "Freight Charges" if i % 3 == 0 else "Interest Paid",
            "amount": 5000.0 + i * 500,
        }
        for i in range(30)
    ]

    count = repo.entries.bulk_insert_ledger(entries)
    assert count == 30

    results = repo.entries.get_ledger_by_run(test_run.id)
    assert len(results) == 30


# ── Match Tests ──

def test_bulk_insert_matches(repo, test_run):
    """Bulk insert match results."""
    matches = [
        {
            "reconciliation_run_id": test_run.id,
            "match_type": "exact_match" if i % 2 == 0 else "fuzzy_match",
            "confidence": 0.95 if i % 2 == 0 else 0.75,
            "amount": 10000.0 + i * 1000,
            "status": "auto_matched",
        }
        for i in range(10)
    ]

    count = repo.matches.bulk_insert(matches)
    assert count == 10

    results = repo.matches.get_by_run(test_run.id)
    assert len(results) == 10


# ── Progress Tests ──

def test_upsert_progress(repo, test_run):
    """Upsert run progress for a section."""
    progress = repo.progress.upsert(
        run_id=test_run.id,
        section="194A",
        total=36,
        matched=36,
        status="completed",
    )
    assert progress.section == "194A"
    assert progress.total == 36
    assert progress.matched == 36

    # Upsert again — should update, not duplicate
    updated = repo.progress.upsert(
        run_id=test_run.id,
        section="194A",
        total=36,
        matched=34,
        unmatched=2,
        status="completed",
    )
    assert updated.matched == 34
    assert updated.unmatched == 2

    # List all progress for run
    all_progress = repo.progress.list_by_run(test_run.id)
    # Should be 1 row (upsert, not insert)
    section_194a = [p for p in all_progress if p.section == "194A"]
    assert len(section_194a) == 1
