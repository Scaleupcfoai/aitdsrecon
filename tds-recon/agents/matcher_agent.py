"""
Matcher Agent — TDS Reconciliation MVP
=======================================
5-pass matching engine that reconciles Form 26 entries against Tally entries.

Pass 1: Exact match      — party name + amount + date
Pass 2: GST-adjusted     — Tally base_amount (pre-GST) = Form 26 amount
Pass 3: TDS-exempt filter — skip entries where TDS not applicable
Pass 4: Fuzzy match       — name similarity + amount tolerance + date range
Pass 5: Aggregated match  — sum multiple Tally entries per vendor/period → Form 26

After each pass: matched entries move out, unmatched carry forward.
After all passes: remaining = truly unmatched → human review.

Inputs:  data/parsed/parsed_form26.json, data/parsed/parsed_tally.json
Outputs: data/results/match_results.json
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Sections we're reconciling in this MVP
TARGET_SECTIONS = {"194A", "194C"}

# Amount tolerance for fuzzy matching (as fraction)
FUZZY_AMOUNT_TOLERANCE = 0.005  # 0.5%

# Date tolerance for fuzzy matching
FUZZY_DATE_DAYS = 30

# GST rates to try when adjusting
GST_RATES = [0.18, 0.12, 0.05, 0.28]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(d) -> datetime | None:
    """Parse date from ISO string."""
    if isinstance(d, datetime):
        return d
    if isinstance(d, str):
        try:
            return datetime.fromisoformat(d)
        except ValueError:
            return None
    return None


def normalize_name(name: str) -> str:
    """Normalize vendor name for comparison: lowercase, strip suffixes."""
    if not name:
        return ""
    n = name.lower().strip()
    # Remove common suffixes
    for suffix in ["pvt. ltd.", "pvt ltd", "private limited", "ltd.", "ltd",
                   "llp", "lp", "inc.", "inc", "co.", "company"]:
        n = n.replace(suffix, "")
    # Remove parenthetical IDs like "(34)"
    n = re.sub(r"\(\d+\)", "", n)
    # Remove extra whitespace
    n = re.sub(r"\s+", " ", n).strip()
    return n


def name_similarity(a: str, b: str) -> float:
    """Simple token-overlap similarity between two normalized names."""
    tokens_a = set(normalize_name(a).split())
    tokens_b = set(normalize_name(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    # Jaccard-like but weighted toward the shorter name
    return len(intersection) / min(len(tokens_a), len(tokens_b))


def amount_close(a: float, b: float, tolerance: float = FUZZY_AMOUNT_TOLERANCE) -> bool:
    """Check if two amounts are within tolerance."""
    if a == 0 and b == 0:
        return True
    if a == 0 or b == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) <= tolerance


def get_month_key(date_str: str) -> str:
    """Extract YYYY-MM from a date string."""
    d = parse_date(date_str)
    if d:
        return f"{d.year}-{d.month:02d}"
    return ""


def get_quarter_end(date_str: str) -> str:
    """Get the quarter-end month for a date (for Form 26 quarterly grouping)."""
    d = parse_date(date_str)
    if not d:
        return ""
    quarter_ends = {
        1: "03", 2: "03", 3: "03",     # Q4: Jan-Mar → Mar 31
        4: "06", 5: "06", 6: "06",     # Q1: Apr-Jun → Jun 30
        7: "09", 8: "09", 9: "09",     # Q2: Jul-Sep → Sep 30
        10: "12", 11: "12", 12: "12",  # Q3: Oct-Dec → Dec 31
    }
    qm = quarter_ends[d.month]
    return f"{d.year}-{qm}"


def to_serializable(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


# ---------------------------------------------------------------------------
# Build Tally lookup structures
# ---------------------------------------------------------------------------

def build_tally_194a_entries(tally: dict) -> list[dict]:
    """
    Extract 194A-relevant entries from Tally Journal Register.
    These are interest_payment entries with loan_party identified.
    """
    entries = []
    for e in tally["journal_register"]["entries"]:
        if e["entry_type"] == "interest_payment" and e.get("loan_party"):
            amount = e["account_postings"].get("Interest Paid", 0)
            entries.append({
                "tally_source": "journal_interest",
                "date": e["date"],
                "party_name": e["loan_party"],
                "amount": amount,
                "voucher_no": e["voucher_no"],
                "raw": e,
                "_matched": False,
            })
    return entries


def build_tally_194c_entries(tally: dict) -> list[dict]:
    """
    Extract 194C-relevant entries from Tally.

    Sources:
    1. Journal Register — freight_expense entries (Inland World)
    2. Purchase GST Exp Register — contractor expenses (Amrita, Anderson, Andreal)
       Uses BASE amount (pre-GST) since TDS is on base amount.
    """
    entries = []

    # From Journal Register: freight expenses
    for e in tally["journal_register"]["entries"]:
        if e["entry_type"] == "freight_expense" and e.get("particulars"):
            amount = e["account_postings"].get("Freight Charges", 0)
            entries.append({
                "tally_source": "journal_freight",
                "date": e["date"],
                "party_name": e["particulars"],
                "amount": amount,
                "amount_is_base": True,  # freight in journal = base amount (no GST)
                "voucher_no": e["voucher_no"],
                "raw": e,
                "_matched": False,
            })

    # From Purchase GST Exp Register: service/contractor expenses
    for e in tally["purchase_gst_exp_register"]["entries"]:
        if e.get("particulars"):
            entries.append({
                "tally_source": "gst_exp",
                "date": e["date"],
                "party_name": e["particulars"],
                "amount": e["base_amount"],  # Use BASE amount for TDS comparison
                "gross_amount": e["gross_total"],
                "total_gst": e["total_gst"],
                "amount_is_base": True,
                "voucher_no": e["voucher_no"],
                "expense_heads": e.get("expense_heads", {}),
                "raw": e,
                "_matched": False,
            })

    return entries


# ---------------------------------------------------------------------------
# Pass 1: Exact Match
# ---------------------------------------------------------------------------

def pass1_exact_match(form26_entries: list[dict], tally_entries: list[dict]) -> list[dict]:
    """
    Exact match: same party name (normalized) + same amount + same date.
    """
    matches = []

    for f26 in form26_entries:
        if f26.get("_matched"):
            continue

        f26_name = normalize_name(f26["vendor_name"])
        f26_amount = f26["amount_paid"]
        f26_date = parse_date(f26["amount_paid_date"])

        for tally in tally_entries:
            if tally.get("_matched"):
                continue

            tally_name = normalize_name(tally["party_name"])
            tally_date = parse_date(tally["date"])

            # Name must match
            if f26_name != tally_name:
                continue

            # Amount must be exact
            if f26_amount != tally["amount"]:
                continue

            # Date within 3 days
            if f26_date and tally_date and abs((f26_date - tally_date).days) > 3:
                continue

            # Match found
            matches.append({
                "pass": 1,
                "pass_name": "exact_match",
                "confidence": 1.0,
                "form26_entry": _clean_entry(f26),
                "tally_entries": [_clean_entry(tally)],
                "match_details": {
                    "name_match": f"'{f26['vendor_name']}' = '{tally['party_name']}'",
                    "amount_match": f"{f26_amount} = {tally['amount']}",
                    "date_diff_days": abs((f26_date - tally_date).days) if f26_date and tally_date else None,
                },
            })
            f26["_matched"] = True
            tally["_matched"] = True
            break

    return matches


# ---------------------------------------------------------------------------
# Pass 2: GST-Adjusted Match
# ---------------------------------------------------------------------------

def pass2_gst_adjusted(form26_entries: list[dict], tally_entries: list[dict]) -> list[dict]:
    """
    GST-adjusted match: Form 26 amount = Tally base_amount (pre-GST).

    For 194C: TDS is deducted on the base amount (excluding GST).
    The parser already computes base_amount from the GST expense register.
    This pass matches Form 26 amount to the pre-computed base_amount.

    Rules:
    - Only uses base_amount already computed by parser (no guessing GST rates)
    - Requires name similarity >= 0.5
    - Requires date within same quarter (90 days)
    - Only for entries from gst_exp source (which have GST breakup)
    """
    matches = []

    for f26 in form26_entries:
        if f26.get("_matched"):
            continue

        f26_amount = f26["amount_paid"]
        f26_date = parse_date(f26["amount_paid_date"])

        for tally in tally_entries:
            if tally.get("_matched"):
                continue

            # Only apply GST adjustment to entries that actually have GST
            if tally.get("tally_source") != "gst_exp":
                continue

            # Name must be similar
            if name_similarity(f26["vendor_name"], tally["party_name"]) < 0.5:
                continue

            # Date must be within same quarter (90 days)
            tally_date = parse_date(tally["date"])
            if f26_date and tally_date and abs((f26_date - tally_date).days) > 90:
                continue

            # Base amount must match Form 26 amount
            if amount_close(f26_amount, tally["amount"]):
                matches.append({
                    "pass": 2,
                    "pass_name": "gst_adjusted_base",
                    "confidence": 0.95,
                    "form26_entry": _clean_entry(f26),
                    "tally_entries": [_clean_entry(tally)],
                    "match_details": {
                        "name_similarity": name_similarity(f26["vendor_name"], tally["party_name"]),
                        "form26_amount": f26_amount,
                        "tally_base_amount": tally["amount"],
                        "tally_gross": tally.get("gross_amount", tally["amount"]),
                        "tally_gst": tally.get("total_gst", 0),
                    },
                })
                f26["_matched"] = True
                tally["_matched"] = True
                break

    return matches


# ---------------------------------------------------------------------------
# Pass 3: TDS-Exempt Filter
# ---------------------------------------------------------------------------

def pass3_exempt_filter(form26_entries: list[dict], tally_entries: list[dict]) -> list[dict]:
    """
    Mark Tally entries as exempt (not requiring TDS) so they don't
    pollute the unmatched list.

    For 194C: Expenses below ₹30,000 single / ₹1,00,000 aggregate
              (simplified: we flag very small entries)
    For 194A: Interest below ₹5,000 threshold

    Returns list of entries flagged as exempt (not real matches).
    """
    exempt = []

    for tally in tally_entries:
        if tally.get("_matched"):
            continue

        amount = tally.get("amount", 0)

        # Very small amounts unlikely to have TDS
        # (This is a simplified heuristic for MVP)
        if amount and abs(amount) < 100:
            exempt.append({
                "pass": 3,
                "pass_name": "exempt_filter",
                "reason": f"Amount {amount} below minimum threshold",
                "tally_entry": _clean_entry(tally),
            })
            tally["_matched"] = True  # Remove from further matching

    return exempt


# ---------------------------------------------------------------------------
# Pass 4: Fuzzy Match
# ---------------------------------------------------------------------------

def pass4_fuzzy_match(form26_entries: list[dict], tally_entries: list[dict]) -> list[dict]:
    """
    Fuzzy match: name similarity + amount tolerance (±0.5%) + date range (±30 days).
    Catches name variations and small rounding differences.
    """
    matches = []

    for f26 in form26_entries:
        if f26.get("_matched"):
            continue

        f26_amount = f26["amount_paid"]
        f26_date = parse_date(f26["amount_paid_date"])

        best_match = None
        best_score = 0

        for tally in tally_entries:
            if tally.get("_matched"):
                continue

            # Name similarity
            sim = name_similarity(f26["vendor_name"], tally["party_name"])
            if sim < 0.4:
                continue

            # Amount within tolerance
            if not amount_close(f26_amount, tally["amount"], FUZZY_AMOUNT_TOLERANCE):
                continue

            # Date within range
            tally_date = parse_date(tally["date"])
            if f26_date and tally_date:
                if abs((f26_date - tally_date).days) > FUZZY_DATE_DAYS:
                    continue

            # Score: weighted combination
            amount_diff = abs(f26_amount - tally["amount"]) / max(f26_amount, 1)
            score = sim * 0.5 + (1 - amount_diff) * 0.5

            if score > best_score:
                best_score = score
                best_match = tally

        if best_match and best_score > 0.5:
            matches.append({
                "pass": 4,
                "pass_name": "fuzzy_match",
                "confidence": round(best_score, 3),
                "form26_entry": _clean_entry(f26),
                "tally_entries": [_clean_entry(best_match)],
                "match_details": {
                    "name_similarity": name_similarity(f26["vendor_name"], best_match["party_name"]),
                    "amount_diff": abs(f26_amount - best_match["amount"]),
                    "amount_diff_pct": round(abs(f26_amount - best_match["amount"]) / max(f26_amount, 1) * 100, 3),
                },
            })
            f26["_matched"] = True
            best_match["_matched"] = True

    return matches


# ---------------------------------------------------------------------------
# Pass 5: Aggregated Match
# ---------------------------------------------------------------------------

def pass5_aggregated_match(form26_entries: list[dict], tally_entries: list[dict]) -> list[dict]:
    """
    Aggregated match: Sum multiple Tally entries for the same vendor
    within a period → compare to a single Form 26 entry.

    This handles:
    - Inland World: many small freight invoices → one monthly TDS entry
    - Amrita/Anderson/Andreal: multiple expense invoices → one quarterly TDS entry

    Grouping strategies:
    1. By month (for monthly TDS deposits like Inland World freight)
    2. By quarter (for quarterly consolidated entries)
    3. Cumulative up to Form 26 date (for running total matching)
    """
    matches = []

    # Group unmatched Tally entries by normalized vendor name
    vendor_entries = defaultdict(list)
    for tally in tally_entries:
        if tally.get("_matched"):
            continue
        vendor_key = normalize_name(tally["party_name"])
        vendor_entries[vendor_key].append(tally)

    for f26 in form26_entries:
        if f26.get("_matched"):
            continue

        f26_name = normalize_name(f26["vendor_name"])
        f26_amount = f26["amount_paid"]
        f26_date = parse_date(f26["amount_paid_date"])
        f26_month = get_month_key(f26["amount_paid_date"])

        # Find BEST matching vendor group (highest name similarity)
        matched_vendor_key = None
        best_vendor_sim = 0
        for vendor_key in vendor_entries:
            sim = name_similarity(f26["vendor_name"], vendor_key)
            if sim > best_vendor_sim:
                best_vendor_sim = sim
                matched_vendor_key = vendor_key

        # Require minimum similarity
        if best_vendor_sim < 0.5:
            matched_vendor_key = None

        if not matched_vendor_key:
            continue

        available = [e for e in vendor_entries[matched_vendor_key] if not e.get("_matched")]
        if not available:
            continue

        # Strategy 1: Monthly aggregation — sum entries in the same month as Form 26
        month_entries = [e for e in available if get_month_key(e["date"]) == f26_month]
        month_sum = sum(e["amount"] for e in month_entries)

        if month_entries and amount_close(f26_amount, month_sum, 0.005):
            matches.append({
                "pass": 5,
                "pass_name": "aggregated_monthly",
                "confidence": 0.90,
                "form26_entry": _clean_entry(f26),
                "tally_entries": [_clean_entry(e) for e in month_entries],
                "match_details": {
                    "strategy": "monthly_sum",
                    "form26_amount": f26_amount,
                    "tally_sum": month_sum,
                    "num_tally_entries": len(month_entries),
                    "diff": round(f26_amount - month_sum, 2),
                },
            })
            f26["_matched"] = True
            for e in month_entries:
                e["_matched"] = True
            continue

        # Strategy 2: Cumulative up to Form 26 date (for entries deposited in bulk)
        # This handles Anderson/Andreal pattern where TDS is deposited for
        # all invoices up to a certain date that haven't been covered yet
        cumulative_entries = sorted(
            [e for e in available
             if parse_date(e["date"]) and f26_date and parse_date(e["date"]) <= f26_date],
            key=lambda e: e["date"]
        )
        cumulative_sum = sum(e["amount"] for e in cumulative_entries)

        if cumulative_entries and amount_close(f26_amount, cumulative_sum, 0.005):
            matches.append({
                "pass": 5,
                "pass_name": "aggregated_cumulative",
                "confidence": 0.85,
                "form26_entry": _clean_entry(f26),
                "tally_entries": [_clean_entry(e) for e in cumulative_entries],
                "match_details": {
                    "strategy": "cumulative_to_date",
                    "form26_amount": f26_amount,
                    "tally_sum": cumulative_sum,
                    "num_tally_entries": len(cumulative_entries),
                    "diff": round(f26_amount - cumulative_sum, 2),
                },
            })
            f26["_matched"] = True
            for e in cumulative_entries:
                e["_matched"] = True
            continue

        # Strategy 2b: Subset-sum search — find the subset of available entries
        # whose amounts sum to the Form 26 amount. Handles cases where only
        # some of the available entries were included in this TDS deposit.
        if len(cumulative_entries) <= 20:  # Keep it tractable
            subset = _find_subset_sum(cumulative_entries, f26_amount, 0.005)
            if subset:
                matches.append({
                    "pass": 5,
                    "pass_name": "aggregated_subset",
                    "confidence": 0.80,
                    "form26_entry": _clean_entry(f26),
                    "tally_entries": [_clean_entry(e) for e in subset],
                    "match_details": {
                        "strategy": "subset_sum_to_date",
                        "form26_amount": f26_amount,
                        "tally_sum": sum(e["amount"] for e in subset),
                        "num_tally_entries": len(subset),
                        "diff": round(f26_amount - sum(e["amount"] for e in subset), 2),
                    },
                })
                f26["_matched"] = True
                for e in subset:
                    e["_matched"] = True
                continue

        # Strategy 3: All available for vendor (deposit date may precede invoice dates)
        # This handles cases where Form 26 deposit date is earlier than some
        # invoices it covers (e.g., deposit on Mar 1, invoices through Mar 20)
        all_sum = sum(e["amount"] for e in available)
        if amount_close(f26_amount, all_sum, 0.005):
            matches.append({
                "pass": 5,
                "pass_name": "aggregated_all_available",
                "confidence": 0.75,
                "form26_entry": _clean_entry(f26),
                "tally_entries": [_clean_entry(e) for e in available],
                "match_details": {
                    "strategy": "all_available_for_vendor",
                    "form26_amount": f26_amount,
                    "tally_sum": all_sum,
                    "num_tally_entries": len(available),
                    "note": "F26 deposit date may precede invoice dates",
                    "diff": round(f26_amount - all_sum, 2),
                },
            })
            f26["_matched"] = True
            for e in available:
                e["_matched"] = True
            continue

        # Strategy 3b: Subset-sum on all available (not just up to date)
        if len(available) <= 20:
            subset = _find_subset_sum(available, f26_amount, 0.005)
            if subset:
                matches.append({
                    "pass": 5,
                    "pass_name": "aggregated_subset_all",
                    "confidence": 0.70,
                    "form26_entry": _clean_entry(f26),
                    "tally_entries": [_clean_entry(e) for e in subset],
                    "match_details": {
                        "strategy": "subset_sum_all_available",
                        "form26_amount": f26_amount,
                        "tally_sum": sum(e["amount"] for e in subset),
                        "num_tally_entries": len(subset),
                        "diff": round(f26_amount - sum(e["amount"] for e in subset), 2),
                    },
                })
                f26["_matched"] = True
                for e in subset:
                    e["_matched"] = True
                continue

        # Strategy 4: Quarter grouping
        f26_quarter = get_quarter_end(f26["amount_paid_date"])
        quarter_entries = [e for e in available if get_quarter_end(e["date"]) == f26_quarter]
        quarter_sum = sum(e["amount"] for e in quarter_entries)

        if quarter_entries and amount_close(f26_amount, quarter_sum, 0.005):
            matches.append({
                "pass": 5,
                "pass_name": "aggregated_quarterly",
                "confidence": 0.85,
                "form26_entry": _clean_entry(f26),
                "tally_entries": [_clean_entry(e) for e in quarter_entries],
                "match_details": {
                    "strategy": "quarterly_sum",
                    "form26_amount": f26_amount,
                    "tally_sum": quarter_sum,
                    "num_tally_entries": len(quarter_entries),
                    "diff": round(f26_amount - quarter_sum, 2),
                },
            })
            f26["_matched"] = True
            for e in quarter_entries:
                e["_matched"] = True
            continue

    return matches


# ---------------------------------------------------------------------------
# Clean entry for output (remove internal fields and large raw data)
# ---------------------------------------------------------------------------

def _find_subset_sum(entries: list[dict], target: float, tolerance: float) -> list[dict] | None:
    """
    Find a subset of entries whose amounts sum to target (within tolerance).
    Uses greedy approach: sort by date, accumulate until we hit target.
    Falls back to trying without each entry if greedy doesn't work.
    """
    if not entries:
        return None

    # Greedy: accumulate in date order until sum matches
    sorted_entries = sorted(entries, key=lambda e: e["date"])
    running = 0
    subset = []
    for e in sorted_entries:
        running += e["amount"]
        subset.append(e)
        if amount_close(target, running, tolerance):
            return subset
        if running > target * (1 + tolerance):
            break  # Overshot

    # If greedy failed, try removing one entry at a time from the overshot set
    if subset and running > target:
        for i, e in enumerate(subset):
            reduced = running - e["amount"]
            if amount_close(target, reduced, tolerance):
                return [x for j, x in enumerate(subset) if j != i]

    return None


def _clean_entry(entry: dict) -> dict:
    """Remove internal tracking fields and bulky raw data from output."""
    cleaned = {}
    for k, v in entry.items():
        if k.startswith("_"):
            continue
        if k == "raw":
            continue  # Skip the full raw entry to keep output manageable
        cleaned[k] = v
    return cleaned


# ---------------------------------------------------------------------------
# Main — Run Matcher Agent
# ---------------------------------------------------------------------------

def run(parsed_dir: str, output_dir: str, sections: set | None = None):
    """Run the 5-pass matching engine."""

    parsed_dir = Path(parsed_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sections = sections or TARGET_SECTIONS

    # Load parsed data
    with open(parsed_dir / "parsed_form26.json") as f:
        form26_data = json.load(f)
    with open(parsed_dir / "parsed_tally.json") as f:
        tally_data = json.load(f)

    # Filter Form 26 to target sections
    form26_entries = [
        {**e, "_matched": False}
        for e in form26_data["entries"]
        if e["section"] in sections
    ]

    print(f"[Matcher] {len(form26_entries)} Form 26 entries for sections {sections}")

    # Build Tally entry pools
    tally_194a = build_tally_194a_entries(tally_data)
    tally_194c = build_tally_194c_entries(tally_data)
    print(f"[Matcher] {len(tally_194a)} Tally 194A entries (interest payments)")
    print(f"[Matcher] {len(tally_194c)} Tally 194C entries (freight + GST expenses)")

    # Split Form 26 by section
    f26_194a = [e for e in form26_entries if e["section"] == "194A"]
    f26_194c = [e for e in form26_entries if e["section"] == "194C"]

    all_matches = []
    all_exemptions = []

    # ---- Pass 1: Exact Match ----
    print("\n--- Pass 1: Exact Match ---")
    m1a = pass1_exact_match(f26_194a, tally_194a)
    m1c = pass1_exact_match(f26_194c, tally_194c)
    m1 = m1a + m1c
    all_matches.extend(m1)
    print(f"  194A: {len(m1a)} matches")
    print(f"  194C: {len(m1c)} matches")

    # ---- Pass 2: GST-Adjusted ----
    print("\n--- Pass 2: GST-Adjusted Match ---")
    m2a = pass2_gst_adjusted(f26_194a, tally_194a)
    m2c = pass2_gst_adjusted(f26_194c, tally_194c)
    m2 = m2a + m2c
    all_matches.extend(m2)
    print(f"  194A: {len(m2a)} matches")
    print(f"  194C: {len(m2c)} matches")

    # ---- Pass 3: Exempt Filter ----
    print("\n--- Pass 3: Exempt Filter ---")
    ex_a = pass3_exempt_filter(f26_194a, tally_194a)
    ex_c = pass3_exempt_filter(f26_194c, tally_194c)
    all_exemptions = ex_a + ex_c
    print(f"  {len(all_exemptions)} entries marked exempt")

    # ---- Pass 4: Fuzzy Match ----
    print("\n--- Pass 4: Fuzzy Match ---")
    m4a = pass4_fuzzy_match(f26_194a, tally_194a)
    m4c = pass4_fuzzy_match(f26_194c, tally_194c)
    m4 = m4a + m4c
    all_matches.extend(m4)
    print(f"  194A: {len(m4a)} matches")
    print(f"  194C: {len(m4c)} matches")

    # ---- Pass 5: Aggregated Match ----
    print("\n--- Pass 5: Aggregated Match ---")
    m5a = pass5_aggregated_match(f26_194a, tally_194a)
    m5c = pass5_aggregated_match(f26_194c, tally_194c)
    m5 = m5a + m5c
    all_matches.extend(m5)
    print(f"  194A: {len(m5a)} matches")
    print(f"  194C: {len(m5c)} matches")

    # ---- Collect unmatched ----
    unmatched_form26 = [_clean_entry(e) for e in form26_entries if not e.get("_matched")]
    unmatched_tally_194a = [_clean_entry(e) for e in tally_194a if not e.get("_matched")]
    unmatched_tally_194c = [_clean_entry(e) for e in tally_194c if not e.get("_matched")]

    # ---- Build output ----
    results = {
        "run_timestamp": datetime.now().isoformat(),
        "sections_processed": list(sections),
        "summary": {
            "form26_total": len(form26_entries),
            "form26_matched": sum(1 for e in form26_entries if e.get("_matched")),
            "form26_unmatched": len(unmatched_form26),
            "matches_by_pass": {
                "pass1_exact": len(m1),
                "pass2_gst_adjusted": len(m2),
                "pass3_exempt": len(all_exemptions),
                "pass4_fuzzy": len(m4),
                "pass5_aggregated": len(m5),
            },
            "total_matches": len(all_matches),
        },
        "matches": all_matches,
        "exemptions": all_exemptions,
        "unmatched_form26": unmatched_form26,
        "unmatched_tally_194a": unmatched_tally_194a,
        "unmatched_tally_194c": unmatched_tally_194c,
    }

    # ---- Write output ----
    out_file = output_dir / "match_results.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2, default=to_serializable)
    print(f"\n[Matcher] Wrote {out_file}")

    # ---- Print summary ----
    print("\n" + "=" * 60)
    print("MATCHER AGENT — SUMMARY")
    print("=" * 60)
    s = results["summary"]
    print(f"\nForm 26 entries: {s['form26_total']}")
    print(f"  Matched:   {s['form26_matched']}")
    print(f"  Unmatched: {s['form26_unmatched']}")
    print(f"\nMatches by pass:")
    for pass_name, count in s["matches_by_pass"].items():
        print(f"  {pass_name}: {count}")
    print(f"\nTotal matches: {s['total_matches']}")

    if unmatched_form26:
        print(f"\n⚠ Unmatched Form 26 entries ({len(unmatched_form26)}):")
        for e in unmatched_form26:
            print(f"  {e['section']} | {e['vendor_name']} | ₹{e['amount_paid']} | {e.get('amount_paid_date', '')[:10]}")

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    base = Path(__file__).parent.parent
    parsed = base / "data" / "parsed"
    output = base / "data" / "results"

    run(str(parsed), str(output))
