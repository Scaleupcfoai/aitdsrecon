"""
TDS Checker Agent — validates compliance on matched entries.

5 checks:
1. Section Validation — is the TDS section correct for the expense type?
2. Rate Validation — is the TDS rate correct for entity type + section?
3. Base Amount Validation — is TDS on pre-GST base (not GST-inclusive)?
4. Threshold Validation — is the amount above the applicable threshold?
5. Missing TDS Detection — Tally expenses where TDS should have been deducted

Rules engine preserved from MVP (tds-recon/agents/tds_checker_agent.py).
"""

import re
from collections import defaultdict
from datetime import datetime

from app.agents.base import AgentBase
from app.knowledge import (
    get_section_rate as kb_get_rate,
    get_threshold as kb_get_threshold,
    get_expense_keywords as kb_get_keywords,
    get_entity_type as kb_get_entity_type,
    get_ambiguous_expenses as kb_get_ambiguous,
)


# Override the hardcoded expected_rate function to use knowledge base
def expected_rate_from_kb(section: str, pan: str) -> float | None:
    """Get expected TDS rate from knowledge base (primary) or hardcoded table (fallback)."""
    entity = kb_get_entity_type(pan)
    if entity == "firm":
        entity = "individual_huf"
    rate = kb_get_rate(section, entity)
    if rate is not None:
        return rate
    # Fallback to hardcoded
    return expected_rate(section, pan)


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

    # Process Journal Register entries
    for entry in tally_data.get("journal_register", {}).get("entries", []):
        key = _tally_entry_key("journal", entry)
        if key in matched_tally_keys:
            continue

        entry_type = entry.get("entry_type", "")
        if entry_type in ("tds_deduction", "salary", "discount", "other"):
            continue  # Not TDS-applicable expenses

        vendor = entry.get("particulars", "")
        vendor_norm = normalize_name(vendor)
        amount = entry.get("gross_total", 0) or 0

        # Determine expense heads
        postings = entry.get("account_postings", {})
        heads = [h for h in postings if h not in ("Gross Total", "Value")]

        for head in heads:
            sections = classify_expense_head(head)
            ve = vendor_expenses[(vendor_norm, tuple(sorted(sections)))]
            ve["total_amount"] += amount
            ve["entries"].append(entry)
            ve["expense_heads"].add(head)
            ve["vendor_name"] = vendor
            ve["expected_sections"].update(sections)

    # Process GST Exp Register entries
    for entry in tally_data.get("purchase_gst_exp_register", {}).get("entries", []):
        key = _tally_entry_key("gst_exp", entry)
        if key in matched_tally_keys:
            continue

        vendor = entry.get("particulars", "")
        vendor_norm = normalize_name(vendor)
        base_amount = entry.get("base_amount", 0) or 0

        heads = list((entry.get("expense_heads") or {}).keys())
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

            findings.append({
                "check": "missing_tds",
                "severity": "error" if total >= (threshold or 0) else "warning",
                "vendor": ve["vendor_name"],
                "vendor_normalized": vendor_norm,
                "expected_section": sec,
                "aggregate_amount": round(total, 2),
                "threshold": threshold,
                "num_tally_entries": len(ve["entries"]),
                "expense_heads": sorted(ve["expense_heads"]),
                "message": (f"No Form 26 entry found for {ve['vendor_name']} "
                            f"under {sec}. Tally shows ₹{total:,.0f} in "
                            f"{', '.join(sorted(ve['expense_heads']))}. "
                            f"TDS may be missing."),
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


# ═══════════════════════════════════════════════════════════
# TDS Checker Agent — DB adapter
# ═══════════════════════════════════════════════════════════

class TdsCheckerAgent(AgentBase):
    agent_name = "TDS Checker"

    def run(self, matches: list[dict], form26_entries: list[dict],
            tally_entries: list[dict]) -> dict:
        """Run all 5 compliance checks.

        Args:
            matches: list of match dicts from Matcher (with form26_entry + tally_entries)
            form26_entries: all Form 26 entries (for missing TDS detection)
            tally_entries: all Tally entries (for missing TDS detection)

        Returns findings summary.
        """
        self.events.agent_start(self.agent_name, "Starting TDS Checker...")

        all_findings = []

        # Check 1: Section Validation
        section_findings = [f for m in matches if (f := check_section(m))]
        all_findings.extend(section_findings)
        if section_findings:
            self.events.detail(self.agent_name, f"Check 1: {len(section_findings)} section issues")

        # Check 1b: LLM classification for ambiguous sections
        ambiguous = [f for f in section_findings if f.get("status") == "review"]
        if ambiguous and self.llm and self.llm.available:
            self.events.detail(self.agent_name, f"  Sending {len(ambiguous)} ambiguous expenses to LLM...")
            self._llm_classify_sections(ambiguous)

        # Check 2: Rate Validation
        rate_findings = [f for m in matches if (f := check_rate(m))]
        all_findings.extend(rate_findings)
        if rate_findings:
            self.events.detail(self.agent_name, f"Check 2: {len(rate_findings)} rate issues")

        # Check 3: Base Amount Validation
        base_findings = [f for m in matches if (f := check_base_amount(m))]
        all_findings.extend(base_findings)
        if base_findings:
            self.events.detail(self.agent_name, f"Check 3: {len(base_findings)} base amount issues")

        # Check 4: Threshold Validation
        threshold_findings = check_thresholds(matches)
        all_findings.extend(threshold_findings)
        if threshold_findings:
            self.events.detail(self.agent_name, f"Check 4: {len(threshold_findings)} threshold issues")

        # Check 5: Missing TDS Detection
        matched_keys = build_matched_tally_keys(matches)
        # Build tally_data dict format expected by detect_missing_tds
        tally_data = self._build_tally_data_dict(tally_entries)
        missing_findings = detect_missing_tds(tally_data, form26_entries, matched_keys)
        all_findings.extend(missing_findings)
        if missing_findings:
            self.events.detail(self.agent_name, f"Check 5: {len(missing_findings)} missing TDS cases")

        # Count by severity
        errors = [f for f in all_findings if f.get("severity") == "error"]
        warnings = [f for f in all_findings if f.get("severity") == "warning"]
        exposure = sum(f.get("aggregate_amount", 0) for f in errors)

        # LLM: Write remediation advice for error findings
        if errors and self.llm and self.llm.available:
            self.events.detail(self.agent_name, f"Writing remediation advice for {len(errors)} errors...")
            self._llm_write_remediations(errors)

        # Write findings to DB as discrepancy_action rows
        self._write_findings_to_db(all_findings)

        self.events.success(
            self.agent_name,
            f"Complete: {len(errors)} errors, {len(warnings)} warnings, Rs {exposure:,.0f} exposure"
        )
        self.events.agent_done(self.agent_name, "Compliance checks complete")

        return {
            "findings": all_findings,
            "summary": {
                "total": len(all_findings),
                "errors": len(errors),
                "warnings": len(warnings),
                "exposure": exposure,
            },
        }

    def _build_tally_data_dict(self, tally_entries: list[dict]) -> dict:
        """Convert flat tally entries back to the nested format detect_missing_tds expects."""
        journal_entries = []
        gst_entries = []
        purchase_entries = []

        for e in tally_entries:
            source = ""
            raw = e.get("raw_data", {})
            if isinstance(raw, str):
                import json
                raw = json.loads(raw)
            if isinstance(raw, dict):
                source = raw.get("source", "")

            if "journal" in source:
                journal_entries.append({
                    "entry_type": e.get("expense_type", "other"),
                    "particulars": e.get("party_name", ""),
                    "voucher_no": e.get("voucher_no", ""),
                    "date": e.get("date", ""),
                    "gross_total": e.get("amount", 0),
                    "account_postings": raw.get("account_postings", {}),
                })
            elif "gst" in source:
                gst_entries.append({
                    "particulars": e.get("party_name", ""),
                    "voucher_no": e.get("voucher_no", ""),
                    "date": e.get("date", ""),
                    "base_amount": e.get("amount", 0),
                    "expense_heads": raw.get("expense_heads", {}),
                })
            elif "purchase" in source:
                purchase_entries.append({
                    "particulars": e.get("party_name", ""),
                    "voucher_no": e.get("voucher_no", ""),
                    "date": e.get("date", ""),
                    "gross_total": e.get("amount", 0),
                })

        return {
            "journal_register": {"entries": journal_entries},
            "purchase_gst_exp_register": {"entries": gst_entries},
            "purchase_register": {"entries": purchase_entries},
        }

    def _llm_classify_sections(self, ambiguous_findings: list[dict]):
        """Ask LLM to classify ambiguous expense heads (e.g., advertisement → 194C or 194J?)."""
        from app.services.llm_prompts import CHECKER_SECTION_SYSTEM, CHECKER_SECTION_PROMPT

        for finding in ambiguous_findings:
            vendor = finding.get("vendor", "")
            expense_heads = finding.get("expense_heads", [])
            current_section = finding.get("form26_section", "")
            amount = finding.get("form26_amount", finding.get("aggregate_amount", 0))

            prompt = CHECKER_SECTION_PROMPT.format(
                vendor_name=vendor,
                expense_head=", ".join(expense_heads) if isinstance(expense_heads, list) else str(expense_heads),
                amount=f"{amount:,.0f}" if isinstance(amount, (int, float)) else str(amount),
                current_section=current_section,
            )

            result = self.llm.complete_json(prompt, system=CHECKER_SECTION_SYSTEM, agent_name=self.agent_name)

            if result:
                correct_section = result.get("correct_section", "")
                confidence = result.get("confidence", 0)
                reasoning = result.get("reasoning", "")
                is_correct = result.get("is_current_correct", True)

                # Update the finding with LLM classification
                finding["llm_classification"] = {
                    "correct_section": correct_section,
                    "confidence": confidence,
                    "reasoning": reasoning,
                }

                if is_correct:
                    # LLM confirms current section is correct — downgrade to info
                    finding["severity"] = "info"
                    finding["message"] = f"Section {current_section} confirmed by AI: {reasoning}"
                    self.events.emit(self.agent_name,
                        f"LLM confirms: {vendor} → {current_section} is correct ({reasoning[:80]})",
                        "llm_insight")
                elif confidence >= 0.7:
                    # LLM says wrong section — upgrade to error
                    finding["severity"] = "error"
                    finding["message"] = (f"Section {current_section} likely incorrect for {vendor}. "
                                          f"AI suggests {correct_section}: {reasoning}")
                    self.events.emit(self.agent_name,
                        f"LLM: {vendor} should be {correct_section}, not {current_section}",
                        "llm_insight")
                else:
                    # LLM unsure — keep as warning, flag for human
                    finding["message"] = f"Ambiguous section for {vendor}. AI unsure: {reasoning}"
                    self.events.emit(self.agent_name,
                        f"LLM unsure about {vendor} section. Flagged for review.",
                        "human_needed")

    def _llm_write_remediations(self, error_findings: list[dict]):
        """Ask LLM to write CA-level remediation advice for each error finding."""
        from app.services.llm_prompts import CHECKER_REMEDIATION_SYSTEM, CHECKER_REMEDIATION_PROMPT

        # Build findings list for prompt
        findings_text = []
        for i, f in enumerate(error_findings):
            findings_text.append(
                f"[{i}] {f.get('severity', 'error').upper()} — {f.get('vendor', 'Unknown')}\n"
                f"    Section: {f.get('form26_section', f.get('expected_section', ''))}\n"
                f"    Amount: Rs {f.get('aggregate_amount', f.get('form26_amount', 0)):,.0f}\n"
                f"    Finding: {f.get('message', '')}"
            )

        prompt = CHECKER_REMEDIATION_PROMPT.format(
            findings_list="\n\n".join(findings_text)
        )

        result = self.llm.complete_json(prompt, system=CHECKER_REMEDIATION_SYSTEM, agent_name=self.agent_name)

        if result and "remediations" in result:
            for remediation in result["remediations"]:
                idx = remediation.get("finding_index", 0)
                if idx < len(error_findings):
                    error_findings[idx]["remediation"] = {
                        "what_is_wrong": remediation.get("what_is_wrong", ""),
                        "why_it_matters": remediation.get("why_it_matters", ""),
                        "action_steps": remediation.get("action_steps", []),
                        "deadline": remediation.get("deadline", ""),
                        "penalty_risk": remediation.get("penalty_risk", ""),
                        "priority": remediation.get("priority", "medium"),
                    }

            self.events.emit(self.agent_name,
                f"LLM wrote remediation advice for {len(result['remediations'])} findings",
                "llm_insight")

    def _write_findings_to_db(self, findings: list[dict]):
        """Write all findings to discrepancy_action table."""
        # We need match_result_ids to link findings. For now, create without link
        # TODO: link to specific match_result rows when available
        for f in findings:
            try:
                self.db.discrepancies.create(
                    match_result_id=f.get("_match_result_id", "00000000-0000-0000-0000-000000000000"),
                    stage=f.get("check", ""),
                    llm_reasoning=f.get("llm_classification", {}).get("reasoning", "")
                                  if f.get("llm_classification") else f.get("message", ""),
                    proposed_action=f.get("remediation") if f.get("remediation") else {"message": f.get("message", "")},
                )
            except Exception:
                pass  # Skip if FK constraint fails (no match_result_id)
