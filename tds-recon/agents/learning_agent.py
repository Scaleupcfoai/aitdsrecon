"""
Learning Agent — TDS Reconciliation MVP
========================================
Captures human decisions on unmatched/flagged entries and stores them as
reusable rules. The Matcher Agent loads these rules on subsequent runs to
resolve entries that previously required manual review.

This is the feedback loop that makes the system smarter over time:

    Unmatched entries → Human reviews → Learning Agent captures decision
    → Rules DB updated → Next Matcher run applies rules automatically

Rule Types:
    1. vendor_alias     — Map different names to same entity
    2. below_threshold  — Vendor's annual total is below TDS threshold
    3. exempt_vendor    — Vendor has exemption (15G/15H, lower deduction cert)
    4. section_override — Confirm/correct the TDS section for a vendor+expense
    5. manual_match     — Explicitly link Form 26 entry to Tally entries
    6. ignore           — Entry is not TDS-applicable (e.g., insurance, salary)

Storage: data/rules/learned_rules.json (append-only, versioned)

Integration:
    - Matcher Agent calls load_rules() at startup
    - Rules are applied as Pass 0 (before all other passes)
    - Each rule has a "times_applied" counter for tracking effectiveness
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Rules DB Schema
# ---------------------------------------------------------------------------

RULE_TYPES = {
    "vendor_alias",
    "below_threshold",
    "exempt_vendor",
    "section_override",
    "manual_match",
    "ignore",
}

RULES_FILE = "learned_rules.json"


def _rules_path(rules_dir: str | Path) -> Path:
    return Path(rules_dir) / RULES_FILE


def _empty_db() -> dict:
    return {
        "version": 1,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "rules": [],
        "stats": {
            "total_rules": 0,
            "total_applied": 0,
            "by_type": {},
        },
    }


# ---------------------------------------------------------------------------
# CRUD Operations
# ---------------------------------------------------------------------------

def load_rules(rules_dir: str | Path) -> dict:
    """Load rules DB from disk. Returns empty DB if file doesn't exist."""
    path = _rules_path(rules_dir)
    if not path.exists():
        return _empty_db()
    with open(path) as f:
        return json.load(f)


def save_rules(rules_dir: str | Path, db: dict) -> Path:
    """Save rules DB to disk."""
    path = _rules_path(rules_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    db["updated_at"] = datetime.now().isoformat()
    db["stats"]["total_rules"] = len(db["rules"])
    db["stats"]["by_type"] = {}
    for r in db["rules"]:
        rtype = r["rule_type"]
        db["stats"]["by_type"][rtype] = db["stats"]["by_type"].get(rtype, 0) + 1
    with open(path, "w") as f:
        json.dump(db, f, indent=2, default=str)
    return path


def add_rule(
    rules_dir: str | Path,
    rule_type: str,
    params: dict,
    reason: str,
    source: str = "human",
) -> dict:
    """Add a new rule to the DB.

    Args:
        rules_dir: Path to rules directory
        rule_type: One of RULE_TYPES
        params: Rule-specific parameters (see below)
        reason: Human-readable explanation of why this rule exists
        source: Who created the rule ("human", "auto", "bulk_import")

    Returns:
        The created rule dict

    Rule params by type:

    vendor_alias:
        tally_name: str      — Name as it appears in Tally
        form26_name: str     — Name as it appears in Form 26
        pan: str (optional)  — PAN for additional verification

    below_threshold:
        vendor_name: str     — Vendor name (normalized)
        section: str         — TDS section (e.g., "194C")
        annual_amount: float — Aggregate annual amount
        threshold: float     — Applicable threshold
        fy: str              — Financial year (e.g., "2024-25")

    exempt_vendor:
        vendor_name: str     — Vendor name
        pan: str             — PAN
        exemption_type: str  — "form_15g", "form_15h", "lower_deduction_cert", "government"
        valid_from: str      — Start date (ISO)
        valid_to: str        — End date (ISO)

    section_override:
        vendor_name: str     — Vendor name
        expense_head: str    — Expense head from Tally
        current_section: str — Section currently applied
        correct_section: str — Confirmed correct section
        confirmed_by: str    — Who confirmed (e.g., "CA review")

    manual_match:
        form26_vendor: str        — Form 26 vendor name
        form26_section: str       — Section
        form26_amount: float      — Amount
        form26_date: str          — Date
        tally_entries: list[dict] — List of {party_name, voucher_no, amount, date}

    ignore:
        vendor_name: str     — Vendor name
        expense_head: str    — Expense head (optional)
        category: str        — Why ignored: "not_tds_applicable", "insurance",
                               "salary", "internal_transfer", "duplicate"
    """
    if rule_type not in RULE_TYPES:
        raise ValueError(f"Invalid rule_type '{rule_type}'. Must be one of: {RULE_TYPES}")

    db = load_rules(rules_dir)

    rule = {
        "id": len(db["rules"]) + 1,
        "rule_type": rule_type,
        "params": params,
        "reason": reason,
        "source": source,
        "created_at": datetime.now().isoformat(),
        "times_applied": 0,
        "active": True,
    }

    db["rules"].append(rule)
    save_rules(rules_dir, db)

    return rule


def deactivate_rule(rules_dir: str | Path, rule_id: int) -> bool:
    """Deactivate a rule (soft delete)."""
    db = load_rules(rules_dir)
    for r in db["rules"]:
        if r["id"] == rule_id:
            r["active"] = False
            save_rules(rules_dir, db)
            return True
    return False


def get_active_rules(rules_dir: str | Path, rule_type: str | None = None) -> list[dict]:
    """Get all active rules, optionally filtered by type."""
    db = load_rules(rules_dir)
    rules = [r for r in db["rules"] if r["active"]]
    if rule_type:
        rules = [r for r in rules if r["rule_type"] == rule_type]
    return rules


def increment_applied(rules_dir: str | Path, rule_id: int) -> None:
    """Increment the times_applied counter for a rule."""
    db = load_rules(rules_dir)
    for r in db["rules"]:
        if r["id"] == rule_id:
            r["times_applied"] = r.get("times_applied", 0) + 1
            break
    # Update total applied
    db["stats"]["total_applied"] = sum(r.get("times_applied", 0) for r in db["rules"])
    save_rules(rules_dir, db)


# ---------------------------------------------------------------------------
# Rule Application — called by Matcher Agent
# ---------------------------------------------------------------------------

def apply_vendor_aliases(
    rules: list[dict],
    tally_entries: list[dict],
) -> list[dict]:
    """Apply vendor_alias rules to normalize Tally party names.

    Returns modified tally_entries with original_party_name preserved.
    """
    alias_map = {}
    alias_rule_ids = {}
    for r in rules:
        if r["rule_type"] == "vendor_alias" and r["active"]:
            tally_name = r["params"]["tally_name"].lower().strip()
            alias_map[tally_name] = r["params"]["form26_name"]
            alias_rule_ids[tally_name] = r["id"]

    if not alias_map:
        return tally_entries

    applied_ids = set()
    for entry in tally_entries:
        party = (entry.get("party_name") or "").lower().strip()
        if party in alias_map:
            entry["original_party_name"] = entry["party_name"]
            entry["party_name"] = alias_map[party]
            entry["applied_rule_id"] = alias_rule_ids[party]
            applied_ids.add(alias_rule_ids[party])

    return tally_entries, applied_ids


def get_ignored_vendors(rules: list[dict]) -> set[str]:
    """Get set of vendor names (lowered) that should be ignored."""
    ignored = set()
    for r in rules:
        if r["rule_type"] == "ignore" and r["active"]:
            ignored.add(r["params"]["vendor_name"].lower().strip())
    return ignored


def get_exempt_vendors(rules: list[dict]) -> set[str]:
    """Get set of vendor names (lowered) that are exempt from TDS."""
    exempt = set()
    for r in rules:
        if r["rule_type"] == "exempt_vendor" and r["active"]:
            exempt.add(r["params"]["vendor_name"].lower().strip())
    return exempt


def get_below_threshold_vendors(rules: list[dict], section: str) -> set[str]:
    """Get set of vendor names confirmed below threshold for a section."""
    below = set()
    for r in rules:
        if (r["rule_type"] == "below_threshold" and r["active"]
                and r["params"].get("section") == section):
            below.add(r["params"]["vendor_name"].lower().strip())
    return below


def get_section_overrides(rules: list[dict]) -> dict[str, str]:
    """Get vendor+expense → confirmed section overrides.

    Returns dict mapping (vendor_lower, expense_head_lower) → correct_section.
    """
    overrides = {}
    for r in rules:
        if r["rule_type"] == "section_override" and r["active"]:
            key = (
                r["params"]["vendor_name"].lower().strip(),
                r["params"]["expense_head"].lower().strip(),
            )
            overrides[key] = r["params"]["correct_section"]
    return overrides


def get_manual_matches(rules: list[dict]) -> list[dict]:
    """Get all manual match rules (for Pass 0 in Matcher)."""
    return [r for r in rules if r["rule_type"] == "manual_match" and r["active"]]


# ---------------------------------------------------------------------------
# Bulk Operations — for processing unmatched review results
# ---------------------------------------------------------------------------

def process_human_review(
    rules_dir: str | Path,
    decisions: list[dict],
) -> dict:
    """Process a batch of human review decisions and create rules.

    Each decision is a dict with:
        vendor: str          — Vendor name
        decision: str        — One of: "below_threshold", "exempt", "ignore",
                               "alias", "section_override", "manual_match"
        params: dict         — Decision-specific parameters
        reason: str          — Why this decision was made

    Returns summary of rules created.
    """
    created = []
    errors = []

    decision_to_rule_type = {
        "below_threshold": "below_threshold",
        "exempt": "exempt_vendor",
        "ignore": "ignore",
        "alias": "vendor_alias",
        "section_override": "section_override",
        "manual_match": "manual_match",
    }

    for d in decisions:
        decision = d.get("decision", "")
        rule_type = decision_to_rule_type.get(decision)

        if not rule_type:
            errors.append({"decision": d, "error": f"Unknown decision type: {decision}"})
            continue

        try:
            rule = add_rule(
                rules_dir=rules_dir,
                rule_type=rule_type,
                params=d.get("params", {}),
                reason=d.get("reason", "Human review"),
                source="human_review",
            )
            created.append(rule)
        except Exception as e:
            errors.append({"decision": d, "error": str(e)})

    return {
        "rules_created": len(created),
        "errors": len(errors),
        "error_details": errors,
        "rules": created,
    }


# ---------------------------------------------------------------------------
# Apply Corrections — process ONLY affected transactions, update results
# ---------------------------------------------------------------------------

def apply_corrections(
    rules_dir: str | Path,
    results_dir: str | Path,
    decisions: list[dict],
) -> dict:
    """Apply human corrections to current results WITHOUT re-running full pipeline.

    This is the core Learning Agent behavior:
    1. Store decisions as rules
    2. Apply corrections to affected transactions only
    3. Move corrected entries from unmatched → resolved
    4. Re-run Checker + Reporter on updated results (not Parser/Matcher)

    Returns: {rules_created, resolved_entries, updated_results, events}
    """
    from agents.event_logger import EventLogger

    logger = EventLogger()
    rules_dir = Path(rules_dir)
    results_dir = Path(results_dir)

    logger.agent_start("Learning Agent", "Processing human corrections...")

    # Step 1: Store decisions as rules
    review_result = process_human_review(str(rules_dir), decisions)
    logger.detail("Learning Agent",
                  f"Created {review_result['rules_created']} new rules")

    # Step 2: Load current results
    with open(results_dir / "match_results.json") as f:
        match_data = json.load(f)

    unmatched_f26 = match_data.get("unmatched_form26", [])
    unmatched_194c = match_data.get("unmatched_tally_194c", [])
    unmatched_194a = match_data.get("unmatched_tally_194a", [])

    resolved_entries = []
    vendors_resolved = set()

    # Step 3: Apply each decision to affected entries only
    for d in decisions:
        vendor = d.get("vendor", "").strip()
        decision = d.get("decision", "")
        vendor_lower = vendor.lower()

        if decision in ("below_threshold", "ignore", "exempt"):
            # Move this vendor's entries from unmatched to resolved
            resolved_from_194c = []
            remaining_194c = []
            for entry in unmatched_194c:
                if (entry.get("party_name", "").lower().strip() == vendor_lower):
                    entry["resolution"] = {
                        "type": decision,
                        "reason": d.get("reason", ""),
                        "resolved_by": "human_review",
                        "resolved_at": datetime.now().isoformat(),
                    }
                    resolved_from_194c.append(entry)
                else:
                    remaining_194c.append(entry)

            if resolved_from_194c:
                resolved_entries.extend(resolved_from_194c)
                vendors_resolved.add(vendor)
                logger.detail("Learning Agent",
                              f"{vendor}: {len(resolved_from_194c)} entries → {decision}")

            unmatched_194c = remaining_194c

        elif decision == "alias":
            # Vendor alias: try to match aliased entries against unmatched Form 26
            form26_name = d.get("params", {}).get("form26_name", "")
            if form26_name:
                matched_via_alias = []
                remaining_194c = []
                for entry in unmatched_194c:
                    if entry.get("party_name", "").lower().strip() == vendor_lower:
                        entry["resolution"] = {
                            "type": "alias",
                            "aliased_to": form26_name,
                            "resolved_by": "human_review",
                            "resolved_at": datetime.now().isoformat(),
                        }
                        matched_via_alias.append(entry)
                    else:
                        remaining_194c.append(entry)

                if matched_via_alias:
                    resolved_entries.extend(matched_via_alias)
                    vendors_resolved.add(vendor)
                    logger.detail("Learning Agent",
                                  f"{vendor} → aliased to '{form26_name}', "
                                  f"{len(matched_via_alias)} entries resolved")

                unmatched_194c = remaining_194c

        elif decision == "section_override":
            # Section override: log it, will be used by Checker on next validation
            logger.detail("Learning Agent",
                          f"{vendor}: section override recorded")
            vendors_resolved.add(vendor)

    # Step 4: Update match_results with corrected unmatched lists
    match_data["unmatched_tally_194c"] = unmatched_194c
    if "resolved_by_learning" not in match_data:
        match_data["resolved_by_learning"] = []
    match_data["resolved_by_learning"].extend(resolved_entries)

    # Update learned_rules stats in match_data
    all_rules = get_active_rules(str(rules_dir))
    match_data["learned_rules"] = {
        "rules_loaded": len(all_rules),
        "rules_applied": len(resolved_entries),
        "below_threshold_vendors": len([
            r for r in all_rules if r["rule_type"] == "below_threshold"
        ]),
        "below_threshold_entries": len([
            e for e in resolved_entries
            if e.get("resolution", {}).get("type") == "below_threshold"
        ]),
        "ignored_vendors": len([
            r for r in all_rules if r["rule_type"] == "ignore"
        ]),
        "exempt_vendors": len([
            r for r in all_rules if r["rule_type"] == "exempt_vendor"
        ]),
        "total_resolved_by_learning": len(
            match_data.get("resolved_by_learning", [])
        ),
    }

    # Save updated match results
    with open(results_dir / "match_results.json", "w") as f:
        json.dump(match_data, f, indent=2, default=str)

    logger.success("Learning Agent",
                   f"Resolved {len(resolved_entries)} entries across "
                   f"{len(vendors_resolved)} vendors")
    logger.agent_done("Learning Agent", "Corrections applied")

    # Step 5: Re-run Checker + Reporter on updated results (NOT full pipeline)
    logger.agent_start("TDS Checker", "Re-validating with corrections...")
    from agents.tds_checker_agent import run as checker_run
    parsed_dir = results_dir.parent / "parsed"
    checker_results = checker_run(str(parsed_dir), str(results_dir))

    findings = checker_results.get("findings", [])
    errors = [f for f in findings if f.get("severity") == "error"]
    warnings = [f for f in findings if f.get("severity") == "warning"]
    logger.success("TDS Checker",
                   f"Updated: {len(errors)} errors, {len(warnings)} warnings")
    logger.agent_done("TDS Checker", "Re-validation complete")

    logger.agent_start("Reporter Agent", "Regenerating reports...")
    from agents.reporter_agent import run as reporter_run
    report = reporter_run(str(parsed_dir), str(results_dir))
    logger.detail("Reporter Agent", "Reports updated with corrections")
    logger.agent_done("Reporter Agent", "Reports regenerated")

    logger.emit("Learning Agent",
                f"Done — {len(resolved_entries)} entries resolved, "
                f"{len(vendors_resolved)} vendors classified", "success")

    # Load updated results for API response
    updated_results = {}
    for fname in ["match_results.json", "checker_results.json",
                   "reconciliation_summary.json"]:
        fpath = results_dir / fname
        if fpath.exists():
            with open(fpath) as f:
                updated_results[fname.replace(".json", "")] = json.load(f)

    return {
        "rules_created": review_result["rules_created"],
        "resolved_entries": len(resolved_entries),
        "vendors_resolved": list(vendors_resolved),
        "events": logger.get_events(),
        "results": updated_results,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def summarize_rules(rules_dir: str | Path) -> dict:
    """Generate a summary of the rules database."""
    db = load_rules(rules_dir)
    active = [r for r in db["rules"] if r["active"]]
    inactive = [r for r in db["rules"] if not r["active"]]

    return {
        "total_rules": len(db["rules"]),
        "active_rules": len(active),
        "inactive_rules": len(inactive),
        "by_type": db["stats"].get("by_type", {}),
        "total_times_applied": db["stats"].get("total_applied", 0),
        "most_applied": sorted(
            active, key=lambda r: r.get("times_applied", 0), reverse=True
        )[:5],
        "never_applied": [r for r in active if r.get("times_applied", 0) == 0],
    }


# ---------------------------------------------------------------------------
# CLI — Interactive rule creation
# ---------------------------------------------------------------------------

def run_interactive(rules_dir: str, results_dir: str):
    """Interactive mode for reviewing unmatched entries and creating rules."""
    rules_path = Path(rules_dir)
    results_path = Path(results_dir)

    # Load unmatched entries
    with open(results_path / "match_results.json") as f:
        match_data = json.load(f)

    unmatched_f26 = match_data.get("unmatched_form26", [])
    unmatched_tally = match_data.get("unmatched_tally_194c", [])

    print("=" * 60)
    print("LEARNING AGENT — INTERACTIVE REVIEW")
    print("=" * 60)

    # Group unmatched tally by vendor
    from collections import defaultdict
    vendor_entries = defaultdict(lambda: {"entries": [], "total": 0})
    for e in unmatched_tally:
        v = e.get("party_name", "Unknown")
        vendor_entries[v]["entries"].append(e)
        vendor_entries[v]["total"] += e.get("amount", 0)

    # Sort by total amount descending
    sorted_vendors = sorted(
        vendor_entries.items(), key=lambda x: -x[1]["total"]
    )

    print(f"\nUnmatched Form 26 entries: {len(unmatched_f26)}")
    print(f"Unmatched Tally vendors (194C): {len(sorted_vendors)}")
    print(f"Unmatched Tally entries (194C): {len(unmatched_tally)}")

    if not sorted_vendors and not unmatched_f26:
        print("\nNo unmatched entries to review!")
        return

    print(f"\n{'─' * 60}")
    print("UNMATCHED TALLY VENDORS (by amount, descending):")
    print(f"{'─' * 60}")
    print(f"\n{'#':>3} | {'Vendor':35s} | {'Entries':>7} | {'Total Amount':>12}")
    print("-" * 70)
    for i, (vendor, data) in enumerate(sorted_vendors, 1):
        print(f"{i:>3} | {vendor:35s} | {data['entries'].__len__():>7} | ₹{data['total']:>10,.0f}")

    print(f"\n{'─' * 60}")
    print("DECISION OPTIONS:")
    print(f"{'─' * 60}")
    print("  1. ignore           — Not TDS-applicable (insurance, travel, etc.)")
    print("  2. below_threshold  — Annual total below TDS threshold")
    print("  3. exempt           — Vendor has exemption certificate")
    print("  4. alias            — Map to existing Form 26 vendor name")
    print("  5. section_override — Confirm/correct TDS section")
    print("  6. skip             — Skip for now (review later)")
    print()

    # Process each vendor
    decisions = []
    for i, (vendor, data) in enumerate(sorted_vendors, 1):
        print(f"\n[{i}/{len(sorted_vendors)}] {vendor}")
        print(f"  Entries: {len(data['entries'])} | Total: ₹{data['total']:,.0f}")
        # Show expense heads
        heads = set()
        for e in data["entries"]:
            if e.get("expense_heads"):
                heads.update(e["expense_heads"].keys())
            elif e.get("account_postings"):
                heads.update(k for k in e["account_postings"] if k not in ("Gross Total", "Value"))
        if heads:
            print(f"  Expense heads: {', '.join(sorted(heads))}")

        try:
            choice = input("  Decision [1-6, or q to quit]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Stopping review.")
            break

        if choice == "q":
            break
        elif choice == "1":
            category = input("  Category (insurance/travel/internal/other): ").strip() or "not_tds_applicable"
            reason = input("  Reason: ").strip() or f"{vendor} expenses not TDS-applicable"
            decisions.append({
                "vendor": vendor,
                "decision": "ignore",
                "params": {"vendor_name": vendor, "category": category},
                "reason": reason,
            })
        elif choice == "2":
            decisions.append({
                "vendor": vendor,
                "decision": "below_threshold",
                "params": {
                    "vendor_name": vendor,
                    "section": "194C",
                    "annual_amount": data["total"],
                    "threshold": 100000,
                    "fy": "2024-25",
                },
                "reason": f"Aggregate ₹{data['total']:,.0f} below ₹1,00,000 threshold",
            })
        elif choice == "3":
            exempt_type = input("  Type (form_15g/form_15h/lower_deduction_cert/government): ").strip()
            decisions.append({
                "vendor": vendor,
                "decision": "exempt",
                "params": {
                    "vendor_name": vendor,
                    "pan": "",
                    "exemption_type": exempt_type or "lower_deduction_cert",
                    "valid_from": "2024-04-01",
                    "valid_to": "2025-03-31",
                },
                "reason": f"Vendor has {exempt_type or 'exemption certificate'}",
            })
        elif choice == "4":
            f26_name = input("  Form 26 name to map to: ").strip()
            if f26_name:
                decisions.append({
                    "vendor": vendor,
                    "decision": "alias",
                    "params": {"tally_name": vendor, "form26_name": f26_name},
                    "reason": f"Tally '{vendor}' = Form 26 '{f26_name}'",
                })
        elif choice == "5":
            correct_section = input("  Correct section (e.g., 194C, 194J(b)): ").strip()
            if correct_section:
                head = sorted(heads)[0] if heads else ""
                decisions.append({
                    "vendor": vendor,
                    "decision": "section_override",
                    "params": {
                        "vendor_name": vendor,
                        "expense_head": head,
                        "current_section": "194C",
                        "correct_section": correct_section,
                        "confirmed_by": "human_review",
                    },
                    "reason": f"Section confirmed as {correct_section}",
                })
        elif choice == "6":
            print("  Skipped.")
        else:
            print("  Invalid choice, skipped.")

    # Save decisions as rules
    if decisions:
        result = process_human_review(rules_dir, decisions)
        print(f"\n{'=' * 60}")
        print(f"Created {result['rules_created']} rules, {result['errors']} errors")
        if result["errors"]:
            for err in result["error_details"]:
                print(f"  Error: {err}")
    else:
        print("\nNo decisions recorded.")

    # Print summary
    summary = summarize_rules(rules_dir)
    print(f"\nRules DB: {summary['active_rules']} active, "
          f"{summary['total_times_applied']} total applications")


# ---------------------------------------------------------------------------
# Programmatic API — for bulk import of decisions (non-interactive)
# ---------------------------------------------------------------------------

def seed_rules_from_analysis(
    rules_dir: str | Path,
    match_results_path: str | Path,
    threshold: float = 100000,
):
    """Analyze unmatched entries and auto-generate below_threshold rules.

    This is a conservative auto-seeding: only creates rules for vendors
    whose aggregate annual amount is clearly below the TDS threshold.
    Human should review and confirm.
    """
    with open(match_results_path) as f:
        match_data = json.load(f)

    unmatched = match_data.get("unmatched_tally_194c", [])

    # Group by vendor
    from collections import defaultdict
    vendor_totals = defaultdict(float)
    for e in unmatched:
        vendor_totals[e.get("party_name", "")] += e.get("amount", 0)

    auto_rules = []
    for vendor, total in vendor_totals.items():
        if total < threshold:
            auto_rules.append({
                "vendor": vendor,
                "decision": "below_threshold",
                "params": {
                    "vendor_name": vendor,
                    "section": "194C",
                    "annual_amount": round(total, 2),
                    "threshold": threshold,
                    "fy": "2024-25",
                },
                "reason": f"Auto: aggregate ₹{total:,.0f} below ₹{threshold:,.0f} threshold",
            })

    if auto_rules:
        result = process_human_review(rules_dir, auto_rules)
        print(f"[Learning] Auto-seeded {result['rules_created']} below_threshold rules")
        return result

    return {"rules_created": 0, "errors": 0}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    rules = base / "data" / "rules"
    results = base / "data" / "results"

    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        # Auto-seed below-threshold rules
        seed_rules_from_analysis(
            str(rules),
            str(results / "match_results.json"),
        )
        summary = summarize_rules(str(rules))
        print(f"\nRules DB: {summary['active_rules']} active rules")
        print(f"  By type: {summary['by_type']}")
    elif len(sys.argv) > 1 and sys.argv[1] == "--summary":
        summary = summarize_rules(str(rules))
        print(json.dumps(summary, indent=2, default=str))
    else:
        # Interactive review mode
        run_interactive(str(rules), str(results))
