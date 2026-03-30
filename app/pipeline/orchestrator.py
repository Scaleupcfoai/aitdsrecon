"""
Pipeline Orchestrator — runs the full reconciliation pipeline.

    Parser → Matcher → TDS Checker → Reporter

Each step:
1. Creates the agent with run context (run_id, company_id, db, events)
2. Runs the agent
3. Passes results to the next agent
4. Updates run_progress table

Usage:
    from app.pipeline.orchestrator import run_reconciliation
    result = run_reconciliation(
        company_id="abc-123",
        firm_id="def-456",
        financial_year="2024-25",
        form26_path="path/to/form26.xlsx",
        tally_path="path/to/tally.xlsx",
        db=repo,
        on_event=callback,  # for SSE streaming
    )
"""

import time

from app.db.repository import Repository
from app.pipeline.events import EventEmitter
from app.agents.parser_agent import ParserAgent
from app.agents.matcher_agent import MatcherAgent
from app.agents.tds_checker_agent import TdsCheckerAgent
from app.agents.reporter_agent import ReporterAgent


def run_reconciliation(
    company_id: str,
    firm_id: str,
    financial_year: str,
    form26_path: str,
    tally_path: str,
    db: Repository,
    on_event=None,
    output_dir: str = "data/reports",
) -> dict:
    """Run the full TDS reconciliation pipeline.

    Args:
        company_id: Which company's data
        firm_id: Which CA firm
        financial_year: e.g. "2024-25"
        form26_path: Path to Form 26 XLSX
        tally_path: Path to Tally XLSX
        db: Repository instance
        on_event: Callback for each event (for SSE streaming)
        output_dir: Where to write report files

    Returns:
        {run_id, events, summary, elapsed_s}
    """
    start = time.time()

    # Create reconciliation run
    run = db.runs.create(company_id, financial_year)
    run_id = run.id

    # Create event emitter scoped to this run
    events = EventEmitter(run_id=run_id, callback=on_event)

    events.emit("Pipeline", f"Starting reconciliation (run: {run_id[:8]}...)", "info")

    # Shared agent context
    ctx = {
        "run_id": run_id,
        "company_id": company_id,
        "firm_id": firm_id,
        "financial_year": financial_year,
        "db": db,
        "events": events,
    }

    # ── Step 1: Parser ──
    parser = ParserAgent(**ctx)
    db.runs.update_status(run_id, "processing", current_section="parsing")
    parse_result = parser.run(form26_path, tally_path)

    # ── Step 2: Matcher ──
    matcher = MatcherAgent(**ctx)
    db.runs.update_status(run_id, "processing", current_section="matching")
    match_result = matcher.run()

    # ── Step 3: TDS Checker ──
    checker = TdsCheckerAgent(**ctx)
    db.runs.update_status(run_id, "processing", current_section="checking")

    # Reload entries from DB for checker (in the format it expects)
    tds_entries = db.entries.get_tds_by_run(run_id)
    ledger_entries = db.entries.get_ledger_by_run(run_id)
    matches_from_db = db.matches.get_by_run(run_id)

    # The checker needs the raw match dicts with form26_entry and tally_entries
    # For now, pass the matcher's internal format via a workaround
    # TODO: refactor checker to read from DB directly
    checker_result = checker.run(
        matches=matcher._last_matches if hasattr(matcher, '_last_matches') else [],
        form26_entries=[{
            "vendor_name": e.party_name, "section": e.tds_section,
            "amount_paid": float(e.gross_amount or 0), "pan": e.pan or "",
        } for e in tds_entries],
        tally_entries=[{
            "party_name": e.party_name, "amount": float(e.amount),
            "date": e.invoice_date or "", "voucher_no": e.invoice_number or "",
            "expense_type": e.expense_type,
            "raw_data": e.raw_data if isinstance(e.raw_data, dict) else {},
        } for e in ledger_entries],
    )

    # ── Step 4: Reporter ──
    reporter = ReporterAgent(**ctx)
    db.runs.update_status(run_id, "processing", current_section="reporting")
    summary = reporter.run(
        match_summary=match_result,
        checker_summary=checker_result,
        matches=matcher._last_matches if hasattr(matcher, '_last_matches') else [],
        findings=checker_result.get("findings", []),
        output_dir=output_dir,
    )

    elapsed = time.time() - start
    events.emit("Pipeline", f"Complete in {elapsed:.1f}s", "success")

    return {
        "run_id": run_id,
        "events": events.get_events(),
        "summary": summary,
        "elapsed_s": round(elapsed, 2),
    }
