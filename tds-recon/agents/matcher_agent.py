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

# Learning Agent integration (optional — gracefully degrades if no rules exist)
try:
    from agents import learning_agent
    HAS_LEARNING_AGENT = True
except ImportError:
    try:
        from . import learning_agent
        HAS_LEARNING_AGENT = True
    except ImportError:
        HAS_LEARNING_AGENT = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Sections we're reconciling
TARGET_SECTIONS = {"192", "194A", "194C", "194H", "194J(b)", "194Q"}

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
    """Normalize vendor name for comparison: lowercase, strip suffixes and parentheticals."""
    if not name:
        return ""
    n = name.lower().strip()
    # Remove common suffixes
    for suffix in ["pvt. ltd.", "pvt ltd", "private limited", "limited", "ltd.", "ltd",
                   "llp", "lp", "inc.", "inc", "co.", "company"]:
        n = n.replace(suffix, "")
    # Remove ALL parentheticals: "(34)", "(Shirting Div.)", "(Loan)", "(Chhindwara)" etc.
    n = re.sub(r"\([^)]*\)", "", n)
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
    These are interest_payment entries. The party name comes from:
    1. loan_party field (if column has "(Loan)" suffix)
    2. Person-name columns in account postings (for entries without "(Loan)")
    """
    # Meta columns that are NOT person names
    INTEREST_META = {"interest paid", "tds payable", "gross total", "value"}

    entries = []
    for e in tally["journal_register"]["entries"]:
        if e["entry_type"] != "interest_payment":
            continue

        amount = e["account_postings"].get("Interest Paid", 0)
        if amount == 0:
            continue

        # Prefer loan_party if available
        if e.get("loan_party"):
            party = e["loan_party"]
        else:
            # Find person-name column(s) in postings
            party = None
            for col_name in e.get("account_postings", {}):
                if col_name.lower().strip() not in INTEREST_META:
                    party = col_name
                    break

        if not party:
            continue

        entries.append({
            "tally_source": "journal_interest",
            "date": e["date"],
            "party_name": party,
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


def build_tally_194h_entries(tally: dict) -> list[dict]:
    """
    Extract 194H-relevant entries from Tally Journal Register.
    These are brokerage/commission entries with 'Brokerage and Commission' posting.
    """
    entries = []
    for e in tally["journal_register"]["entries"]:
        if e["entry_type"] == "brokerage" and e.get("particulars"):
            amount = e["account_postings"].get("Brokerage and Commission", 0)
            if amount == 0:
                continue
            entries.append({
                "tally_source": "journal_brokerage",
                "date": e["date"],
                "party_name": e["particulars"],
                "amount": amount,
                "voucher_no": e["voucher_no"],
                "account_postings": e.get("account_postings", {}),
                "raw": e,
                "_matched": False,
            })
    return entries


def build_tally_194j_entries(tally: dict) -> list[dict]:
    """
    Extract 194J(b)-relevant entries from Tally.

    Sources:
    1. Journal Register — professional_fees, consultancy, audit_fees entries
    2. Purchase GST Exp Register — entries with professional/consultancy/audit expense heads
       Uses BASE amount (pre-GST) since TDS is on base amount.
    """
    entries = []

    # Professional expense heads to look for in GST register
    PROFESSIONAL_HEADS = {
        "professonal charges", "professional charges", "consultancy charges",
        "audit fees", "outstanding audit fees", "legal charges",
        "gst annual return charges", "domain charges",
    }

    # From Journal Register
    for e in tally["journal_register"]["entries"]:
        if e["entry_type"] in ("professional_fees", "consultancy", "audit_fees"):
            # Sum all non-meta postings as the amount
            postings = e.get("account_postings", {})
            amount = 0
            for k, v in postings.items():
                if k.lower().strip() in PROFESSIONAL_HEADS:
                    amount += v
            if amount == 0:
                amount = e.get("gross_total", 0) or 0
            if amount == 0:
                continue
            entries.append({
                "tally_source": "journal_professional",
                "date": e["date"],
                "party_name": e.get("particulars", ""),
                "amount": amount,
                "voucher_no": e["voucher_no"],
                "account_postings": postings,
                "raw": e,
                "_matched": False,
            })

    # From Purchase GST Exp Register — entries with professional expense heads
    for e in tally["purchase_gst_exp_register"]["entries"]:
        if not e.get("particulars"):
            continue
        heads = e.get("expense_heads", {})
        has_professional = any(
            h.lower().strip() in PROFESSIONAL_HEADS for h in heads
        )
        if has_professional:
            entries.append({
                "tally_source": "gst_exp_professional",
                "date": e["date"],
                "party_name": e["particulars"],
                "amount": e["base_amount"],
                "gross_amount": e["gross_total"],
                "total_gst": e["total_gst"],
                "amount_is_base": True,
                "voucher_no": e["voucher_no"],
                "expense_heads": heads,
                "raw": e,
                "_matched": False,
            })

    return entries


def build_tally_194q_entries(tally: dict) -> list[dict]:
    """
    Extract 194Q-relevant entries from Tally Purchase Register.

    194Q applies to purchase of goods exceeding ₹50 lakh aggregate.
    These are goods purchases (not services/expenses).

    Uses gross_total as the base amount since 194Q is on total purchase value.
    """
    entries = []
    for e in tally["purchase_register"]["entries"]:
        if not e.get("particulars"):
            continue
        # Use gross_total as the amount — 194Q TDS is on the purchase value
        amount = e.get("gross_total", 0) or 0
        if amount == 0:
            continue
        entries.append({
            "tally_source": "purchase_register",
            "date": e["date"],
            "party_name": e["particulars"],
            "amount": amount,
            "purchase_value": e.get("purchase_value", 0),
            "total_gst": e.get("total_gst", 0),
            "voucher_no": e["voucher_no"],
            "raw": e,
            "_matched": False,
        })
    return entries


def build_tally_192_entries(tally: dict) -> list[dict]:
    """
    Extract Section 192-relevant entries from Tally Journal Register.
    These are salary entries — both regular staff salary and director's salary.

    For director salary: the journal entry has Director's Salary posting
    with individual person columns (e.g., "Adi Debnath": 675000).

    Form 24 uses abbreviated names (e.g., "AD (D1)"), so matching will
    rely on amount + date rather than name.
    """
    entries = []
    for e in tally["journal_register"]["entries"]:
        if e["entry_type"] != "salary":
            continue

        postings = e.get("account_postings", {})
        is_director = "Director's Salary" in postings

        # Extract individual person amounts from account postings
        # Person columns are those that aren't expense heads
        SALARY_HEADS = {"salary & bonus", "director's salary", "tds payable",
                        "employees professonal tax"}
        for col_name, amount in postings.items():
            if col_name.lower().strip() in SALARY_HEADS:
                continue
            if amount == 0:
                continue
            # This is a person column with their salary amount
            entries.append({
                "tally_source": "journal_salary",
                "date": e["date"],
                "party_name": col_name,  # Full name e.g. "Adi Debnath"
                "amount": amount,
                "is_director": is_director,
                "salary_type": "Director's Salary" if is_director else "Salary & Bonus",
                "voucher_no": e["voucher_no"],
                "raw": e,
                "_matched": False,
            })
    return entries


# ---------------------------------------------------------------------------
# Pass 1: Exact Match
# ---------------------------------------------------------------------------

def pass1_exact_match(form26_entries: list[dict], tally_entries: list[dict],
                      name_optional: bool = False) -> list[dict]:
    """
    Exact match: same party name (normalized) + same amount + same date.

    If name_optional=True (for Section 192 salary), match on amount + date only
    since Form 24 uses abbreviated names (AD, HCD) vs Tally full names.
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

            # Name must match (unless salary section with abbreviated names)
            if not name_optional and f26_name != tally_name:
                continue

            # Amount must be exact
            if f26_amount != tally["amount"]:
                continue

            # Date within tolerance (3 days for named matches, 31 days for salary)
            date_tolerance = 31 if name_optional else 3
            if f26_date and tally_date and abs((f26_date - tally_date).days) > date_tolerance:
                continue

            # Match found
            confidence = 1.0 if not name_optional else 0.95
            matches.append({
                "pass": 1,
                "pass_name": "exact_match" if not name_optional else "exact_amount_date",
                "confidence": confidence,
                "form26_entry": _clean_entry(f26),
                "tally_entries": [_clean_entry(tally)],
                "match_details": {
                    "name_match": f"'{f26['vendor_name']}' → '{tally['party_name']}'" if name_optional
                                  else f"'{f26['vendor_name']}' = '{tally['party_name']}'",
                    "amount_match": f"{f26_amount} = {tally['amount']}",
                    "date_diff_days": abs((f26_date - tally_date).days) if f26_date and tally_date else None,
                    "match_mode": "amount+date (salary abbreviated names)" if name_optional else "name+amount+date",
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

def _normalize_name_keep_division(name: str) -> str:
    """Normalize vendor name but keep division/branch identifiers distinct.
    Used for 194Q where 'Raymond Limited (Shirting)' != 'Raymond Limited (Chhindwara)'."""
    if not name:
        return ""
    n = name.lower().strip()
    # Extract division/branch from parenthetical before removing suffixes
    division = ""
    div_match = re.search(r"\(([^)]+)\)", n)
    if div_match:
        div_text = div_match.group(1).strip()
        # Only keep it if it's a meaningful division (not just a number)
        if not div_text.isdigit() and "loan" not in div_text:
            # Take first word of division as identifier
            division = div_text.split()[0] if div_text else ""
    # Standard normalization
    for suffix in ["pvt. ltd.", "pvt ltd", "private limited", "limited", "ltd.", "ltd",
                   "llp", "lp", "inc.", "inc", "co.", "company"]:
        n = n.replace(suffix, "")
    n = re.sub(r"\([^)]*\)", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    if division:
        n = f"{n} [{division}]"
    return n


def _pre_aggregate_194q(tally_entries: list[dict], f26_entries: list[dict]) -> list[dict]:
    """
    Pre-aggregate 194Q purchase register entries into monthly synthetic entries.

    194Q pattern: Form 26 amount = monthly sum of gross_totals / (1 + GST rate)
    i.e., TDS is on purchase value excluding GST.

    We group by vendor name (keeping divisions distinct) + month, compute the
    GST-exclusive base, and create synthetic entries the matching passes can use.
    """
    # Group by (vendor_with_division, month)
    groups = defaultdict(lambda: {
        "entries": [], "gross_sum": 0, "party_names": set(),
    })
    for e in tally_entries:
        vn = _normalize_name_keep_division(e["party_name"])
        month = get_month_key(e["date"])
        key = (vn, month)
        groups[key]["entries"].append(e)
        groups[key]["gross_sum"] += e.get("amount", 0) or 0
        groups[key]["party_names"].add(e["party_name"])

    # Also build vendor groups ignoring division (for F26 entries that aggregate divisions)
    vendor_month_nodiv = defaultdict(lambda: {
        "entries": [], "gross_sum": 0, "party_names": set(),
    })
    for e in tally_entries:
        vn = normalize_name(e["party_name"])
        month = get_month_key(e["date"])
        key = (vn, month)
        vendor_month_nodiv[key]["entries"].append(e)
        vendor_month_nodiv[key]["gross_sum"] += e.get("amount", 0) or 0
        vendor_month_nodiv[key]["party_names"].add(e["party_name"])

    # Build synthetic monthly entries with GST-adjusted base amounts
    synthetic = []

    # Per-division monthly aggregates
    for (vn, month), g in groups.items():
        gross = g["gross_sum"]
        for gst_rate in [0.05, 0.12, 0.18, 0.28]:
            base = round(gross / (1 + gst_rate), 0)
            synthetic.append({
                "tally_source": "purchase_register_agg",
                "date": f"{month}-28" if month else "",
                "party_name": sorted(g["party_names"])[0],
                "amount": base,
                "gross_amount": gross,
                "gst_rate_applied": gst_rate,
                "num_invoices": len(g["entries"]),
                "month": month,
                "voucher_no": f"AGG-{month}-{len(g['entries'])}inv",
                "_matched": False,
            })

    # Cross-division monthly aggregates (all divisions of same vendor combined)
    for (vn, month), g in vendor_month_nodiv.items():
        gross = g["gross_sum"]
        for gst_rate in [0.05, 0.12, 0.18, 0.28]:
            base = round(gross / (1 + gst_rate), 0)
            synthetic.append({
                "tally_source": "purchase_register_agg_combined",
                "date": f"{month}-28" if month else "",
                "party_name": sorted(g["party_names"])[0],
                "amount": base,
                "gross_amount": gross,
                "gst_rate_applied": gst_rate,
                "num_invoices": len(g["entries"]),
                "month": month,
                "voucher_no": f"AGG-COMBINED-{month}-{len(g['entries'])}inv",
                "_matched": False,
            })

    # Keep individual entries for exact matching
    for e in tally_entries:
        e["_matched"] = False
        synthetic.append(e)

    return synthetic


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
    # Fields starting with _ to keep in output
    KEEP_INTERNAL = {"_below_threshold"}
    cleaned = {}
    for k, v in entry.items():
        if k.startswith("_") and k not in KEEP_INTERNAL:
            continue
        if k == "raw":
            continue  # Skip the full raw entry to keep output manageable
        cleaned[k] = v
    return cleaned


# ---------------------------------------------------------------------------
# Main — Run Matcher Agent
# ---------------------------------------------------------------------------

def run(parsed_dir: str, output_dir: str, sections: set | None = None,
        rules_dir: str | None = None):
    """Run the matching engine across all TDS sections."""

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

    # Build Tally entry pools per section
    tally_pools = {}
    if "192" in sections:
        tally_pools["192"] = build_tally_192_entries(tally_data)
        print(f"[Matcher] {len(tally_pools['192'])} Tally 192 entries (salary payments)")
    if "194A" in sections:
        tally_pools["194A"] = build_tally_194a_entries(tally_data)
        print(f"[Matcher] {len(tally_pools['194A'])} Tally 194A entries (interest payments)")
    if "194C" in sections:
        tally_pools["194C"] = build_tally_194c_entries(tally_data)
        print(f"[Matcher] {len(tally_pools['194C'])} Tally 194C entries (freight + GST expenses)")
    if "194H" in sections:
        tally_pools["194H"] = build_tally_194h_entries(tally_data)
        print(f"[Matcher] {len(tally_pools['194H'])} Tally 194H entries (brokerage/commission)")
    if "194J(b)" in sections:
        tally_pools["194J(b)"] = build_tally_194j_entries(tally_data)
        print(f"[Matcher] {len(tally_pools['194J(b)'])} Tally 194J(b) entries (professional/consultancy)")
    if "194Q" in sections:
        tally_pools["194Q"] = build_tally_194q_entries(tally_data)
        print(f"[Matcher] {len(tally_pools['194Q'])} Tally 194Q entries (purchase of goods)")

    # ---- Pass 0: Apply Learned Rules ----
    rules_applied = []
    learned_rules = []
    ignored_vendors = set()
    exempt_vendors = set()
    below_threshold_vendors = set()

    if rules_dir is None:
        rules_dir = str(parsed_dir.parent / "data" / "rules")

    if HAS_LEARNING_AGENT:
        learned_rules = learning_agent.get_active_rules(rules_dir)
        if learned_rules:
            print(f"\n--- Pass 0: Learned Rules ({len(learned_rules)} active) ---")

            # Apply vendor aliases to all tally pools
            alias_rules = [r for r in learned_rules if r["rule_type"] == "vendor_alias"]
            if alias_rules:
                total_aliases = 0
                for sec_key, pool in tally_pools.items():
                    pool, alias_ids = learning_agent.apply_vendor_aliases(learned_rules, pool)
                    tally_pools[sec_key] = pool
                    total_aliases += len(alias_ids)
                    rules_applied.extend(alias_ids)
                if total_aliases:
                    print(f"  Vendor aliases applied: {total_aliases}")

            # Get ignore/exempt/below-threshold sets
            ignored_vendors = learning_agent.get_ignored_vendors(learned_rules)
            exempt_vendors = learning_agent.get_exempt_vendors(learned_rules)
            below_threshold_vendors = learning_agent.get_below_threshold_vendors(
                learned_rules, "194C")

            # Filter out ignored vendors from all pools
            if ignored_vendors:
                for sec_key in tally_pools:
                    before = len(tally_pools[sec_key])
                    tally_pools[sec_key] = [
                        e for e in tally_pools[sec_key]
                        if e.get("party_name", "").lower().strip() not in ignored_vendors
                    ]
                    removed = before - len(tally_pools[sec_key])
                    if removed:
                        print(f"  Ignored vendors removed from {sec_key}: {removed} entries")

            # Mark below-threshold vendors (194C specific from learned rules)
            if below_threshold_vendors and "194C" in tally_pools:
                bt_count = 0
                for e in tally_pools["194C"]:
                    if e.get("party_name", "").lower().strip() in below_threshold_vendors:
                        e["_below_threshold"] = True
                        bt_count += 1
                if bt_count:
                    print(f"  Below-threshold entries marked: {bt_count}")

            for rule_id in rules_applied:
                learning_agent.increment_applied(rules_dir, rule_id)
        else:
            print("\n--- Pass 0: Learned Rules (no rules found) ---")
    else:
        print("\n--- Pass 0: Learned Rules (learning agent not available) ---")

    # Split Form 26 by section
    f26_by_section = {}
    for sec in sections:
        f26_by_section[sec] = [e for e in form26_entries if e["section"] == sec]

    all_matches = []
    all_exemptions = []
    pass_counts = {"pass1_exact": 0, "pass2_gst_adjusted": 0, "pass3_exempt": 0,
                   "pass4_fuzzy": 0, "pass5_aggregated": 0}

    # Run all 5 passes across all sections
    section_order = ["192", "194A", "194C", "194H", "194J(b)", "194Q"]
    active_sections = [s for s in section_order if s in sections and s in tally_pools]

    # ---- Pass 0b: 194Q pre-processing ----
    # 194Q entries are monthly aggregates of hundreds of purchase invoices.
    # Form 26 amount = sum(gross_total) / (1 + GST_rate) for the month.
    # Pre-aggregate into monthly synthetic entries for matching.
    if "194Q" in tally_pools:
        tally_pools["194Q"] = _pre_aggregate_194q(
            tally_pools["194Q"], f26_by_section.get("194Q", []))

    # ---- Pass 1: Exact Match ----
    print("\n--- Pass 1: Exact Match ---")
    m1_all = []
    for sec in active_sections:
        # For Section 192 (salary), use amount+date matching since Form 24
        # has abbreviated names (AD, HCD) that don't match Tally full names
        name_opt = (sec == "192")
        m1 = pass1_exact_match(f26_by_section.get(sec, []), tally_pools[sec],
                               name_optional=name_opt)
        m1_all.extend(m1)
        if m1:
            print(f"  {sec}: {len(m1)} matches")
    all_matches.extend(m1_all)
    pass_counts["pass1_exact"] = len(m1_all)

    # ---- Pass 2: GST-Adjusted ----
    print("\n--- Pass 2: GST-Adjusted Match ---")
    m2_all = []
    for sec in active_sections:
        m2 = pass2_gst_adjusted(f26_by_section.get(sec, []), tally_pools[sec])
        m2_all.extend(m2)
        if m2:
            print(f"  {sec}: {len(m2)} matches")
    all_matches.extend(m2_all)
    pass_counts["pass2_gst_adjusted"] = len(m2_all)

    # ---- Pass 3: Exempt Filter ----
    print("\n--- Pass 3: Exempt Filter ---")
    for sec in active_sections:
        ex = pass3_exempt_filter(f26_by_section.get(sec, []), tally_pools[sec])
        all_exemptions.extend(ex)
        if ex:
            print(f"  {sec}: {len(ex)} entries marked exempt")
    pass_counts["pass3_exempt"] = len(all_exemptions)

    # ---- Pass 4: Fuzzy Match ----
    print("\n--- Pass 4: Fuzzy Match ---")
    m4_all = []
    for sec in active_sections:
        m4 = pass4_fuzzy_match(f26_by_section.get(sec, []), tally_pools[sec])
        m4_all.extend(m4)
        if m4:
            print(f"  {sec}: {len(m4)} matches")
    all_matches.extend(m4_all)
    pass_counts["pass4_fuzzy"] = len(m4_all)

    # ---- Pass 5: Aggregated Match ----
    print("\n--- Pass 5: Aggregated Match ---")
    m5_all = []
    for sec in active_sections:
        m5 = pass5_aggregated_match(f26_by_section.get(sec, []), tally_pools[sec])
        m5_all.extend(m5)
        if m5:
            print(f"  {sec}: {len(m5)} matches")
    all_matches.extend(m5_all)
    pass_counts["pass5_aggregated"] = len(m5_all)

    # ---- Collect unmatched ----
    unmatched_form26 = [_clean_entry(e) for e in form26_entries if not e.get("_matched")]

    unmatched_tally = {}
    for sec in active_sections:
        unmatched = [_clean_entry(e) for e in tally_pools[sec] if not e.get("_matched")]
        if unmatched:
            unmatched_tally[sec] = unmatched

    # ---- Collect below-threshold entries for reporting ----
    below_threshold_entries = []
    for sec in active_sections:
        below_threshold_entries.extend(
            _clean_entry(e) for e in tally_pools[sec] if e.get("_below_threshold")
        )

    # ---- Build output ----
    results = {
        "run_timestamp": datetime.now().isoformat(),
        "sections_processed": sorted(active_sections),
        "learned_rules": {
            "rules_loaded": len(learned_rules),
            "rules_applied": len(rules_applied),
            "ignored_vendors": len(ignored_vendors),
            "exempt_vendors": len(exempt_vendors),
            "below_threshold_vendors": len(below_threshold_vendors),
            "below_threshold_entries": len(below_threshold_entries),
        },
        "summary": {
            "form26_total": len(form26_entries),
            "form26_matched": sum(1 for e in form26_entries if e.get("_matched")),
            "form26_unmatched": len(unmatched_form26),
            "below_threshold_resolved": len(below_threshold_entries),
            "total_resolved": sum(1 for e in form26_entries if e.get("_matched")) + len(below_threshold_entries),
            "matches_by_pass": {
                "pass0_learned_rules": len(rules_applied),
                **pass_counts,
            },
            "total_matches": len(all_matches),
        },
        "matches": all_matches,
        "exemptions": all_exemptions,
        "unmatched_form26": unmatched_form26,
        # Keep backward-compatible keys + new generic key
        "unmatched_tally_194a": unmatched_tally.get("194A", []),
        "unmatched_tally_194c": unmatched_tally.get("194C", []),
        "unmatched_tally": unmatched_tally,
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

    # Section-wise breakdown
    matched_by_section = defaultdict(int)
    for m in all_matches:
        sec = m["form26_entry"].get("section", "?")
        matched_by_section[sec] += 1
    print(f"\nMatches by section:")
    for sec in section_order:
        total_in_sec = len(f26_by_section.get(sec, []))
        matched_in_sec = matched_by_section.get(sec, 0)
        if total_in_sec > 0:
            print(f"  {sec}: {matched_in_sec}/{total_in_sec}")

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
    rules = base / "data" / "rules"

    run(str(parsed), str(output), rules_dir=str(rules))
