"""
Pipeline Orchestrator — wires all 7 agents together.

    Learning (Pass 0) → Parser → Matcher → TDS Checker → Reporter

Each step:
1. Creates agent with shared context (run_id, company_id, db, events, llm)
2. Updates run status in DB
3. Runs the agent with error handling (partial results preserved)
4. Passes results to next agent
5. Emits SSE events at every stage (including LLM calls)

Usage:
    from app.pipeline.orchestrator import run_reconciliation
    result = run_reconciliation(
        company_id="abc-123", firm_id="def-456", financial_year="2024-25",
        form26_path="form26.xlsx", tally_path="tally.xlsx",
        db=repo, on_event=callback,
    )
"""

import time
import traceback

from app.db.repository import Repository
from app.pipeline.events import EventEmitter
from app.services.llm_client import LLMClient
from app.agents.parser_agent import ParserAgent
from app.agents.matcher_agent import MatcherAgent
from app.agents.tds_checker_agent import TdsCheckerAgent
from app.agents.reporter_agent import ReporterAgent
from app.agents.learning_agent import LearningAgent


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
    """Run the full TDS reconciliation pipeline with all 7 agents.

    Pipeline: Learning (Pass 0) → Parser → Matcher → TDS Checker → Reporter

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
        {run_id, events, summary, elapsed_s, errors}
    """
    start = time.time()
    errors = []

    # Create reconciliation run record
    run = db.runs.create(company_id, financial_year)
    run_id = run.id

    # Create scoped event emitter (for SSE streaming)
    events = EventEmitter(run_id=run_id, callback=on_event)

    # Create shared LLM client (all agents share this)
    llm = LLMClient(events=events)

    events.emit("Pipeline", f"Starting reconciliation (run: {run_id[:8]}...)", "info")
    if llm.available:
        events.emit("Pipeline", "LLM available — agents will use AI for ambiguous cases", "info")
    else:
        events.emit("Pipeline", "LLM not available — using deterministic logic only", "warning")

    # Shared context for all agents
    ctx = {
        "run_id": run_id,
        "company_id": company_id,
        "firm_id": firm_id,
        "financial_year": financial_year,
        "db": db,
        "events": events,
        "llm": llm,
    }

    parse_result = None
    match_result = None
    checker_result = None
    summary = None

    # ══════════════════════════════════════════════════════
    # Step 0: Learning Agent — apply learned rules (Pass 0)
    # ══════════════════════════════════════════════════════
    learning = LearningAgent(**ctx)
    learned_rules_result = None
    try:
        db.runs.update_status(run_id, "processing", processing_status="applying_rules")
        learned_rules_result = learning.apply_learned_rules([], [])
        # Rules will be applied AFTER parser creates entries — we just load them here
        if learned_rules_result.get("applied_count", 0) > 0:
            events.detail("Learning Agent", f"Loaded {learned_rules_result['applied_count']} learned rules")
    except Exception as e:
        events.warning("Learning Agent", f"Could not load learned rules: {str(e)[:80]}")

    # ══════════════════════════════════════════════════════
    # Step 1: Parser Agent
    # ══════════════════════════════════════════════════════
    try:
        db.runs.update_status(run_id, "processing", processing_status="parsing",
                              current_section="parsing")
        parser = ParserAgent(**ctx)
        parse_result = parser.run(form26_path, tally_path)
    except Exception as e:
        error_msg = f"Parser failed: {str(e)}"
        events.error("Parser Agent", error_msg)
        errors.append({"agent": "Parser", "error": error_msg, "traceback": traceback.format_exc()})
        db.runs.update_status(run_id, "review", processing_status="parser_failed")
        return _build_result(run_id, events, summary, start, errors)

    # ══════════════════════════════════════════════════════
    # Step 2: Matcher Agent (with Learning Pass 0 applied)
    # ══════════════════════════════════════════════════════
    try:
        db.runs.update_status(run_id, "processing", processing_status="matching",
                              current_section="matching")
        matcher = MatcherAgent(**ctx)
        match_result = matcher.run()
    except Exception as e:
        error_msg = f"Matcher failed: {str(e)}"
        events.error("Matcher Agent", error_msg)
        errors.append({"agent": "Matcher", "error": error_msg})
        # Continue to reporter with partial results
        match_result = {"matched": 0, "unmatched": 0, "total_form26": 0}

    # ══════════════════════════════════════════════════════
    # Step 3: TDS Checker Agent
    # ══════════════════════════════════════════════════════
    try:
        db.runs.update_status(run_id, "processing", processing_status="checking",
                              current_section="checking")
        checker = TdsCheckerAgent(**ctx)

        # Build checker inputs from DB + matcher's raw matches
        tds_entries = db.entries.get_tds_by_run(run_id)
        ledger_entries = db.entries.get_ledger_by_run(run_id)

        form26_for_checker = [{
            "vendor_name": e.party_name, "section": e.tds_section,
            "amount_paid": float(e.gross_amount or 0), "pan": e.pan or "",
        } for e in tds_entries]

        tally_for_checker = [{
            "party_name": e.party_name, "amount": float(e.amount),
            "date": e.invoice_date or "", "voucher_no": e.invoice_number or "",
            "expense_type": e.expense_type,
            "raw_data": e.raw_data if isinstance(e.raw_data, dict) else {},
        } for e in ledger_entries]

        raw_matches = matcher._last_matches if hasattr(matcher, '_last_matches') else []

        checker_result = checker.run(
            matches=raw_matches,
            form26_entries=form26_for_checker,
            tally_entries=tally_for_checker,
        )
    except Exception as e:
        error_msg = f"Checker failed: {str(e)}"
        events.error("TDS Checker", error_msg)
        errors.append({"agent": "Checker", "error": error_msg})
        checker_result = {"findings": [], "summary": {"total": 0, "errors": 0, "warnings": 0, "exposure": 0}}

    # ══════════════════════════════════════════════════════
    # Step 4: Reporter Agent
    # ══════════════════════════════════════════════════════
    try:
        db.runs.update_status(run_id, "processing", processing_status="reporting",
                              current_section="reporting")
        reporter = ReporterAgent(**ctx)
        summary = reporter.run(
            match_summary=match_result or {},
            checker_summary=checker_result or {},
            matches=raw_matches if 'raw_matches' in dir() else [],
            findings=checker_result.get("findings", []) if checker_result else [],
            output_dir=output_dir,
        )
    except Exception as e:
        error_msg = f"Reporter failed: {str(e)}"
        events.error("Reporter Agent", error_msg)
        errors.append({"agent": "Reporter", "error": error_msg})

    # ══════════════════════════════════════════════════════
    # Complete
    # ══════════════════════════════════════════════════════
    elapsed = time.time() - start
    final_status = "completed" if not errors else "review"
    db.runs.update_status(run_id, final_status, processing_status="done")

    if errors:
        events.warning("Pipeline", f"Completed with {len(errors)} error(s) in {elapsed:.1f}s")
    else:
        events.emit("Pipeline", f"Complete in {elapsed:.1f}s", "success")

    return _build_result(run_id, events, summary, start, errors)


def _build_result(run_id: str, events: EventEmitter, summary: dict | None,
                  start: float, errors: list) -> dict:
    """Build the final result dict."""
    return {
        "run_id": run_id,
        "events": events.get_events(),
        "summary": summary or {},
        "elapsed_s": round(time.time() - start, 2),
        "errors": errors,
    }
