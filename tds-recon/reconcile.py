"""
TDS Reconciliation — Orchestrator (v2)
=======================================
Gated orchestrator with routing decisions and human review queue.

Architecture:
    Orchestrator
    ├─ validate_inputs(form26, tally)     ← gate: are files parseable?
    ├─ run_parser(form26, tally)          ← deterministic
    │   └─ check: parsed entries > 0?     ← gate
    ├─ run_matcher(parsed, rules)         ← deterministic (5-pass)
    │   └─ check: unmatched count         ← routing decision
    │       ├─ 0 unmatched → skip checker
    │       └─ N unmatched → continue
    ├─ run_checker(matched, parsed)       ← deterministic
    │   └─ check: findings severity       ← routing decision
    │       ├─ all OK → clean report
    │       └─ errors found → flag for review
    ├─ run_reporter(all_results)          ← deterministic
    └─ return {status, results, human_review_queue}

Usage:
    python reconcile.py                          # Use existing parsed data
    python reconcile.py <form26.xlsx> <tally.xlsx>  # Parse + reconcile

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
# ---------------------------------------------------------------------------
# Pipeline State — passed between stages
# ---------------------------------------------------------------------------

def _initial_state() -> dict:
    """Create the initial pipeline state object."""
    return {
        "status": "started",
        "stages_completed": [],
        "gates_passed": [],
        "gates_failed": [],
        "routing_decisions": [],
        "human_review_queue": [],
        "results": {},
        "errors": [],
        "timing": {},
    }


# ---------------------------------------------------------------------------
# Gate: Validate Inputs
# ---------------------------------------------------------------------------

def validate_inputs(
    form26_path: str | None,
    tally_path: str | None,
    parsed_dir: Path,
) -> dict:
    """Gate: Are input files present and parseable?

    Returns:
        {passed: bool, mode: "parse"|"cached", detail: str}
    """
    # Mode 1: Fresh parse from XLSX
    if form26_path and tally_path:
        issues = []
        if not Path(form26_path).exists():
            issues.append(f"Form 26 file not found: {form26_path}")
        if not Path(tally_path).exists():
            issues.append(f"Tally file not found: {tally_path}")

        if issues:
            return {"passed": False, "mode": "parse", "detail": "; ".join(issues)}

        # Check file extensions
        for fpath, label in [(form26_path, "Form 26"), (tally_path, "Tally")]:
            ext = Path(fpath).suffix.lower()
            if ext not in (".xlsx", ".xls"):
                issues.append(f"{label} has unexpected extension '{ext}' (expected .xlsx)")

        if issues:
            return {"passed": False, "mode": "parse", "detail": "; ".join(issues)}

        return {"passed": True, "mode": "parse", "detail": "XLSX files validated"}

    # Mode 2: Use cached parsed data
    f26_json = parsed_dir / "parsed_form26.json"
    tally_json = parsed_dir / "parsed_tally.json"
    issues = []

    if not f26_json.exists():
        issues.append(f"parsed_form26.json not found in {parsed_dir}")
    if not tally_json.exists():
        issues.append(f"parsed_tally.json not found in {parsed_dir}")

    if issues:
        return {"passed": False, "mode": "cached", "detail": "; ".join(issues)}

    # Validate JSON is loadable and non-empty
    try:
        with open(f26_json) as f:
            f26_data = json.load(f)
        if not f26_data.get("entries"):
            issues.append("parsed_form26.json has no entries")
    except (json.JSONDecodeError, KeyError) as e:
        issues.append(f"parsed_form26.json is invalid: {e}")

    try:
        with open(tally_json) as f:
            tally_data = json.load(f)
        has_data = (
            tally_data.get("journal_register", {}).get("entries")
            or tally_data.get("purchase_gst_exp_register", {}).get("entries")
            or tally_data.get("purchase_register", {}).get("entries")
        )
        if not has_data:
            issues.append("parsed_tally.json has no entries in any register")
    except (json.JSONDecodeError, KeyError) as e:
        issues.append(f"parsed_tally.json is invalid: {e}")

    if issues:
        return {"passed": False, "mode": "cached", "detail": "; ".join(issues)}

    return {"passed": True, "mode": "cached", "detail": "Cached parsed data validated"}


# ---------------------------------------------------------------------------
# Gate: Check parsed output
# ---------------------------------------------------------------------------

def check_parsed_output(parsed_dir: Path) -> dict:
    """Gate: Did the parser produce usable output?

    Returns:
        {passed: bool, form26_count: int, tally_count: int, detail: str}
    """
    try:
        with open(parsed_dir / "parsed_form26.json") as f:
            f26 = json.load(f)
        with open(parsed_dir / "parsed_tally.json") as f:
            tally = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return {"passed": False, "form26_count": 0, "tally_count": 0,
                "detail": f"Parser output unreadable: {e}"}

    f26_count = len(f26.get("entries", []))
    journal_count = len(tally.get("journal_register", {}).get("entries", []))
    gst_exp_count = len(tally.get("purchase_gst_exp_register", {}).get("entries", []))
    purchase_count = len(tally.get("purchase_register", {}).get("entries", []))
    tally_count = journal_count + gst_exp_count + purchase_count

    if f26_count == 0:
        return {"passed": False, "form26_count": 0, "tally_count": tally_count,
                "detail": "Parser produced 0 Form 26 entries"}
    if tally_count == 0:
        return {"passed": False, "form26_count": f26_count, "tally_count": 0,
                "detail": "Parser produced 0 Tally entries"}

    return {
        "passed": True,
        "form26_count": f26_count,
        "tally_count": tally_count,
        "tally_breakdown": {
            "journal": journal_count,
            "gst_exp": gst_exp_count,
            "purchase": purchase_count,
        },
        "detail": f"{f26_count} Form 26 + {tally_count} Tally entries",
    }


# ---------------------------------------------------------------------------
# Routing: After Matcher
# ---------------------------------------------------------------------------

def route_after_matcher(match_results: dict) -> dict:
    """Routing decision after matching: should we run the checker?

    Returns:
        {run_checker: bool, reason: str, unmatched_count: int, match_rate: float}
    """
    summary = match_results.get("summary", {})
    total = summary.get("form26_total", 0)
    matched = summary.get("form26_matched", 0)
    unmatched = summary.get("form26_unmatched", 0)
    match_rate = round(matched / max(total, 1) * 100, 1)

    if unmatched == 0 and total > 0:
        return {
            "run_checker": True,
            "reason": f"100% match rate ({matched}/{total}) — run checker for compliance validation",
            "unmatched_count": 0,
            "match_rate": match_rate,
        }
    elif unmatched > 0:
        return {
            "run_checker": True,
            "reason": f"{unmatched} unmatched entries ({match_rate}% rate) — checker needed",
            "unmatched_count": unmatched,
            "match_rate": match_rate,
        }
    else:
        return {
            "run_checker": False,
            "reason": "No entries to check (total=0)",
            "unmatched_count": 0,
            "match_rate": 0,
        }


# ---------------------------------------------------------------------------
# Routing: After Checker
# ---------------------------------------------------------------------------

def route_after_checker(checker_results: dict) -> dict:
    """Routing decision after compliance checks: clean report or flag for review?

    Returns:
        {status: "clean"|"needs_review", severity: str, review_items: list}
    """
    summary = checker_results.get("summary", {})
    findings = checker_results.get("findings", [])
    errors = summary.get("by_severity", {}).get("error", 0)
    warnings = summary.get("by_severity", {}).get("warning", 0)

    review_items = []
    for f in findings:
        if f["severity"] in ("error", "warning"):
            review_items.append({
                "check": f["check"],
                "severity": f["severity"],
                "vendor": f.get("vendor", ""),
                "message": f["message"],
                "section": f.get("form26_section", f.get("expected_section", "")),
            })

    if errors > 0:
        return {
            "status": "needs_review",
            "severity": "error",
            "reason": f"{errors} error(s) and {warnings} warning(s) found",
            "review_items": review_items,
        }
    elif warnings > 0:
        return {
            "status": "needs_review",
            "severity": "warning",
            "reason": f"{warnings} warning(s) found (no errors)",
            "review_items": review_items,
        }
    else:
        return {
            "status": "clean",
            "severity": "none",
            "reason": "All compliance checks passed",
            "review_items": [],
        }


# ---------------------------------------------------------------------------
# Build Human Review Queue
# ---------------------------------------------------------------------------

def build_review_queue(
    match_results: dict,
    checker_routing: dict | None,
) -> list[dict]:
    """Assemble the human review queue from unmatched entries + compliance findings.

    This is the key output — tells the CA/accountant exactly what needs attention.
    """
    queue = []

    # 1. Unmatched Form 26 entries → need manual matching
    for entry in match_results.get("unmatched_form26", []):
        queue.append({
            "type": "unmatched_form26",
            "priority": "high",
            "vendor": entry.get("vendor_name", ""),
            "section": entry.get("section", ""),
            "amount": entry.get("amount_paid", 0),
            "date": str(entry.get("amount_paid_date", ""))[:10],
            "action_needed": "Find matching Tally entry or confirm TDS is correct",
            "source": entry,
        })

    # 2. Unmatched Tally entries → potential missing TDS
    for entry in match_results.get("unmatched_tally_194a", []):
        queue.append({
            "type": "unmatched_tally",
            "priority": "medium",
            "vendor": entry.get("party_name", ""),
            "section": "194A",
            "amount": entry.get("amount", 0),
            "action_needed": "Verify if TDS was deducted for this interest payment",
            "source": entry,
        })

    for entry in match_results.get("unmatched_tally_194c", []):
        queue.append({
            "type": "unmatched_tally",
            "priority": "medium",
            "vendor": entry.get("party_name", ""),
            "section": "194C",
            "amount": entry.get("amount", 0),
            "action_needed": "Verify if TDS was deducted for this contractor payment",
            "source": entry,
        })

    # 3. Compliance findings that need review
    if checker_routing and checker_routing.get("review_items"):
        for item in checker_routing["review_items"]:
            priority = "high" if item["severity"] == "error" else "medium"
            queue.append({
                "type": "compliance_finding",
                "priority": priority,
                "vendor": item.get("vendor", ""),
                "section": item.get("section", ""),
                "check": item["check"],
                "action_needed": item["message"],
            })

    # Sort: high priority first, then by vendor
    priority_order = {"high": 0, "medium": 1, "low": 2}
    queue.sort(key=lambda x: (priority_order.get(x["priority"], 9), x.get("vendor", "")))

    return queue


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run_pipeline(form26_path: str | None = None, tally_path: str | None = None) -> dict:
    """Run the gated TDS reconciliation pipeline.

    Returns:
        {
            status: "complete" | "needs_review" | "failed",
            results: {match, checker, report summaries},
            human_review_queue: [...items needing attention...],
            pipeline: {stages, gates, routing decisions, timing}
        }
    """
    base = Path(__file__).parent
    parsed_dir = base / "data" / "parsed"
    results_dir = base / "data" / "results"
    rules_dir = base / "data" / "rules"

    parsed_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    state = _initial_state()
    pipeline_start = time.time()

    print("=" * 60)
    print("TDS RECONCILIATION PIPELINE (v2 — Gated Orchestrator)")
    print("=" * 60)

    # ================================================================
    # GATE 1: Validate Inputs
    # ================================================================
    print("─" * 60)
    print("GATE 1: VALIDATE INPUTS")
    print("─" * 60)

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

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
