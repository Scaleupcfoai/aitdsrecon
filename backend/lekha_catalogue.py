"""Lekha AI — 15 reconciliation modules catalogue.

Source of truth: aibookclose branch claude/all-15-recons-homepage,
src/data/reconTiles.js (the `reconTiles` array). Mirrored here so the
Excel marketing sheet stays in sync without importing across repos.

Update this list when the product catalogue changes upstream.
"""

from __future__ import annotations

LEKHA_RECONS = [
    {"id": "platform-sales-cash",    "domain": "PLATFORM",     "flow": "Revenue",       "title": "Sales-to-Cash — Platform Settlements",        "compliance": "Internal Control"},
    {"id": "gst-output",             "domain": "GST",          "flow": "Revenue",       "title": "GST Output Recon — GSTR-1 vs Sales Register", "compliance": "Regulatory"},
    {"id": "bank-payments",          "domain": "BANK",         "flow": "Expense",       "title": "Bank Payments Recon — Outward Payments vs GL", "compliance": "Internal Control"},
    {"id": "credit-card-amex",       "domain": "CREDIT_CARD",  "flow": "Expense",       "title": "Amex Corporate Card — Statement vs Books",    "compliance": "Internal Control"},
    {"id": "prepaid-expenses",       "domain": "EXPENSE",      "flow": "Expense",       "title": "Prepaid Expenses — Amortisation Schedule vs GL", "compliance": "Internal Control"},
    {"id": "platform-merchant-fees", "domain": "PLATFORM",     "flow": "Expense",       "title": "Platform & Merchant Fee Recon",               "compliance": "Internal Control"},
    {"id": "tds-26q",                "domain": "TDS",          "flow": "Expense",       "title": "TDS — 26Q vs Books (Vendor Payments)",        "compliance": "Regulatory"},
    {"id": "tds-24q",                "domain": "TDS",          "flow": "Expense",       "title": "TDS — 24Q vs Books (Salary)",                 "compliance": "Regulatory"},
    {"id": "gst-itc",                "domain": "GST",          "flow": "Expense",       "title": "GST ITC Recon — GSTR-2B vs Purchase Register", "compliance": "Regulatory"},
    {"id": "gst-liability",          "domain": "GST",          "flow": "Revenue",       "title": "GST Liability Recon — GSTR-1 vs GSTR-3B",     "compliance": "Regulatory"},
    {"id": "bank-hdfc",              "domain": "BANK",         "flow": "Balance Sheet", "title": "HDFC Current A/c — Bank Recon",               "compliance": "Internal Control"},
    {"id": "bank-icici",             "domain": "BANK",         "flow": "Balance Sheet", "title": "ICICI Savings A/c — Bank Recon",              "compliance": "Internal Control"},
    {"id": "intercompany-prism",     "domain": "INTERCOMPANY", "flow": "Balance Sheet", "title": "Intercompany Recon — Entity vs Entity",       "compliance": "Internal Control"},
    {"id": "accrued-liabilities",    "domain": "ACCRUAL",      "flow": "Balance Sheet", "title": "Accrued Liabilities — Schedule vs GL",        "compliance": "Internal Control"},
    {"id": "payroll-recon",          "domain": "PAYROLL",      "flow": "Expense",       "title": "Payroll Recon — Salary Register vs GL",       "compliance": "Internal Control"},
]
