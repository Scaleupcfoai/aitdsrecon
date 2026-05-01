"""TDS threshold limits + Rule 30 deposit-due-date helpers.

Sourced from CA's TDS Master Data, FY 2025-26.

Each section entry can carry:
  - aggregate_annual: total per FY in rupees
  - single_txn:       single payment ceiling in rupees
  - monthly:          monthly threshold (e.g. 194-I uses ₹50,000/month)
  - description:      human readable rule
"""

from __future__ import annotations

from datetime import date

# Use None to mean "no threshold of this type".
TDS_THRESHOLDS: dict[str, dict] = {
    "192":      {"aggregate_annual": None, "single_txn": None,
                 "description": "Salary — basic exemption ₹12.75L (slab-based, out of scope)"},
    "193":      {"aggregate_annual": 10000, "single_txn": None,
                 "description": "Interest on securities — ₹10,000 per FY"},
    "194":      {"aggregate_annual": 10000, "single_txn": None,
                 "description": "Dividend — ₹10,000 per FY"},
    "194A":     {"aggregate_annual": 10000, "single_txn": None,
                 "description": "Interest other than securities — ₹10,000 per FY (₹50k bank/others, ₹1L bank/senior)"},
    "194B":     {"aggregate_annual": 10000, "single_txn": None,
                 "description": "Lottery / crossword puzzle — ₹10,000"},
    "194BA":    {"aggregate_annual": None, "single_txn": None,
                 "description": "Online games — no threshold (TDS on net winnings, ≤₹100 exempt)"},
    "194BB":    {"aggregate_annual": 10000, "single_txn": None,
                 "description": "Horse race winnings — ₹10,000"},
    "194C":     {"aggregate_annual": 100000, "single_txn": 30000,
                 "description": "Contractor — single ≤ ₹30k AND aggregate ≤ ₹1L exempt"},
    "194D":     {"aggregate_annual": 20000, "single_txn": None,
                 "description": "Insurance commission — ₹20,000 per FY"},
    "194DA":    {"aggregate_annual": 100000, "single_txn": None,
                 "description": "Life insurance maturity — ₹1,00,000 (income portion only)"},
    "194E":     {"aggregate_annual": None, "single_txn": None,
                 "description": "Non-resident sportsman / entertainer — no threshold"},
    "194EE":    {"aggregate_annual": 2500, "single_txn": None,
                 "description": "NSS withdrawals — ₹2,500"},
    "194G":     {"aggregate_annual": 20000, "single_txn": None,
                 "description": "Lottery commission — ₹20,000"},
    "194H":     {"aggregate_annual": 20000, "single_txn": None,
                 "description": "Commission / brokerage — ₹20,000 per FY"},
    "194-IA":   {"aggregate_annual": 5000000, "single_txn": None,
                 "description": "Immovable property — ₹50L sale consideration / SDV"},
    "194-IB":   {"monthly": 50000, "aggregate_annual": None, "single_txn": None,
                 "description": "Rent by Ind/HUF (not under audit) — ₹50,000 per month"},
    "194-IC":   {"aggregate_annual": None, "single_txn": None,
                 "description": "Joint Development Agreement — no threshold"},
    "194I(a)":  {"monthly": 50000, "aggregate_annual": None, "single_txn": None,
                 "description": "Rent — plant/machinery/equipment — ₹50,000/month"},
    "194I(b)":  {"monthly": 50000, "aggregate_annual": None, "single_txn": None,
                 "description": "Rent — land/building/furniture — ₹50,000/month (hotel rents excluded)"},
    "194J(a)":  {"aggregate_annual": 50000, "single_txn": None,
                 "description": "Technical fees / call centre — ₹50,000 per category"},
    "194J(b)":  {"aggregate_annual": 50000, "single_txn": None,
                 "description": "Professional / royalty / director fees — ₹50,000 per category"},
    "194K":     {"aggregate_annual": 10000, "single_txn": None,
                 "description": "MF dividend — ₹10,000"},
    "194LA":    {"aggregate_annual": 500000, "single_txn": None,
                 "description": "Compensation on land acquisition — ₹5,00,000 (agri land excluded)"},
    "194M":     {"aggregate_annual": 5000000, "single_txn": None,
                 "description": "Contractor / professional payment by Ind/HUF (not under audit) — ₹50,00,000 p.a."},
    "194N":     {"aggregate_annual": 10000000, "single_txn": None,
                 "description": "Cash withdrawal — ₹1 Cr (filer); ₹20L (non-filer)"},
    "194O":     {"aggregate_annual": None, "single_txn": None,
                 "description": "E-commerce — no threshold (₹5L exemption for ind/HUF participants with PAN/Aadhaar)"},
    "194Q":     {"aggregate_annual": 5000000, "single_txn": None,
                 "description": "Purchase of goods — ₹50L per seller; buyer's previous-year turnover > ₹10 Cr"},
    "194R":     {"aggregate_annual": 20000, "single_txn": None,
                 "description": "Benefit / perquisite — ₹20,000 p.a."},
    "194S":     {"aggregate_annual": 50000, "single_txn": None,
                 "description": "VDA — ₹50,000 (ind/HUF not under audit) / ₹10,000 (others)"},
    "194T":     {"aggregate_annual": 20000, "single_txn": None,
                 "description": "Partner remuneration / interest from firm — ₹20,000 p.a."},
    "195":      {"aggregate_annual": None, "single_txn": None,
                 "description": "Non-resident other income — no threshold (DTAA may apply)"},
}


def get_deposit_due_date(deduction_date: date) -> date:
    """Rule 30 deposit due date for non-government deductors.

    - March deductions: due 30 April
    - Any other month: due 7th of the following month

    (Sections 194-IA / 194-IB / 194M / 194S have separate 30-day rules — not modelled here yet.)
    """
    month = deduction_date.month
    year = deduction_date.year
    if month == 3:
        return date(year, 4, 30)
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    return date(next_year, next_month, 7)


def get_quarter(deduction_date: date) -> str:
    """Indian FY quarter: Q1 Apr-Jun, Q2 Jul-Sep, Q3 Oct-Dec, Q4 Jan-Mar."""
    m = deduction_date.month
    if 4 <= m <= 6:
        return "Q1"
    if 7 <= m <= 9:
        return "Q2"
    if 10 <= m <= 12:
        return "Q3"
    return "Q4"


def get_fy_label(deduction_date: date) -> str:
    """FY label like 'FY 2025-26' based on Apr-Mar year."""
    y = deduction_date.year
    if deduction_date.month >= 4:
        return f"FY {y}-{str(y + 1)[-2:]}"
    return f"FY {y - 1}-{str(y)[-2:]}"
