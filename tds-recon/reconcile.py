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

import sys
import time
from pathlib import Path


def run_pipeline(form26_path: str | None = None, tally_path: str | None = None):
    """Run the full TDS reconciliation pipeline."""
    base = Path(__file__).parent
    parsed_dir = base / "data" / "parsed"
    results_dir = base / "data" / "results"

    # Ensure output directories exist
    parsed_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("TDS RECONCILIATION PIPELINE")
    print("=" * 60)
    print(f"Sections: 194A (Interest), 194C (Contractor)")
    print(f"FY: 2024-25 | AY: 2025-26")
    print()

    start = time.time()

    # ---- Step 1: Parser ----
    if form26_path and tally_path:
        print("─" * 60)
        print("STEP 1/4: PARSER AGENT")
        print("─" * 60)
        from agents.parser_agent import run as parser_run
        parser_run(form26_path, tally_path, str(parsed_dir))
        print()
    else:
        print("─" * 60)
        print("STEP 1/4: PARSER AGENT — Skipped (using existing parsed data)")
        print("─" * 60)
        if not (parsed_dir / "parsed_form26.json").exists():
            print("ERROR: parsed_form26.json not found. Provide XLSX paths to run parser.")
            sys.exit(1)
        if not (parsed_dir / "parsed_tally.json").exists():
            print("ERROR: parsed_tally.json not found. Provide XLSX paths to run parser.")
            sys.exit(1)
        print(f"  Using: {parsed_dir / 'parsed_form26.json'}")
        print(f"  Using: {parsed_dir / 'parsed_tally.json'}")
        print()

    # ---- Step 2: Matcher ----
    print("─" * 60)
    print("STEP 2/4: MATCHER AGENT")
    print("─" * 60)
    from agents.matcher_agent import run as matcher_run
    match_results = matcher_run(str(parsed_dir), str(results_dir))
    print()

    # ---- Step 3: TDS Checker ----
    print("─" * 60)
    print("STEP 3/4: TDS CHECKER AGENT")
    print("─" * 60)
    from agents.tds_checker_agent import run as checker_run
    checker_results = checker_run(str(parsed_dir), str(results_dir))
    print()

    # ---- Step 4: Reporter ----
    print("─" * 60)
    print("STEP 4/4: REPORTER AGENT")
    print("─" * 60)
    from agents.reporter_agent import run as reporter_run
    report = reporter_run(str(parsed_dir), str(results_dir))
    print()

    elapsed = time.time() - start

    # ---- Final Summary ----
    print("=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"Time: {elapsed:.1f}s")
    print(f"\nOutputs in {results_dir}/:")
    print(f"  match_results.json           — Raw match data")
    print(f"  checker_results.json         — Compliance findings")
    print(f"  reconciliation_summary.json  — Executive summary")
    print(f"  reconciliation_report.csv    — Full match report")
    print(f"  findings_report.csv          — Findings + remediation")

    summary = report["summary"]
    c = summary["compliance"]
    status = "CLEAN" if c["clean_bill"] else "ACTION REQUIRED"
    print(f"\nStatus: {status}")
    if c["errors"] > 0:
        print(f"  {c['errors']} error(s) require attention")
    if c["warnings"] > 0:
        print(f"  {c['warnings']} warning(s) to review")

    return report


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
