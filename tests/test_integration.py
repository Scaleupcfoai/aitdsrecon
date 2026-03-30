"""
Integration test — full pipeline end-to-end.

Tests the complete flow: upload → parse → match → check → report.
Requires Supabase service_role key and sample data files.

Run: pytest tests/test_integration.py -v -s
"""

import pytest
from pathlib import Path

from app.db.repository import Repository
from app.pipeline.orchestrator import run_reconciliation
from app.pipeline.events import EventEmitter

SAMPLE_FORM26 = "data/hpc/Form 26 - Deduction Register....xlsx"
SAMPLE_TALLY = "data/hpc/Tally extract.xlsx"


@pytest.fixture
def integration_setup(repo):
    """Create firm + company for integration test."""
    firm = repo.firms.create("E2E Test Firm", pan_no="AAAE2E001A")
    company = repo.companies.create(firm.id, "E2E Test Company", "AAAE2EC01A")
    yield {"firm": firm, "company": company, "repo": repo}
    # Cleanup
    try:
        repo._client.table("ca_firm").delete().eq("id", firm.id).execute()
    except Exception:
        pass


def test_full_pipeline_e2e(integration_setup):
    """Full pipeline: parse → match → check → report."""
    if not Path(SAMPLE_FORM26).exists() or not Path(SAMPLE_TALLY).exists():
        pytest.skip("Sample files not found")

    ctx = integration_setup
    repo = ctx["repo"]
    firm = ctx["firm"]
    company = ctx["company"]

    events_log = []

    def on_event(event):
        events_log.append(event)

    result = run_reconciliation(
        company_id=company.id,
        firm_id=firm.id,
        financial_year="2024-25",
        form26_path=SAMPLE_FORM26,
        tally_path=SAMPLE_TALLY,
        db=repo,
        on_event=on_event,
    )

    # Verify result structure
    assert "run_id" in result
    assert "events" in result
    assert "summary" in result
    assert "elapsed_s" in result
    assert result["elapsed_s"] > 0

    run_id = result["run_id"]
    print(f"\n=== E2E Pipeline Result ===")
    print(f"  Run ID: {run_id}")
    print(f"  Elapsed: {result['elapsed_s']}s")
    print(f"  Errors: {result.get('errors', [])}")

    # Verify events were emitted
    assert len(events_log) > 10  # should have many events
    event_types = set(e["type"] for e in events_log)
    assert "agent_start" in event_types
    assert "agent_done" in event_types
    print(f"  Events: {len(events_log)} total, types: {sorted(event_types)}")

    # Verify data in database
    tds_entries = repo.entries.get_tds_by_run(run_id)
    ledger_entries = repo.entries.get_ledger_by_run(run_id)
    matches = repo.matches.get_by_run(run_id)
    progress = repo.progress.list_by_run(run_id)

    print(f"  TDS entries in DB: {len(tds_entries)}")
    print(f"  Ledger entries in DB: {len(ledger_entries)}")
    print(f"  Matches in DB: {len(matches)}")
    print(f"  Progress rows: {len(progress)}")

    assert len(tds_entries) > 0, "No TDS entries parsed"
    assert len(ledger_entries) > 0, "No ledger entries parsed"

    # Verify run status
    run = repo.runs.get_by_id(run_id)
    assert run is not None
    assert run.status in ("completed", "review")
    print(f"  Run status: {run.status}")

    # Check for LLM events (if LLM was available)
    llm_events = [e for e in events_log if e["type"] in ("llm_call", "llm_response", "llm_insight")]
    print(f"  LLM events: {len(llm_events)}")


def test_pipeline_with_missing_files(integration_setup):
    """Pipeline with non-existent files fails gracefully."""
    ctx = integration_setup
    repo = ctx["repo"]

    result = run_reconciliation(
        company_id=ctx["company"].id,
        firm_id=ctx["firm"].id,
        financial_year="2024-25",
        form26_path="/nonexistent/form26.xlsx",
        tally_path="/nonexistent/tally.xlsx",
        db=repo,
    )

    # Should have errors but not crash
    assert "errors" in result
    assert len(result["errors"]) > 0
    print(f"Graceful failure: {result['errors'][0]['agent']} — {result['errors'][0]['error'][:60]}")


def test_run_listed_after_pipeline(integration_setup):
    """After pipeline runs, the run appears in list_by_company."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample files not found")

    ctx = integration_setup
    repo = ctx["repo"]

    result = run_reconciliation(
        company_id=ctx["company"].id,
        firm_id=ctx["firm"].id,
        financial_year="2024-25",
        form26_path=SAMPLE_FORM26,
        tally_path=SAMPLE_TALLY,
        db=repo,
    )

    runs = repo.runs.list_by_company(ctx["company"].id)
    assert len(runs) >= 1
    assert any(r.id == result["run_id"] for r in runs)
    print(f"Run {result['run_id'][:8]}... found in company run list")
