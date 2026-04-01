"""
TDS Reconciliation — Orchestrator
==================================
Single entry point to run the full reconciliation pipeline:

    Parser → Matcher → TDS Checker → Reporter

Usage:
    python reconcile.py                          # Use default paths
    python reconcile.py <form26.xlsx> <tally.xlsx>  # Custom input files

Pipeline:
    1. Parser Agent    — Parse XLSX files → normalized JSON
    2. Matcher Agent   — Match Form 26 ↔ Tally entries (5-pass engine)
    3. TDS Checker     — Validate compliance (section, rate, base, threshold, missing)
    4. Reporter Agent  — Generate summary + CSV reports with remediation

All outputs go to data/results/.
"""

import json
import sys
import time
from pathlib import Path

from agents.event_logger import EventLogger, reset_logger


def run_pipeline(form26_path: str | None = None, tally_path: str | None = None,
                 form24_path: str | None = None, event_callback=None) -> dict:
    """Run the full TDS reconciliation pipeline.

    Args:
        event_callback: Optional callback for real-time SSE streaming.
                        Called with each event dict as it happens.

    Returns a dict with: {events, summary, results_dir}
    """
    logger = reset_logger()
    if event_callback:
        logger.set_callback(event_callback)
    base = Path(__file__).parent
    parsed_dir = base / "data" / "parsed"
    results_dir = base / "data" / "results"
    rules_dir = base / "data" / "rules"

    parsed_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("TDS RECONCILIATION PIPELINE")
    print("=" * 60)

    start = time.time()

    # ---- Step 1: Parser ----
    logger.agent_start("Parser Agent", "Starting Parser Agent...")
    if form26_path and tally_path:
        from agents.parser_agent import run as parser_run
        parser_run(form26_path, tally_path, str(parsed_dir), form24_path=form24_path)
        logger.success("Parser Agent", "Parsed input files")
    else:
        if not (parsed_dir / "parsed_form26.json").exists():
            logger.error("Parser Agent", "parsed_form26.json not found")
            return {"events": logger.get_events(), "error": "Missing parsed data"}
        if not (parsed_dir / "parsed_tally.json").exists():
            logger.error("Parser Agent", "parsed_tally.json not found")
            return {"events": logger.get_events(), "error": "Missing parsed data"}

        # Emit parsing details from existing files
        with open(parsed_dir / "parsed_form26.json") as f:
            f26 = json.load(f)
        with open(parsed_dir / "parsed_tally.json") as f:
            tally = json.load(f)

        f26_count = len(f26.get("entries", []))
        sections = set(e["section"] for e in f26.get("entries", []))
        jr_count = len(tally.get("journal_register", {}).get("entries", []))
        gst_count = len(tally.get("purchase_gst_exp_register", {}).get("entries", []))
        pr_count = len(tally.get("purchase_register", {}).get("entries", []))

        f24_count = sum(1 for e in f26.get("entries", []) if e.get("source") == "form24")
        f26_only = f26_count - f24_count
        if f24_count > 0:
            logger.detail("Parser Agent", f"Form 26: {f26_only} entries, Form 24: {f24_count} salary entries")
        else:
            logger.detail("Parser Agent", f"Form 26: {f26_count} entries across {len(sections)} sections")
        logger.detail("Parser Agent", f"Sections found: {', '.join(sorted(sections))}")
        logger.detail("Parser Agent", f"Tally Journal Register: {jr_count} entries")
        logger.detail("Parser Agent", f"Tally GST Expense Register: {gst_count} entries")
        logger.detail("Parser Agent", f"Tally Purchase Register: {pr_count} entries")

        # Count unique vendor names
        vendors = set(e.get("vendor_name", "") for e in f26.get("entries", []))
        tally_vendors = set()
        for e in tally.get("journal_register", {}).get("entries", []):
            if e.get("loan_party"):
                tally_vendors.add(e["loan_party"])
            if e.get("particulars"):
                tally_vendors.add(e["particulars"])
        for e in tally.get("purchase_gst_exp_register", {}).get("entries", []):
            if e.get("particulars"):
                tally_vendors.add(e["particulars"])
        logger.detail("Parser Agent", f"Form 26 vendors: {len(vendors)} unique")
        logger.detail("Parser Agent", f"Tally vendors: {len(tally_vendors)} unique")

    logger.agent_done("Parser Agent", "Parsing complete")

    # ---- Step 2: Matcher ----
    logger.agent_start("Matcher Agent", "Starting Matcher Agent...")
    from agents.matcher_agent import run as matcher_run

    def matcher_event(agent, message, type="detail"):
        logger.emit(agent, message, type)

    match_results = matcher_run(str(parsed_dir), str(results_dir),
                                rules_dir=str(rules_dir), event_callback=matcher_event)

    summary = match_results.get("summary", {})
    learned = match_results.get("learned_rules", {})
    if learned.get("rules_loaded", 0) > 0:
        logger.detail("Matcher Agent", f"Loaded {learned['rules_loaded']} learned rules from previous runs")
        if learned.get("below_threshold_entries", 0):
            logger.detail("Matcher Agent", f"{learned['below_threshold_entries']} below-threshold entries resolved")

    matched = summary.get("form26_matched", 0)
    below_threshold = summary.get("below_threshold_resolved", 0)
    total_resolved = summary.get("total_resolved", matched)
    total = summary.get("form26_total", 0)
    pct = (matched / total * 100) if total > 0 else 0
    logger.success("Matcher Agent", f"Result: {matched}/{total} matched with TDS ({pct:.0f}%)")
    if below_threshold:
        logger.success("Matcher Agent", f"Total resolved: {total_resolved} entries ({matched} TDS + {below_threshold} exempt)")
    logger.agent_done("Matcher Agent", "Matching complete")

    # Ask user about unmatched entries if any exist
    unmatched_count = summary.get("form26_unmatched", 0)
    if unmatched_count > 0:
        answer = logger.question(
            "Matcher Agent",
            "q_unmatched",
            f"{unmatched_count} entries could not be matched. How should I proceed?",
            options=[
                {"id": "flag_review", "label": "Flag for review", "description": "Add to manual review queue for human verification"},
                {"id": "mark_exempt", "label": "Mark as exempt", "description": "Treat as below-threshold or exempt entries"},
                {"id": "retry_fuzzy", "label": "Retry with relaxed matching", "description": "Lower similarity threshold from 40% to 25%"},
            ],
            allow_text_input=True,
            multi_select=False,
            timeout=30,  # 30s timeout for demo — auto-continue if no answer
        )
        if answer:
            selected = answer.get("selected", [])
            logger.detail("Matcher Agent", f"User decided: {', '.join(selected)}")
            if answer.get("text_input"):
                logger.detail("Matcher Agent", f"User note: {answer['text_input']}")
        else:
            logger.detail("Matcher Agent", "Auto-continuing: flagging unmatched entries for review")

    # ---- Step 3: TDS Checker ----
    logger.agent_start("TDS Checker", "Starting TDS Checker Agent...")
    from agents.tds_checker_agent import run as checker_run

    def checker_event(agent, message, type="detail"):
        logger.emit(agent, message, type)

    checker_results = checker_run(str(parsed_dir), str(results_dir), event_callback=checker_event)

    findings = checker_results.get("findings", [])
    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    exposure = sum(f.get("aggregate_amount", 0) for f in errors)
    logger.success("TDS Checker", f"Complete: {len(errors)} errors, {len(warnings)} warnings, \u20b9{exposure:,.0f} exposure")
    logger.agent_done("TDS Checker", "Compliance checks complete")

    # ---- Step 4: Reporter ----
    logger.agent_start("Reporter Agent", "Generating reports...")
    from agents.reporter_agent import run as reporter_run
    report = reporter_run(str(parsed_dir), str(results_dir))
    logger.detail("Reporter Agent", "reconciliation_summary.json \u2014 Executive summary")
    logger.detail("Reporter Agent", "reconciliation_report.csv \u2014 Full match report")
    logger.detail("Reporter Agent", "findings_report.csv \u2014 Findings + remediation")
    logger.agent_done("Reporter Agent", "Reports generated")

    elapsed = time.time() - start
    logger.emit("Pipeline", f"Complete in {elapsed:.1f}s", "success")

    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETE \u2014 {elapsed:.1f}s")
    print(f"{'=' * 60}")

    report_summary = report.get("summary", {})
    c = report_summary.get("compliance", {})
    status = "CLEAN" if c.get("clean_bill") else "ACTION REQUIRED"
    print(f"Status: {status}")

    return {
        "events": logger.get_events(),
        "summary": report_summary,
        "results_dir": str(results_dir),
        "elapsed_s": round(elapsed, 2),
    }


if __name__ == "__main__":
    if len(sys.argv) == 3:
        run_pipeline(sys.argv[1], sys.argv[2])
    elif len(sys.argv) == 1:
        run_pipeline()
    else:
        print("Usage:")
        print("  python reconcile.py                            # Use existing parsed data")
        print("  python reconcile.py <form26.xlsx> <tally.xlsx> # Parse + reconcile")
        sys.exit(1)
