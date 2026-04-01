"""
Test Parser Agent — parse XLSX files and write to Supabase.

Run: pytest tests/test_parser_agent.py -v -s
"""

import pytest
from pathlib import Path
from app.db.client import get_admin_client
from app.db.repository import Repository
from app.pipeline.events import EventEmitter
from app.agents.parser_agent import ParserAgent

SAMPLE_FORM26 = "data/hpc/Form 26 - Deduction Register....xlsx"
SAMPLE_TALLY = "data/hpc/Tally extract.xlsx"


@pytest.fixture
def repo():
    return Repository(client=get_admin_client())


@pytest.fixture
def setup_firm_and_run(repo):
    """Create test firm, company, and run. Clean up after."""
    firm = repo.firms.create("Parser Test Firm", pan_no="AAAPF0001A")
    company = repo.companies.create(firm.id, "Parser Test Co", "AAAPTC001A")
    run = repo.runs.create(company.id, "2024-25")

    yield {"firm": firm, "company": company, "run": run}

    # Cleanup
    repo._client.table("ca_firm").delete().eq("id", firm.id).execute()


@pytest.fixture
def parser(repo, setup_firm_and_run):
    """Create a ParserAgent with test context."""
    ctx = setup_firm_and_run
    events = EventEmitter(run_id=ctx["run"].id)
    return ParserAgent(
        run_id=ctx["run"].id,
        company_id=ctx["company"].id,
        firm_id=ctx["firm"].id,
        financial_year="2024-25",
        db=repo,
        events=events,
    )


def test_parse_form26(parser, repo, setup_firm_and_run):
    """Parse Form 26 and verify entries in database."""
    if not Path(SAMPLE_FORM26).exists():
        pytest.skip("Sample Form 26 not found")

    run_id = setup_firm_and_run["run"].id
    entries = parser._parse_form26(SAMPLE_FORM26)

    assert len(entries) == 85  # same as MVP
    print(f"\nForm 26: {len(entries)} entries parsed")

    # Check entry structure
    e = entries[0]
    assert e["reconciliation_run_id"] == run_id
    assert e["company_id"] == setup_firm_and_run["company"].id
    assert e["party_name"]  # not empty
    assert e["tds_section"]  # not empty
    print(f"  Sample: {e['party_name']} | {e['tds_section']} | TDS={e['tds_amount']}")

    # Check sections match MVP
    sections = set(e["tds_section"] for e in entries)
    print(f"  Sections: {sorted(sections)}")
    assert "194A" in sections
    assert "194C" in sections


def test_parse_tally(parser, repo, setup_firm_and_run):
    """Parse Tally and verify entries."""
    if not Path(SAMPLE_TALLY).exists():
        pytest.skip("Sample Tally not found")

    entries = parser._parse_tally(SAMPLE_TALLY)
    print(f"\nTally: {len(entries)} total entries parsed")

    # Count by source
    sources = {}
    for e in entries:
        src = e.get("raw_data", {}).get("source", "unknown")
        sources[src] = sources.get(src, 0) + 1
    for src, count in sorted(sources.items()):
        print(f"  {src}: {count}")

    assert len(entries) > 100  # should be 700+ across all registers


def test_full_parse_and_insert(parser, repo, setup_firm_and_run):
    """Full pipeline: parse both files and insert into DB."""
    if not Path(SAMPLE_FORM26).exists() or not Path(SAMPLE_TALLY).exists():
        pytest.skip("Sample files not found")

    run_id = setup_firm_and_run["run"].id
    result = parser.run(SAMPLE_FORM26, SAMPLE_TALLY)

    print(f"\nFull parse result:")
    print(f"  TDS entries: {result['tds_count']}")
    print(f"  Ledger entries: {result['ledger_count']}")
    print(f"  Sections: {result['sections']}")

    assert result["tds_count"] == 85
    assert result["ledger_count"] > 100

    # Verify data is in database
    tds_in_db = repo.entries.get_tds_by_run(run_id)
    ledger_in_db = repo.entries.get_ledger_by_run(run_id)
    print(f"  TDS in DB: {len(tds_in_db)}")
    print(f"  Ledger in DB: {len(ledger_in_db)}")

    assert len(tds_in_db) == 85
    assert len(ledger_in_db) > 100

    # Check events were emitted
    events = parser.events.get_events()
    assert len(events) > 0
    print(f"  Events emitted: {len(events)}")
