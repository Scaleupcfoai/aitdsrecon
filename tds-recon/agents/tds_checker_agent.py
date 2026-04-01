"""
TDS Checker Agent — TDS Reconciliation MVP
===========================================
Validates TDS compliance on matched entries and detects missing TDS deductions.

The Matcher Agent answers: "Which Tally entry corresponds to which Form 26 entry?"
This agent answers: "Is the TDS correct — right section, right rate, right base amount?"

Check 1: Section Validation    — Is the TDS section correct for the expense type?
Check 2: Rate Validation       — Is the TDS rate correct for entity type + section?
Check 3: Base Amount Validation — Is TDS computed on the correct base (pre-GST)?
Check 4: Threshold Validation   — Does the amount exceed the applicable threshold?
Check 5: Missing TDS Detection  — Tally expenses where TDS should have been deducted
                                  but no Form 26 entry exists.

Inputs:
  - data/parsed/parsed_form26.json
  - data/parsed/parsed_tally.json
  - data/results/match_results.json

Outputs:
  - data/results/checker_results.json
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# TDS Rules Engine — Indian Income Tax Act
# ---------------------------------------------------------------------------

# Section → expense head mapping: which expense types belong under which section
# Key = TDS section, Value = set of expense head keywords (lowercase)
SECTION_EXPENSE_MAP = {
    "194A": {
        "keywords": {"interest", "loan"},
        "description": "Interest other than interest on securities",
    },
    "194C": {
        "keywords": {
            "freight", "carriage", "transport", "logistics", "packing",
            "printing", "stationary", "shop repair", "maintenance",
            "computer repair", "contractor",
        },
        "description": "Payment to contractors/sub-contractors",
    },
    "194H": {
        "keywords": {"brokerage", "commission"},
        "description": "Commission or brokerage",
    },
    "194J(a)": {
        "keywords": {"call centre", "technical"},
        "description": "Fee for technical services (to call centre)",
    },
    "194J(b)": {
        "keywords": {
            "professional", "consultancy", "audit", "legal", "software",
            "gst annual return", "domain",
        },
        "description": "Fee for professional/technical services",
    },
    "194Q": {
        "keywords": {"purchase"},
        "description": "Payment for purchase of goods",
    },
}

# Expense heads that could be mis-classified between sections
# advertisement can be 194C (if works contract) or 194J(b) (if professional)
AMBIGUOUS_EXPENSE_HEADS = {
    "advertisement": {
        "likely_sections": ["194C", "194J(b)"],
        "note": "Advertisement may be 194C (works contract / production) "
                "or 194J(b) (professional/creative services). "
                "Verify nature of service from invoice.",
    },
    "annual maintenance": {
        "likely_sections": ["194C", "194J(b)"],
        "note": "AMC may be 194C (if labour/facility) or 194J(b) "
                "(if technical/software). Check contract terms.",
    },
    "software": {
        "likely_sections": ["194J(b)", "194C"],
        "note": "Software expenses are typically 194J(b) for royalty/license, "
                "but 194C if it's a development contract.",
    },
}

# TDS rate table: section → entity_type → rate (%)
# entity_type: "individual_huf" or "company" (derived from PAN 4th char)
TDS_RATES = {
    "192": {
        "individual_huf": 30.0,  # Highest slab assumed for directors
        "company": 30.0,
        "default": 30.0,
    },
    "194A": {
        "individual_huf": 10.0,
        "company": 10.0,
        "default": 10.0,
    },
    "194C": {
        "individual_huf": 1.0,
        "company": 2.0,
        "default": 2.0,
    },
    "194H": {
        "individual_huf": 2.0,    # 5% before Budget 2025, now 2%
        "company": 2.0,           # 5% before Budget 2025, now 2%
        "default": 2.0,
    },
    "194J(a)": {
        "individual_huf": 2.0,
        "company": 2.0,
        "default": 2.0,
    },
    "194J(b)": {
        "individual_huf": 10.0,
        "company": 10.0,
        "default": 10.0,
    },
    "194Q": {
        "individual_huf": 0.1,
        "company": 0.1,
        "default": 0.1,
    },
}

# Threshold limits: section → {single_txn, aggregate_annual}
# Below these limits, TDS need not be deducted
TDS_THRESHOLDS = {
    "192": {
        "aggregate_annual": 250000,  # Basic exemption limit
        "single_txn": None,
        "description": "Salary below ₹2,50,000 basic exemption limit",
    },
    "194A": {
        "aggregate_annual": 5000,
        "single_txn": None,
        "description": "Interest below ₹5,000 in a year exempt",
    },
    "194C": {
        "single_txn": 30000,
        "aggregate_annual": 100000,
        "description": "Single payment ≤₹30,000 or aggregate ≤₹1,00,000 exempt",
    },
    "194H": {
        "aggregate_annual": 15000,
        "single_txn": None,
        "description": "Commission below ₹15,000 in a year exempt",
    },
    "194J(a)": {
        "aggregate_annual": 30000,
        "single_txn": None,
        "description": "Professional fees below ₹30,000 in a year exempt",
    },
    "194J(b)": {
        "aggregate_annual": 30000,
        "single_txn": None,
        "description": "Professional fees below ₹30,000 in a year exempt",
    },
    "194Q": {
        "aggregate_annual": 5000000,  # ₹50 lakh
        "single_txn": None,
        "description": "Purchase of goods below ₹50 lakh in a year exempt",
    },
}

# GST rates for reverse-computing base amounts
GST_RATES = [0.18, 0.12, 0.05, 0.28]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def entity_type_from_pan(pan: str) -> str:
    """Derive entity type from PAN 4th character.
    C = Company, P = Individual, H = HUF, F = Firm, etc."""
    if not pan or len(pan) < 4:
        return "unknown"
    fourth = pan[3].upper()
    if fourth == "C":
        return "company"
    elif fourth in ("P", "H"):
        return "individual_huf"
    elif fourth == "F":
        return "firm"  # treated as individual_huf for TDS rates
    else:
        return "unknown"


def expected_rate(section: str, pan: str) -> float | None:
    """Get expected TDS rate for a section + PAN combination."""
    rates = TDS_RATES.get(section)
    if not rates:
        return None
    etype = entity_type_from_pan(pan)
    if etype == "firm":
        etype = "individual_huf"  # firms use individual rate for most sections
    return rates.get(etype, rates.get("default"))


def classify_expense_head(head: str) -> list[str]:
    """Given an expense head string, return likely TDS sections."""
    head_lower = head.lower().strip()

    # Check ambiguous first
    for keyword, info in AMBIGUOUS_EXPENSE_HEADS.items():
        if keyword in head_lower:
            return info["likely_sections"]

    # Check standard mappings
    matches = []
    for section, mapping in SECTION_EXPENSE_MAP.items():
        for keyword in mapping["keywords"]:
            if keyword in head_lower:
                matches.append(section)
                break

    return matches if matches else ["unknown"]


def normalize_name(name: str) -> str:
    """Normalize vendor name for comparison."""
    if not name:
        return ""
    n = name.lower().strip()
    for suffix in ["pvt. ltd.", "pvt ltd", "private limited", "ltd.", "ltd",
                   "llp", "lp", "inc.", "inc", "co.", "company"]:
        n = n.replace(suffix, "")
    n = re.sub(r"\(\d+\)", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def parse_date(d) -> datetime | None:
    if isinstance(d, datetime):
        return d
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d)
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Check 1: Section Validation
# ---------------------------------------------------------------------------

def check_section(match_entry: dict) -> dict | None:
    """Validate if the Form 26 section is correct for the matched expense type."""
    f26 = match_entry["form26_entry"]
    tally_entries = match_entry["tally_entries"]
    section = f26["section"]

    # Collect all expense heads from tally entries
    expense_heads = set()
    for t in tally_entries:
        # GST exp entries have expense_heads dict
        if "expense_heads" in t and t["expense_heads"]:
            for head in t["expense_heads"]:
                expense_heads.add(head)
        # Journal entries have account_postings
        elif "account_postings" in t and t["account_postings"]:
            for head in t["account_postings"]:
                if head not in ("Gross Total", "Value"):
                    expense_heads.add(head)
        # Infer from tally_source
        src = t.get("tally_source", "")
        if src == "journal_interest":
            expense_heads.add("Interest Paid")
        elif src == "journal_freight":
            expense_heads.add("Freight Charges")

    if not expense_heads:
        return None  # can't validate without expense info

    # For each expense head, check which sections it maps to
    all_expected_sections = set()
    ambiguous_heads = []
    for head in expense_heads:
        expected = classify_expense_head(head)
        all_expected_sections.update(expected)
        if head.lower() in AMBIGUOUS_EXPENSE_HEADS:
            ambiguous_heads.append(head)

    # If the declared section is in expected sections, it's OK
    if section in all_expected_sections:
        status = "ok"
        if ambiguous_heads:
            status = "review"  # technically valid but ambiguous
    elif "unknown" in all_expected_sections and len(all_expected_sections) == 1:
        status = "unclassified"
    else:
        status = "mismatch"

    if status == "ok":
        return None  # no finding to report

    return {
        "check": "section_validation",
        "severity": "warning" if status == "review" else ("info" if status == "unclassified" else "error"),
        "vendor": f26["vendor_name"],
        "pan": f26.get("pan", ""),
        "form26_section": section,
        "expense_heads": sorted(expense_heads),
        "expected_sections": sorted(all_expected_sections - {"unknown"}),
        "status": status,
        "message": _section_message(status, section, expense_heads, all_expected_sections, ambiguous_heads),
    }


def _section_message(status, section, heads, expected, ambiguous):
    heads_str = ", ".join(sorted(heads))
    if status == "mismatch":
        exp_str = ", ".join(sorted(expected - {"unknown"}))
        return (f"Section {section} may be incorrect for expense(s): {heads_str}. "
                f"Expected section(s): {exp_str}.")
    elif status == "review":
        amb_str = ", ".join(ambiguous)
        return (f"Ambiguous expense(s): {amb_str}. Section {section} is possible but "
                f"verify against invoice/contract nature.")
    else:
        return f"Cannot classify expense(s): {heads_str}. Manual review needed."


# ---------------------------------------------------------------------------
# Check 2: Rate Validation
# ---------------------------------------------------------------------------

def check_rate(match_entry: dict) -> dict | None:
    """Validate if the TDS rate applied matches expected rate for section + entity."""
    f26 = match_entry["form26_entry"]
    section = f26["section"]
    pan = f26.get("pan", "")
    actual_rate = f26.get("tax_rate_pct")
    amount_paid = f26.get("amount_paid", 0)
    tax_deducted = f26.get("tax_deducted", 0)

    if actual_rate is None:
        return None

    exp_rate = expected_rate(section, pan)
    if exp_rate is None:
        return None

    # Compare rates
    if abs(actual_rate - exp_rate) < 0.01:
        return None  # rate matches

    # Also verify via actual computation
    if amount_paid > 0:
        computed_rate = round(tax_deducted / amount_paid * 100, 2)
    else:
        computed_rate = 0

    etype = entity_type_from_pan(pan)
    return {
        "check": "rate_validation",
        "severity": "error",
        "vendor": f26["vendor_name"],
        "pan": pan,
        "entity_type": etype,
        "form26_section": section,
        "actual_rate_pct": actual_rate,
        "expected_rate_pct": exp_rate,
        "computed_rate_pct": computed_rate,
        "amount_paid": amount_paid,
        "tax_deducted": tax_deducted,
        "message": (f"TDS rate mismatch: {section} on {f26['vendor_name']} ({etype}) — "
                    f"applied {actual_rate}% but expected {exp_rate}%."),
    }


# ---------------------------------------------------------------------------
# Check 3: Base Amount Validation
# ---------------------------------------------------------------------------

def check_base_amount(match_entry: dict) -> dict | None:
    """Validate TDS is computed on the correct base amount (pre-GST, not gross).

    For GST entries, TDS should be on base_amount (net of GST).
    If Form 26 amount_paid == Tally gross (inclusive of GST), flag it.
    """
    f26 = match_entry["form26_entry"]
    tally_entries = match_entry["tally_entries"]

    f26_amount = f26.get("amount_paid", 0)
    if f26_amount == 0:
        return None

    # Sum tally base amounts and gross amounts
    total_base = 0
    total_gross = 0
    has_gst_entries = False

    for t in tally_entries:
        if t.get("tally_source") in ("gst_exp", "purchase"):
            has_gst_entries = True
            base = t.get("amount", 0)  # in matcher, 'amount' is base for gst_exp
            gross = t.get("gross_amount", 0) or t.get("gross_total", 0) or 0
            total_base += base
            total_gross += gross
        elif t.get("tally_source") in ("journal_freight", "journal_interest"):
            # Journal entries don't have GST breakup
            total_base += t.get("amount", 0)
            total_gross += t.get("amount", 0)

    if not has_gst_entries:
        return None  # No GST component to validate

    if total_gross == 0:
        return None

    # Check: is F26 amount matching gross (wrong) instead of base (right)?
    # TDS should be on base amount (pre-GST)
    base_diff = abs(f26_amount - total_base)
    gross_diff = abs(f26_amount - total_gross)

    # F26 matches base → correct
    if base_diff <= max(1, total_base * 0.005):
        return None

    # F26 matches gross → TDS on GST-inclusive amount (incorrect)
    if gross_diff < base_diff and gross_diff <= max(1, total_gross * 0.005):
        gst_amount = total_gross - total_base
        excess_tds = round(f26.get("tax_rate_pct", 0) / 100 * gst_amount, 2)
        return {
            "check": "base_amount_validation",
            "severity": "error",
            "vendor": f26["vendor_name"],
            "pan": f26.get("pan", ""),
            "form26_section": f26["section"],
            "form26_amount": f26_amount,
            "tally_base_amount": total_base,
            "tally_gross_amount": total_gross,
            "gst_component": round(total_gross - total_base, 2),
            "excess_tds": excess_tds,
            "message": (f"TDS appears computed on GST-inclusive amount (₹{f26_amount:,}) "
                        f"instead of base (₹{total_base:,.0f}). GST component: ₹{gst_amount:,.0f}. "
                        f"Potential excess TDS: ₹{excess_tds:,.0f}."),
        }

    return None


# ---------------------------------------------------------------------------
# Check 4: Threshold Validation
# ---------------------------------------------------------------------------

def check_thresholds(match_entries: list[dict]) -> list[dict]:
    """Validate threshold limits across all matches.

    Groups by vendor + section, checks if aggregate amounts breach thresholds.
    Also flags if TDS was deducted on below-threshold amounts.
    """
    findings = []

    # Group by (vendor_normalized, section) to compute aggregates
    vendor_section_totals = defaultdict(lambda: {
        "total_amount": 0, "entries": [], "vendor_name": "", "pan": "",
    })

    for m in match_entries:
        f26 = m["form26_entry"]
        key = (normalize_name(f26["vendor_name"]), f26["section"])
        vs = vendor_section_totals[key]
        vs["total_amount"] += f26.get("amount_paid", 0)
        vs["entries"].append(f26)
        vs["vendor_name"] = f26["vendor_name"]
        vs["pan"] = f26.get("pan", "")

    for (vendor_norm, section), vs in vendor_section_totals.items():
        thresholds = TDS_THRESHOLDS.get(section)
        if not thresholds:
            continue

        total = vs["total_amount"]
        agg_limit = thresholds.get("aggregate_annual")
        single_limit = thresholds.get("single_txn")

        # Check: aggregate is below annual threshold but TDS still deducted
        if agg_limit and total < agg_limit:
            findings.append({
                "check": "threshold_validation",
                "severity": "info",
                "vendor": vs["vendor_name"],
                "pan": vs["pan"],
                "form26_section": section,
                "aggregate_amount": total,
                "threshold_annual": agg_limit,
                "num_entries": len(vs["entries"]),
                "status": "below_threshold_but_deducted",
                "message": (f"{section} for {vs['vendor_name']}: aggregate ₹{total:,} "
                            f"is below annual threshold ₹{agg_limit:,}. "
                            f"TDS deduction is not mandatory (but not wrong if deducted)."),
            })

        # Check: single payment exceeds single-txn threshold
        if single_limit:
            for entry in vs["entries"]:
                amt = entry.get("amount_paid", 0)
                if amt > single_limit:
                    # This is fine — just noting it's over single threshold
                    pass

    return findings


# ---------------------------------------------------------------------------
# Check 5: Missing TDS Detection
# ---------------------------------------------------------------------------

def detect_missing_tds(
    tally_data: dict,
    form26_entries: list[dict],
    matched_tally_keys: set[str],
) -> list[dict]:
    """Find Tally expense entries where TDS should have been deducted
    but no corresponding Form 26 entry exists.

    Strategy:
    1. Collect all TDS-applicable Tally expenses (by expense head)
    2. Group by vendor
    3. Check aggregate annual amounts against thresholds
    4. If above threshold and no Form 26 entry → flag as missing TDS
    """
    findings = []

    # Build set of Form 26 vendors (normalized) per section
    f26_vendors_by_section = defaultdict(set)
    for e in form26_entries:
        f26_vendors_by_section[e["section"]].add(normalize_name(e["vendor_name"]))

    # Collect TDS-applicable Tally expenses not already matched
    vendor_expenses = defaultdict(lambda: {
        "total_amount": 0,
        "entries": [],
        "expense_heads": set(),
        "vendor_name": "",
        "expected_sections": set(),
    })

    # Track journal entries by (vendor_norm, amount, date_month) to deduplicate
    # against GST Exp Register (same transaction appears in both registers)
    journal_seen = set()  # (vendor_norm, amount, date_month)

    # Process Journal Register entries
    for entry in tally_data.get("journal_register", {}).get("entries", []):
        key = _tally_entry_key("journal", entry)
        if key in matched_tally_keys:
            continue

        entry_type = entry.get("entry_type", "")
        if entry_type in ("tds_deduction", "salary", "discount", "other"):
            continue  # Not TDS-applicable expenses

        vendor = entry.get("particulars", "")
        if not vendor or not vendor.strip():
            continue  # Skip entries with no vendor/particulars

        vendor_norm = normalize_name(vendor)

        # Use individual posting amounts (not gross_total) as the expense amount
        # This avoids double-counting when gross_total includes non-expense heads
        postings = entry.get("account_postings", {})
        heads = [h for h in postings if h not in ("Gross Total", "Value")]

        date_str = str(entry.get("date", ""))[:7]  # YYYY-MM

        for head in heads:
            head_amount = abs(postings.get(head, 0))
            if head_amount == 0:
                continue

            # Record for dedup against GST Exp Register
            journal_seen.add((vendor_norm, round(head_amount, 0), date_str, head.lower()))

            sections = classify_expense_head(head)
            ve = vendor_expenses[(vendor_norm, tuple(sorted(sections)))]
            ve["total_amount"] += head_amount
            ve["entries"].append(entry)
            ve["expense_heads"].add(head)
            ve["vendor_name"] = vendor
            ve["expected_sections"].update(sections)

    # Track cross-register duplicates for flagging
    cross_register_dupes = []  # list of (vendor, amount, head, journal_date, gst_date)

    # Process GST Exp Register entries — flag duplicates with journal for review
    for entry in tally_data.get("purchase_gst_exp_register", {}).get("entries", []):
        key = _tally_entry_key("gst_exp", entry)
        if key in matched_tally_keys:
            continue

        vendor = entry.get("particulars", "")
        if not vendor or not vendor.strip():
            continue

        vendor_norm = normalize_name(vendor)
        base_amount = entry.get("base_amount", 0) or 0
        date_str = str(entry.get("date", ""))[:7]

        heads = list((entry.get("expense_heads") or {}).keys())

        # Check for duplicates: if journal already has this vendor + amount + month
        # for the same expense head, count once but flag for human review
        is_duped = False
        for head in heads:
            head_lower = head.lower().replace("_18%", "").replace("_12%", "").replace("_5%", "").strip()
            dedup_key = (vendor_norm, round(abs(base_amount), 0), date_str, head_lower)
            if dedup_key in journal_seen:
                is_duped = True
                cross_register_dupes.append({
                    "vendor": vendor,
                    "amount": base_amount,
                    "head": head,
                    "date": date_str,
                })
                break

        if is_duped:
            continue  # Counted from journal — will be flagged for review below

        for head in heads:
            sections = classify_expense_head(head)
            ve = vendor_expenses[(vendor_norm, tuple(sorted(sections)))]
            ve["total_amount"] += base_amount
            ve["entries"].append(entry)
            ve["expense_heads"].add(head)
            ve["vendor_name"] = vendor
            ve["expected_sections"].update(sections)

    # Now check each vendor group against thresholds
    for (vendor_norm, sections_tuple), ve in vendor_expenses.items():
        expected_sections = ve["expected_sections"] - {"unknown"}
        if not expected_sections:
            continue

        # Check if vendor has Form 26 entries in any expected section
        # Use both exact and fuzzy name matching
        vendor_in_f26 = False
        fuzzy_match_name = None
        for sec in expected_sections:
            f26_vendors = f26_vendors_by_section.get(sec, set())
            if vendor_norm in f26_vendors:
                vendor_in_f26 = True
                break
            # Fuzzy: check if any F26 vendor name is a substring or shares tokens
            vendor_tokens = set(vendor_norm.split())
            for f26_v in f26_vendors:
                f26_tokens = set(f26_v.split())
                overlap = vendor_tokens & f26_tokens
                # If >50% tokens overlap, consider it a likely match
                if overlap and len(overlap) >= min(len(vendor_tokens), len(f26_tokens)) * 0.5:
                    vendor_in_f26 = True
                    fuzzy_match_name = f26_v
                    break
            if vendor_in_f26:
                break

        if vendor_in_f26:
            continue  # Already has Form 26 entries (exact or fuzzy)

        total = ve["total_amount"]
        if total <= 0:
            continue

        # Check against threshold for each expected section
        for sec in expected_sections:
            threshold = TDS_THRESHOLDS.get(sec, {}).get("aggregate_annual")
            if threshold and total < threshold:
                continue  # Below threshold — no TDS required

            # Collect review flags
            review_reasons = []

            # Flag 1: Year-end or quarter-end entries that don't fit in one go
            entry_dates = set()
            for ent in ve["entries"]:
                d = str(ent.get("date", ""))[:10]
                entry_dates.add(d)
            quarter_ends = {"03-31", "06-30", "09-30", "12-31"}
            qe_dates = [d for d in entry_dates if any(qe in d for qe in quarter_ends)]
            non_qe_dates = [d for d in entry_dates if not any(qe in d for qe in quarter_ends)]
            if qe_dates and non_qe_dates:
                review_reasons.append(
                    f"Has entries on quarter/year-end dates ({', '.join(sorted(qe_dates))}) "
                    f"alongside other dates — may include provisions or reversals."
                )

            # Flag 2: Cross-register duplicates for this vendor
            vendor_dupes = [d for d in cross_register_dupes
                            if normalize_name(d["vendor"]) == vendor_norm]
            if vendor_dupes:
                dupe_amt = vendor_dupes[0]["amount"]
                review_reasons.append(
                    f"Same transaction (₹{dupe_amt:,.0f}) appears in both "
                    f"Journal Register and GST Exp Register — counted once from "
                    f"Journal. Please confirm these are the same entry."
                )

            # Flag 3: Cr/Dr direction info (read but not interpreted)
            cr_entries = []
            dr_entries = []
            for ent in ve["entries"]:
                direction = ent.get("gross_total_direction", "")
                if direction == "cr":
                    cr_entries.append(ent)
                elif direction == "dr":
                    dr_entries.append(ent)
            if cr_entries and dr_entries:
                review_reasons.append(
                    f"Has both Dr ({len(dr_entries)}) and Cr ({len(cr_entries)}) "
                    f"entries — Cr entries may be reversals. Verify net expense."
                )

            needs_review = len(review_reasons) > 0
            severity = "error" if total >= (threshold or 0) else "warning"
            if needs_review:
                severity = "warning"

            review_note = ""
            if review_reasons:
                review_note = " Review: " + " | ".join(review_reasons)

            findings.append({
                "check": "missing_tds",
                "severity": severity,
                "vendor": ve["vendor_name"],
                "vendor_normalized": vendor_norm,
                "expected_section": sec,
                "aggregate_amount": round(total, 2),
                "threshold": threshold,
                "num_tally_entries": len(ve["entries"]),
                "expense_heads": sorted(ve["expense_heads"]),
                "needs_review": needs_review,
                "review_reasons": review_reasons,
                "message": (f"No Form 26 entry found for {ve['vendor_name']} "
                            f"under {sec}. Tally shows ₹{total:,.0f} in "
                            f"{', '.join(sorted(ve['expense_heads']))}. "
                            f"TDS may be missing.{review_note}"),
            })

    return findings


def _tally_entry_key(source: str, entry: dict) -> str:
    """Create a unique key for a tally entry to track which are already matched."""
    return f"{source}|{entry.get('particulars','')}|{entry.get('voucher_no','')}|{entry.get('date','')}"


def build_matched_tally_keys(matches: list[dict]) -> set[str]:
    """Extract unique keys for all tally entries that were matched."""
    keys = set()
    for m in matches:
        for t in m.get("tally_entries", []):
            src = t.get("tally_source", "")
            # Map matcher source names back to register sources
            if src in ("journal_interest", "journal_freight"):
                src = "journal"
            elif src == "gst_exp":
                src = "gst_exp"
            else:
                src = src
            keys.add(f"{src}|{t.get('party_name','')}|{t.get('voucher_no','')}|{t.get('date','')}")
    return keys


# ---------------------------------------------------------------------------
# Main Runner
# ---------------------------------------------------------------------------

def run(parsed_dir: str, results_dir: str, event_callback=None) -> dict:
    """Run all TDS compliance checks.

    Args:
        parsed_dir: Path to parsed data (parsed_form26.json, parsed_tally.json)
        results_dir: Path to results (match_results.json, output checker_results.json)
        event_callback: Optional callable(agent, message, type) for real-time progress.
    """

    def emit(message, type="detail"):
        if event_callback:
            event_callback("TDS Checker", message, type)
        print(f"  [{type}] {message}")

    parsed_path = Path(parsed_dir)
    results_path = Path(results_dir)

    # Load data
    with open(parsed_path / "parsed_form26.json") as f:
        form26_data = json.load(f)
    with open(parsed_path / "parsed_tally.json") as f:
        tally_data = json.load(f)
    with open(results_path / "match_results.json") as f:
        match_data = json.load(f)

    form26_entries = form26_data["entries"]
    matches = match_data["matches"]

    all_findings = []

    # ---- Section Validation ----
    emit(f"Validating TDS sections for {len(matches)} matched entries...")
    section_findings = []
    for m in matches:
        finding = check_section(m)
        if finding:
            section_findings.append(finding)
    all_findings.extend(section_findings)
    if section_findings:
        emit(f"{len(section_findings)} section classification issues found", "warning")
    else:
        emit("All sections correctly classified", "success")

    # ---- Rate Validation ----
    emit("Validating TDS rates against Income Tax rules...")
    rate_findings = []
    for m in matches:
        finding = check_rate(m)
        if finding:
            rate_findings.append(finding)
    all_findings.extend(rate_findings)
    if rate_findings:
        emit(f"{len(rate_findings)} rate mismatches found", "warning")
    else:
        emit("All TDS rates correct", "success")

    # ---- Base Amount Validation ----
    emit("Checking if TDS computed on correct base amount (pre-GST)...")
    base_findings = []
    for m in matches:
        finding = check_base_amount(m)
        if finding:
            base_findings.append(finding)
    all_findings.extend(base_findings)
    if base_findings:
        emit(f"{len(base_findings)} base amount issues — TDS may be on GST-inclusive amount", "warning")
    else:
        emit("All base amounts correct", "success")

    # ---- Threshold Validation ----
    emit("Checking threshold compliance across vendors...")
    threshold_findings = check_thresholds(matches)
    all_findings.extend(threshold_findings)
    below_count = sum(1 for f in threshold_findings if "below" in f.get("status", ""))
    if below_count:
        emit(f"{below_count} vendors below annual threshold (TDS not mandatory)")

    # ---- Missing TDS Detection ----
    # Count TDS-applicable entries by expense type for natural progress
    jr_entries = tally_data.get("journal_register", {}).get("entries", [])
    gst_entries = tally_data.get("purchase_gst_exp_register", {}).get("entries", [])
    interest_count = sum(1 for e in jr_entries if e.get("entry_type") == "interest_payment")
    freight_count = sum(1 for e in jr_entries if e.get("entry_type") == "freight_expense")
    brokerage_count = sum(1 for e in jr_entries if e.get("entry_type") == "brokerage")
    professional_count = sum(1 for e in jr_entries if e.get("entry_type") in ("professional_fees", "consultancy", "audit_fees"))
    emit("Scanning books for entries where TDS may be missing...")
    if interest_count:
        emit(f"Scanning interest expenses... {interest_count} entries")
    if freight_count:
        emit(f"Scanning contractor/freight expenses... {freight_count} entries")
    if brokerage_count:
        emit(f"Scanning brokerage/commission expenses... {brokerage_count} entries")
    if professional_count:
        emit(f"Scanning professional/consultancy fees... {professional_count} entries")
    if gst_entries:
        emit(f"Scanning GST expense register... {len(gst_entries)} entries")
    matched_keys = build_matched_tally_keys(matches)
    missing_findings = detect_missing_tds(tally_data, form26_entries, matched_keys)
    all_findings.extend(missing_findings)
    review_count = sum(1 for f in missing_findings if f.get("needs_review"))
    error_count = sum(1 for f in missing_findings if f["severity"] == "error")
    if missing_findings:
        parts = []
        if error_count:
            parts.append(f"{error_count} missing TDS")
        if review_count:
            parts.append(f"{review_count} flagged for review")
        emit(f"Found {', '.join(parts)}", "warning")
    else:
        emit("No missing TDS detected", "success")

    # ---- Summarize ----
    summary = {
        "total_findings": len(all_findings),
        "by_check": {
            "section_validation": len(section_findings),
            "rate_validation": len(rate_findings),
            "base_amount_validation": len(base_findings),
            "threshold_validation": len(threshold_findings),
            "missing_tds": len(missing_findings),
        },
        "by_severity": {
            "error": sum(1 for f in all_findings if f["severity"] == "error"),
            "warning": sum(1 for f in all_findings if f["severity"] == "warning"),
            "info": sum(1 for f in all_findings if f["severity"] == "info"),
        },
        "matches_checked": len(matches),
        "sections_in_scope": sorted(set(m["form26_entry"]["section"] for m in matches)),
    }

    results = {
        "run_timestamp": datetime.now().isoformat(),
        "summary": summary,
        "findings": all_findings,
    }

    # Write output
    out_file = results_path / "checker_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[TDS Checker] Wrote {out_file}")

    # Print summary
    print("\n" + "=" * 60)
    print("TDS CHECKER AGENT — SUMMARY")
    print("=" * 60)
    print(f"\nMatches checked: {summary['matches_checked']}")
    print(f"Sections in scope: {', '.join(summary['sections_in_scope'])}")
    print(f"\nTotal findings: {summary['total_findings']}")
    print(f"  Errors:   {summary['by_severity']['error']}")
    print(f"  Warnings: {summary['by_severity']['warning']}")
    print(f"  Info:     {summary['by_severity']['info']}")
    print(f"\nBy check:")
    for check, count in summary["by_check"].items():
        print(f"  {check}: {count}")

    if all_findings:
        print(f"\n{'─' * 60}")
        print("TOP FINDINGS:")
        print(f"{'─' * 60}")
        # Show errors first, then warnings
        for f in sorted(all_findings, key=lambda x: {"error": 0, "warning": 1, "info": 2}[x["severity"]]):
            icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}[f["severity"]]
            print(f"\n  {icon} [{f['severity'].upper()}] {f['check']}")
            print(f"    {f['message']}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    parsed = base / "data" / "parsed"
    output = base / "data" / "results"

    run(str(parsed), str(output))
