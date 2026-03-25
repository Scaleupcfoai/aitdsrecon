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


def run_pipeline(form26_path: str | None = None, tally_path: str | None = None) -> dict:
    """Run the full TDS reconciliation pipeline.

    Returns a dict with: {events, summary, results_dir}
    """
    logger = reset_logger()
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
        parser_run(form26_path, tally_path, str(parsed_dir))
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
    match_results = matcher_run(str(parsed_dir), str(results_dir), rules_dir=str(rules_dir))

    # Emit matcher details from results
    summary = match_results.get("summary", {})
    by_pass = summary.get("matches_by_pass", {})
    learned = match_results.get("learned_rules", {})

    if learned.get("rules_loaded", 0) > 0:
        logger.detail("Matcher Agent", f"Pass 0: {learned['rules_loaded']} learned rules loaded")
        if learned.get("below_threshold_entries", 0):
            logger.detail("Matcher Agent", f"  → {learned['below_threshold_entries']} below-threshold entries marked")
    if by_pass.get("pass1_exact", 0):
        logger.detail("Matcher Agent", f"Pass 1: {by_pass['pass1_exact']} exact matches (name + amount + date)")
    if by_pass.get("pass2_gst_adjusted", 0):
        logger.detail("Matcher Agent", f"Pass 2: {by_pass['pass2_gst_adjusted']} GST-adjusted matches")
    if by_pass.get("pass3_exempt", 0):
        logger.detail("Matcher Agent", f"Pass 3: {by_pass['pass3_exempt']} exempt entries filtered")
    if by_pass.get("pass4_fuzzy", 0):
        logger.detail("Matcher Agent", f"Pass 4: {by_pass['pass4_fuzzy']} fuzzy matches (name similarity > 40%)")
    if by_pass.get("pass5_aggregated", 0):
        logger.detail("Matcher Agent", f"Pass 5: {by_pass['pass5_aggregated']} aggregated matches")

    matched = summary.get("form26_matched", 0)
    total = summary.get("form26_total", 0)
    pct = (matched / total * 100) if total > 0 else 0
    logger.success("Matcher Agent", f"Result: {matched}/{total} matched ({pct:.0f}%)")
    logger.agent_done("Matcher Agent", "Matching complete")

    # ---- Step 3: TDS Checker ----
    logger.agent_start("TDS Checker", "Starting TDS Checker Agent...")
    from agents.tds_checker_agent import run as checker_run
    checker_results = checker_run(str(parsed_dir), str(results_dir))

    findings = checker_results.get("findings", [])
    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]

    for f in findings:
        sev = f.get("severity", "info")
        vendor = f.get("vendor", "Unknown")
        msg = f.get("message", "")
        # Truncate long messages
        short_msg = msg[:120] + "..." if len(msg) > 120 else msg
        if sev == "error":
            logger.error("TDS Checker", f"{vendor}: {short_msg}")
        elif sev == "warning":
            logger.warning("TDS Checker", f"{vendor}: {short_msg}")
        else:
            logger.detail("TDS Checker", f"{vendor}: {short_msg}")

    exposure = sum(f.get("aggregate_amount", 0) for f in errors)
    logger.success("TDS Checker", f"Complete: {len(errors)} errors, {len(warnings)} warnings, ₹{exposure:,.0f} exposure")
    logger.agent_done("TDS Checker", "Compliance checks complete")

    # ---- Step 4: Reporter ----
    logger.agent_start("Reporter Agent", "Generating reports...")
    from agents.reporter_agent import run as reporter_run
    report = reporter_run(str(parsed_dir), str(results_dir))
    logger.detail("Reporter Agent", "reconciliation_summary.json — Executive summary")
    logger.detail("Reporter Agent", "reconciliation_report.csv — Full match report")
    logger.detail("Reporter Agent", "findings_report.csv — Findings + remediation")
    logger.agent_done("Reporter Agent", "Reports generated")

    elapsed = time.time() - start
    logger.emit("Pipeline", f"Complete in {elapsed:.1f}s", "success")

    print(f"\n{'=' * 60}")
    print(f"PIPELINE COMPLETE — {elapsed:.1f}s")
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
