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

    # Ensure output directories exist
    parsed_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    state = _initial_state()
    pipeline_start = time.time()

    print("=" * 60)
    print("TDS RECONCILIATION PIPELINE (v2 — Gated Orchestrator)")
    print("=" * 60)
    print(f"Sections: 194A (Interest), 194C (Contractor)")
    print(f"FY: 2024-25 | AY: 2025-26")
    print()

    # ================================================================
    # GATE 1: Validate Inputs
    # ================================================================
    print("─" * 60)
    print("GATE 1: VALIDATE INPUTS")
    print("─" * 60)

    gate1 = validate_inputs(form26_path, tally_path, parsed_dir)
    print(f"  Mode: {gate1['mode']}")
    print(f"  Result: {'PASS' if gate1['passed'] else 'FAIL'} — {gate1['detail']}")

    if not gate1["passed"]:
        state["gates_failed"].append({"gate": "validate_inputs", **gate1})
        state["status"] = "failed"
        state["errors"].append(gate1["detail"])
        print(f"\n  PIPELINE ABORTED: {gate1['detail']}")
        return _finalize(state, pipeline_start)

    state["gates_passed"].append({"gate": "validate_inputs", **gate1})
    print()

    # ================================================================
    # STAGE 1: Parser Agent
    # ================================================================
    print("─" * 60)
    print("STAGE 1/4: PARSER AGENT")
    print("─" * 60)

    stage_start = time.time()
    if gate1["mode"] == "parse":
        from agents.parser_agent import run as parser_run
        parser_run(form26_path, tally_path, str(parsed_dir))
    else:
        print("  Skipped (using cached parsed data)")

    state["timing"]["parser"] = round(time.time() - stage_start, 2)
    state["stages_completed"].append("parser")
    print()

    # ================================================================
    # GATE 2: Check Parsed Output
    # ================================================================
    print("─" * 60)
    print("GATE 2: PARSED OUTPUT CHECK")
    print("─" * 60)

    gate2 = check_parsed_output(parsed_dir)
    print(f"  Form 26: {gate2['form26_count']} entries")
    print(f"  Tally:   {gate2['tally_count']} entries")
    if gate2.get("tally_breakdown"):
        tb = gate2["tally_breakdown"]
        print(f"    Journal: {tb['journal']}, GST Exp: {tb['gst_exp']}, Purchase: {tb['purchase']}")
    print(f"  Result: {'PASS' if gate2['passed'] else 'FAIL'} — {gate2['detail']}")

    if not gate2["passed"]:
        state["gates_failed"].append({"gate": "parsed_output_check", **gate2})
        state["status"] = "failed"
        state["errors"].append(gate2["detail"])
        print(f"\n  PIPELINE ABORTED: {gate2['detail']}")
        return _finalize(state, pipeline_start)

    state["gates_passed"].append({"gate": "parsed_output_check", **gate2})
    print()

    # ================================================================
    # STAGE 2: Matcher Agent
    # ================================================================
    print("─" * 60)
    print("STAGE 2/4: MATCHER AGENT")
    print("─" * 60)

    stage_start = time.time()
    from agents.matcher_agent import run as matcher_run
    match_results = matcher_run(str(parsed_dir), str(results_dir), rules_dir=str(rules_dir))
    state["timing"]["matcher"] = round(time.time() - stage_start, 2)
    state["stages_completed"].append("matcher")
    state["results"]["matcher"] = match_results.get("summary", {})
    print()

    # ================================================================
    # ROUTING: After Matcher — should we run checker?
    # ================================================================
    print("─" * 60)
    print("ROUTING: POST-MATCHER DECISION")
    print("─" * 60)

    matcher_routing = route_after_matcher(match_results)
    state["routing_decisions"].append({"point": "post_matcher", **matcher_routing})
    print(f"  Unmatched: {matcher_routing['unmatched_count']}")
    print(f"  Match rate: {matcher_routing['match_rate']}%")
    print(f"  Decision: {'RUN CHECKER' if matcher_routing['run_checker'] else 'SKIP CHECKER'}")
    print(f"  Reason: {matcher_routing['reason']}")
    print()

    # ================================================================
    # STAGE 3: TDS Checker Agent (conditional)
    # ================================================================
    checker_results = None
    checker_routing = None

    if matcher_routing["run_checker"]:
        print("─" * 60)
        print("STAGE 3/4: TDS CHECKER AGENT")
        print("─" * 60)

        stage_start = time.time()
        from agents.tds_checker_agent import run as checker_run
        checker_results = checker_run(str(parsed_dir), str(results_dir))
        state["timing"]["checker"] = round(time.time() - stage_start, 2)
        state["stages_completed"].append("checker")
        state["results"]["checker"] = checker_results.get("summary", {})
        print()

        # ============================================================
        # ROUTING: After Checker — clean or needs review?
        # ============================================================
        print("─" * 60)
        print("ROUTING: POST-CHECKER DECISION")
        print("─" * 60)

        checker_routing = route_after_checker(checker_results)
        state["routing_decisions"].append({"point": "post_checker", **checker_routing})
        print(f"  Status: {checker_routing['status'].upper()}")
        print(f"  Severity: {checker_routing['severity']}")
        print(f"  Reason: {checker_routing['reason']}")
        if checker_routing["review_items"]:
            print(f"  Review items: {len(checker_routing['review_items'])}")
        print()
    else:
        print("─" * 60)
        print("STAGE 3/4: TDS CHECKER AGENT — SKIPPED")
        print("─" * 60)
        print(f"  Reason: {matcher_routing['reason']}")
        state["stages_completed"].append("checker_skipped")
        print()

    # ================================================================
    # STAGE 4: Reporter Agent
    # ================================================================
    print("─" * 60)
    print("STAGE 4/4: REPORTER AGENT")
    print("─" * 60)

    stage_start = time.time()
    from agents.reporter_agent import run as reporter_run
    report = reporter_run(str(parsed_dir), str(results_dir))
    state["timing"]["reporter"] = round(time.time() - stage_start, 2)
    state["stages_completed"].append("reporter")
    state["results"]["reporter"] = report.get("summary", {})
    print()

    # ================================================================
    # BUILD HUMAN REVIEW QUEUE
    # ================================================================
    review_queue = build_review_queue(match_results, checker_routing)
    state["human_review_queue"] = review_queue

    # ================================================================
    # DETERMINE FINAL STATUS
    # ================================================================
    if state["errors"]:
        state["status"] = "failed"
    elif review_queue:
        state["status"] = "needs_review"
    else:
        state["status"] = "complete"

    result = _finalize(state, pipeline_start)

    # ================================================================
    # FINAL SUMMARY
    # ================================================================
    print("=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    _print_final_summary(result)

    # Write pipeline result to disk
    pipeline_file = results_dir / "pipeline_result.json"
    with open(pipeline_file, "w") as f:
        # Strip large source data from review queue for the JSON output
        output = {**result}
        output["human_review_queue"] = [
            {k: v for k, v in item.items() if k != "source"}
            for item in result["human_review_queue"]
        ]
        json.dump(output, f, indent=2, default=str)
    print(f"\nPipeline result: {pipeline_file}")

    return result


def _finalize(state: dict, pipeline_start: float) -> dict:
    """Finalize the pipeline state into the return format."""
    state["timing"]["total"] = round(time.time() - pipeline_start, 2)
    return {
        "status": state["status"],
        "results": state["results"],
        "human_review_queue": state["human_review_queue"],
        "pipeline": {
            "stages_completed": state["stages_completed"],
            "gates_passed": [g["gate"] for g in state["gates_passed"]],
            "gates_failed": [g["gate"] for g in state["gates_failed"]],
            "routing_decisions": state["routing_decisions"],
            "timing": state["timing"],
            "errors": state["errors"],
        },
    }


def _print_final_summary(result: dict):
    """Print a human-readable final summary."""
    pipeline = result["pipeline"]
    timing = pipeline["timing"]

    print(f"\nStatus: {result['status'].upper()}")
    print(f"Time: {timing.get('total', 0):.1f}s")
    print(f"Stages: {' → '.join(pipeline['stages_completed'])}")
    print(f"Gates passed: {', '.join(pipeline['gates_passed']) or 'none'}")
    if pipeline["gates_failed"]:
        print(f"Gates FAILED: {', '.join(pipeline['gates_failed'])}")

    # Routing decisions
    for rd in pipeline["routing_decisions"]:
        point = rd["point"]
        if point == "post_matcher":
            print(f"\nMatcher: {rd['match_rate']}% match rate, "
                  f"{rd['unmatched_count']} unmatched")
        elif point == "post_checker":
            print(f"Checker: {rd['status']} ({rd['reason']})")

    # Human review queue
    queue = result["human_review_queue"]
    if queue:
        high = sum(1 for q in queue if q["priority"] == "high")
        medium = sum(1 for q in queue if q["priority"] == "medium")
        print(f"\nHuman Review Queue: {len(queue)} items")
        print(f"  High priority: {high}")
        print(f"  Medium priority: {medium}")
        print()
        for i, item in enumerate(queue, 1):
            print(f"  {i}. [{item['priority'].upper()}] {item['type']}")
            if item.get("vendor"):
                print(f"     Vendor: {item['vendor']} | Section: {item.get('section', '-')}")
            if item.get("amount"):
                print(f"     Amount: {item['amount']:,}")
            print(f"     Action: {item['action_needed']}")
    else:
        print(f"\nHuman Review Queue: EMPTY (all clear)")

    # Timing breakdown
    print(f"\nTiming:")
    for stage, t in timing.items():
        if stage != "total":
            print(f"  {stage}: {t:.2f}s")
    print(f"  TOTAL: {timing.get('total', 0):.1f}s")


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
