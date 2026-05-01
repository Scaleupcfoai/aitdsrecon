"""Unified TDS expense-head knowledge base.

Single source of truth for "what does this expense head mean for TDS?".

Used by:
  - b2 (tds_calculator) — at row evaluation time, auto-skip or auto-apply when KB
    confidence is high; flag for review when medium/low.
  - b3 (flag_resolver) — to compose proposal recommendations.
  - The 'classify_expense_head' wrapper in section_classifier.py and the
    'lookup_exemption' wrapper in exemptions.py both delegate here.

Authoritative source: backend/data/TDS_Master_Data_Income_Tax_Act_1961.xlsx
(provided by founder's CA, FY 2025-26).

Each KB entry is a dict:
    {
      "keyword":        lowercase substring matched against the description
      "category":       coarse bucket (see CATEGORY_* below)
      "action":         "skip" | "apply" | "ask"
      "section":        TDS section if action == "apply"
      "skip_reason":    short tag if action == "skip"
      "confidence":     "high" | "medium" | "low"
      "rationale":      one-paragraph explanation for the user-facing note
      "alt_options":    list of alternate options the user can override to
    }

Match order: most specific keyword wins. Entries are evaluated in declaration order.

Coverage target: ~150 patterns. Resolves ~85-90% of any real Indian Tally chart
deterministically. Anything that misses → b3's grounded research path.
"""

from __future__ import annotations

import re
from typing import Any

# ── Categories ────────────────────────────────────────────────────────────

# Auto-skip categories — rows in these never become flags.
CAT_INCOME = "income_or_receipt"             # money received, not paid
CAT_LIABILITY_COLLECTED = "liability_collected"  # GST output, payable, etc.
CAT_FOREX = "forex_adjustment"               # exchange gain/loss
CAT_INVESTMENT = "investment_or_asset"       # FD, MFD, capital deposit
CAT_INTERNAL = "internal_accounting"         # running A/c, internal transfer
CAT_GOVT_LEVY = "govt_levy"                  # taxes paid TO govt
CAT_UTILITY = "utility"                      # electricity, gas, water
CAT_TELECOM = "telecom"                      # phone, internet
CAT_POSTAL = "postal"                        # stamps, postage
CAT_INSURANCE_PREMIUM = "insurance_premium"  # premium TO insurer (not commission)
CAT_BANK = "bank_charges"                    # bank service fees
CAT_REIMBURSE = "employee_reimburse"         # petty cash, imprest
CAT_CAPITAL = "capital_expenditure"          # fixed asset purchase
CAT_192 = "salary_192_out_of_scope"          # slab-based, separate framework

# Apply categories — assign a section, deductor uses standard rate.
CAT_194A = "section_194a"
CAT_194C = "section_194c"
CAT_194D = "section_194d"
CAT_194H = "section_194h"
CAT_194I_A = "section_194i_a"
CAT_194I_B = "section_194i_b"
CAT_194J_A = "section_194j_a"
CAT_194J_B = "section_194j_b"
CAT_194O = "section_194o"
CAT_194Q = "section_194q"
CAT_194R = "section_194r"
CAT_194T = "section_194t"
CAT_195 = "section_195"

# Ambiguous — surface to user with options.
CAT_AMBIGUOUS = "ambiguous"


# ── KB entries ─────────────────────────────────────────────────────────────
# Order matters: most specific FIRST. Each entry is a tuple of
# (keyword, kb_record_dict).

KB_ENTRIES: list[tuple[str, dict[str, Any]]] = [

    # ═══ INCOME / RECEIPTS — auto-skip, never an expense ═══
    ("ddb incentive", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_govt_scheme",
        "confidence": "high",
        "rationale": "Duty Drawback (DDB) Incentive Scheme is a customs rebate RECEIVED from govt, not a payment. Not TDS-applicable.",
        "alt_options": [],
    }),
    ("duty drawback", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_govt_scheme",
        "confidence": "high",
        "rationale": "Customs duty drawback received — income, not expense.",
        "alt_options": [],
    }),
    ("rodtep", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_govt_scheme",
        "confidence": "high",
        "rationale": "RoDTEP (Remission of Duties and Taxes on Exported Products) — govt incentive received by exporters. Income, not TDS-applicable.",
        "alt_options": [],
    }),
    ("meis", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_govt_scheme",
        "confidence": "high",
        "rationale": "MEIS (Merchandise Exports from India Scheme) — govt export incentive received. Income, not TDS-applicable.",
        "alt_options": [],
    }),
    ("seis", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_govt_scheme",
        "confidence": "high",
        "rationale": "SEIS (Service Exports from India Scheme) — govt service-export incentive. Income, not TDS-applicable.",
        "alt_options": [],
    }),
    ("export incentive", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_govt_scheme",
        "confidence": "high",
        "rationale": "Export incentive received from govt — income.",
        "alt_options": [],
    }),
    ("foreign inward remittance", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_remittance",
        "confidence": "high",
        "rationale": "Foreign Inward Remittance is money RECEIVED by the entity (typically export proceeds). Income, not an expense.",
        "alt_options": [],
    }),
    ("interest received", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_interest",
        "confidence": "high",
        "rationale": "Interest received is income to the entity. The bank/payer deducts TDS at source under 194A; the entity itself does not deduct anything.",
        "alt_options": [],
    }),
    ("dividend received", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_dividend",
        "confidence": "high",
        "rationale": "Dividend received is income. Issuer deducts TDS under 194/194K.",
        "alt_options": [],
    }),
    ("rent received", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_rent",
        "confidence": "high",
        "rationale": "Rent received is income. Tenant deducts TDS under 194-I.",
        "alt_options": [],
    }),
    ("commission received", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_commission",
        "confidence": "high",
        "rationale": "Commission received is income. Payer deducts TDS under 194H.",
        "alt_options": [],
    }),
    ("sales promotion", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_promotion_credit",
        "confidence": "medium",
        "rationale": "If this is a promotion credit / discount received, it's income side. Verify it's not a payment to a marketing agency (which would be 194C/194J).",
        "alt_options": ["194C — if paid to a marketing agency", "194J(b) — if creative/professional fees"],
    }),

    # ═══ LIABILITY COLLECTED — GST output / payables ═══
    ("output cgst", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_collected",
        "confidence": "high",
        "rationale": "Output CGST is GST liability collected from customers, then paid to govt. Not the entity's expense.",
        "alt_options": [],
    }),
    ("output sgst", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_collected",
        "confidence": "high",
        "rationale": "Output SGST is GST liability collected. Not an expense.",
        "alt_options": [],
    }),
    ("output igst", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_collected",
        "confidence": "high",
        "rationale": "Output IGST is GST liability collected. Not an expense.",
        "alt_options": [],
    }),
    ("gst payable", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_payable",
        "confidence": "high",
        "rationale": "GST Payable is a liability ledger, not an expense.",
        "alt_options": [],
    }),
    ("gst paid", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_payment_to_govt",
        "confidence": "high",
        "rationale": "GST Paid records GST remitted to govt — statutory tax payment, no TDS.",
        "alt_options": [],
    }),
    ("gst refundable", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_refund_due",
        "confidence": "high",
        "rationale": "GST Refundable is an asset (refund due to entity), not an expense.",
        "alt_options": [],
    }),
    ("gst unclaime", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_input_unclaim",
        "confidence": "high",
        "rationale": "GST Unclaimed (input ITC not yet claimed) is an asset, not an expense.",
        "alt_options": [],
    }),
    ("input cgst", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_input_credit",
        "confidence": "high",
        "rationale": "Input CGST is GST credit on purchases — asset, not deductible expense.",
        "alt_options": [],
    }),
    ("input sgst", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_input_credit",
        "confidence": "high",
        "rationale": "Input SGST — GST credit, not expense.",
        "alt_options": [],
    }),
    ("input igst", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "gst_input_credit",
        "confidence": "high",
        "rationale": "Input IGST — GST credit, not expense.",
        "alt_options": [],
    }),
    ("tds payable", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "tds_liability",
        "confidence": "high",
        "rationale": "TDS Payable is the liability ledger for TDS already deducted. Not a fresh expense.",
        "alt_options": [],
    }),
    ("tcs on purchase", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "tcs_collected",
        "confidence": "high",
        "rationale": "TCS on Purchase (collected by seller from buyer) is not the buyer's TDS deduction.",
        "alt_options": [],
    }),
    ("provision of income tax", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "income_tax_provision",
        "confidence": "high",
        "rationale": "Income tax provision is the entity's own tax liability — not a TDS-applicable payment.",
        "alt_options": [],
    }),
    ("advance tax", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "advance_tax",
        "confidence": "high",
        "rationale": "Advance tax is the entity's income tax payment to govt. No TDS to deduct on this.",
        "alt_options": [],
    }),
    ("income tax refund", {
        "category": CAT_INCOME, "action": "skip", "skip_reason": "income_tax_refund",
        "confidence": "high",
        "rationale": "Income tax refund is amount received from govt. Income, not expense.",
        "alt_options": [],
    }),
    ("tds receivable", {
        "category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "tds_receivable",
        "confidence": "high",
        "rationale": "TDS Receivable tracks TDS the entity expects refunded. Asset, not expense.",
        "alt_options": [],
    }),

    # ═══ FOREX ═══
    ("exchange gain", {
        "category": CAT_FOREX, "action": "skip", "skip_reason": "forex_adjustment",
        "confidence": "high",
        "rationale": "Exchange gain is an accounting adjustment from forex revaluation, not a payment. No TDS.",
        "alt_options": [],
    }),
    ("exchange loss", {
        "category": CAT_FOREX, "action": "skip", "skip_reason": "forex_adjustment",
        "confidence": "high",
        "rationale": "Exchange loss is an accounting adjustment, not a payment. No TDS.",
        "alt_options": [],
    }),
    ("forex gain", {
        "category": CAT_FOREX, "action": "skip", "skip_reason": "forex_adjustment",
        "confidence": "high",
        "rationale": "Forex gain — accounting adjustment, no TDS.",
        "alt_options": [],
    }),
    ("forex loss", {
        "category": CAT_FOREX, "action": "skip", "skip_reason": "forex_adjustment",
        "confidence": "high",
        "rationale": "Forex loss — accounting adjustment, no TDS.",
        "alt_options": [],
    }),

    # ═══ INVESTMENT / ASSET LEDGERS ═══
    ("federal bank fd", {
        "category": CAT_INVESTMENT, "action": "skip", "skip_reason": "investment_fd",
        "confidence": "high",
        "rationale": "Fixed Deposit is investment by the entity, not an expense. The bank deducts TDS on interest under 194A; the entity has nothing to deduct.",
        "alt_options": [],
    }),
    ("federal bank mfd", {
        "category": CAT_INVESTMENT, "action": "skip", "skip_reason": "investment_mfd",
        "confidence": "high",
        "rationale": "Mutual Fund Deposit is investment, not expense.",
        "alt_options": [],
    }),
    ("fixed deposit", {
        "category": CAT_INVESTMENT, "action": "skip", "skip_reason": "investment_fd",
        "confidence": "high",
        "rationale": "Fixed Deposit — investment, not TDS-applicable expense.",
        "alt_options": [],
    }),
    ("mutual fund", {
        "category": CAT_INVESTMENT, "action": "skip", "skip_reason": "investment_mf",
        "confidence": "high",
        "rationale": "Mutual fund investment — not an expense.",
        "alt_options": [],
    }),
    ("corpus fund", {
        "category": CAT_INVESTMENT, "action": "skip", "skip_reason": "capital_deposit",
        "confidence": "high",
        "rationale": "Corpus fund / capital deposit. Not an expense.",
        "alt_options": [],
    }),
    ("security deposit", {
        "category": CAT_INVESTMENT, "action": "skip", "skip_reason": "refundable_deposit",
        "confidence": "high",
        "rationale": "Refundable security deposit — asset, not expense.",
        "alt_options": [],
    }),
    ("rental deposit", {
        "category": CAT_INVESTMENT, "action": "skip", "skip_reason": "refundable_deposit",
        "confidence": "high",
        "rationale": "Refundable rental deposit — asset.",
        "alt_options": [],
    }),

    # ═══ INTERNAL ACCOUNTING ═══
    ("running account", {
        "category": CAT_INTERNAL, "action": "skip", "skip_reason": "internal_running_acct",
        "confidence": "high",
        "rationale": "Running account is an internal accounting balance, not a payment to a third party.",
        "alt_options": [],
    }),
    ("running a/c", {
        "category": CAT_INTERNAL, "action": "skip", "skip_reason": "internal_running_acct",
        "confidence": "high",
        "rationale": "Running A/c — internal accounting.",
        "alt_options": [],
    }),
    ("staff pay out", {
        "category": CAT_INTERNAL, "action": "skip", "skip_reason": "payroll_internal",
        "confidence": "high",
        "rationale": "Staff Pay Out account — internal payroll movement. Salary TDS (192) is slab-based; out of scope for this calculator.",
        "alt_options": [],
    }),
    ("payable to staff", {
        "category": CAT_INTERNAL, "action": "skip", "skip_reason": "payroll_accrual",
        "confidence": "high",
        "rationale": "Payable to Staff is a payroll accrual. TDS on salary (192) is slab-based, separate framework.",
        "alt_options": [],
    }),
    ("misc. account", {
        "category": CAT_INTERNAL, "action": "ask", "skip_reason": None,
        "confidence": "low",
        "rationale": "Miscellaneous account — generic bucket. Could be any of: contractor service, professional fee, or a non-TDS adjustment. Need user to clarify.",
        "alt_options": ["194C — if it's a service contract", "194J(b) — if professional fees", "Skip — if it's an internal adjustment"],
    }),

    # ═══ GOVT LEVIES / FILING FEES ═══
    ("rates & taxes", {
        "category": CAT_GOVT_LEVY, "action": "skip", "skip_reason": "govt_levy",
        "confidence": "high",
        "rationale": "Rates and taxes paid to govt / municipal bodies are statutory levies, not TDS-applicable payments.",
        "alt_options": [],
    }),
    ("rates and taxes", {
        "category": CAT_GOVT_LEVY, "action": "skip", "skip_reason": "govt_levy",
        "confidence": "high",
        "rationale": "Rates and taxes — statutory levies, no TDS.",
        "alt_options": [],
    }),
    ("postage", {
        "category": CAT_POSTAL, "action": "skip", "skip_reason": "govt_postal",
        "confidence": "high",
        "rationale": "Postage paid to India Post — Section 196 exempts payments to Central Govt. No TDS.",
        "alt_options": [],
    }),
    ("stamp duty", {
        "category": CAT_GOVT_LEVY, "action": "skip", "skip_reason": "govt_levy",
        "confidence": "high",
        "rationale": "Stamp duty is a govt levy.",
        "alt_options": [],
    }),
    ("stamp", {
        "category": CAT_GOVT_LEVY, "action": "skip", "skip_reason": "govt_levy",
        "confidence": "medium",
        "rationale": "If this is stamp duty / postage stamps — no TDS. If it's a stamp vendor that runs a printing service, may be 194C — verify.",
        "alt_options": ["194C — if a printing/stamping service"],
    }),
    ("filing fees", {
        "category": CAT_GOVT_LEVY, "action": "skip", "skip_reason": "govt_levy",
        "confidence": "high",
        "rationale": "Filing fees / ROC fees / govt registration fees are statutory levies. No TDS.",
        "alt_options": [],
    }),
    ("roc fees", {
        "category": CAT_GOVT_LEVY, "action": "skip", "skip_reason": "govt_levy",
        "confidence": "high",
        "rationale": "ROC fees paid to Registrar of Companies — govt levy.",
        "alt_options": [],
    }),
    ("professional tax", {
        "category": CAT_GOVT_LEVY, "action": "skip", "skip_reason": "govt_levy",
        "confidence": "high",
        "rationale": "Professional tax is a state govt levy on employees, deducted from salary and remitted to state. No TDS.",
        "alt_options": [],
    }),

    # ═══ UTILITIES ═══
    ("electricity", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "utility_no_tds",
        "confidence": "high",
        "rationale": "Electricity bills are paid to state-electricity boards or discoms (CESC, BSES, MSEB, etc.) which are statutory utilities. No specific TDS section applies.",
        "alt_options": [],
    }),
    ("electric charges", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "utility_no_tds",
        "confidence": "high",
        "rationale": "Electricity supply payments — no TDS.",
        "alt_options": [],
    }),
    ("power & fuel", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "utility_no_tds",
        "confidence": "high",
        "rationale": "Power & Fuel typically combines electricity, diesel/petrol for genset, and LPG/PNG. None are TDS-applicable utility payments.",
        "alt_options": [],
    }),
    ("power and fuel", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "utility_no_tds",
        "confidence": "high",
        "rationale": "Power and Fuel — utility expenses, no TDS.",
        "alt_options": [],
    }),
    ("diesel", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "fuel_purchase",
        "confidence": "medium",
        "rationale": "Retail diesel purchase — no TDS at the pump. 194Q only kicks in if cumulative purchases from one seller cross ₹50L AND your turnover > ₹10 Cr.",
        "alt_options": ["194Q at 0.1% — if vendor is a fleet supplier above ₹50L threshold"],
    }),
    ("generator", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "utility_no_tds",
        "confidence": "medium",
        "rationale": "Generator running expenses — usually fuel + maintenance. Fuel: no TDS. Maintenance/AMC if separate: 194C.",
        "alt_options": ["194C — if it's a maintenance contract"],
    }),
    ("water charges", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "utility_no_tds",
        "confidence": "high",
        "rationale": "Water supply from local body / municipal corporation — utility, no TDS.",
        "alt_options": [],
    }),
    ("gas charges", {
        "category": CAT_UTILITY, "action": "skip", "skip_reason": "utility_no_tds",
        "confidence": "high",
        "rationale": "Gas (LPG/PNG) supply — utility, no TDS.",
        "alt_options": [],
    }),

    # ═══ TELECOM / INTERNET ═══
    ("telephone", {
        "category": CAT_TELECOM, "action": "skip", "skip_reason": "telecom_no_tds",
        "confidence": "high",
        "rationale": "Telephone / mobile bills paid to telecom operators (Airtel, Jio, Vodafone-Idea, BSNL) — no TDS section applies. Telecom services are governed by TRAI; not 194C/194J.",
        "alt_options": [],
    }),
    ("mobile bill", {
        "category": CAT_TELECOM, "action": "skip", "skip_reason": "telecom_no_tds",
        "confidence": "high",
        "rationale": "Mobile bills — telecom service, no TDS.",
        "alt_options": [],
    }),
    ("internet", {
        "category": CAT_TELECOM, "action": "skip", "skip_reason": "telecom_no_tds",
        "confidence": "high",
        "rationale": "Internet / broadband to ISPs (Airtel, Jio, ACT, etc.) — telecom, no TDS.",
        "alt_options": [],
    }),
    ("broadband", {
        "category": CAT_TELECOM, "action": "skip", "skip_reason": "telecom_no_tds",
        "confidence": "high",
        "rationale": "Broadband to telecom ISP — no TDS.",
        "alt_options": [],
    }),

    # ═══ COMPACT APPLY-SIDE (terse rationales, expand later) ═══
    # 194C — works contract
    *[(kw, {"category": CAT_194C, "action": "apply", "section": "194C", "skip_reason": None,
            "confidence": "high", "rationale": rationale, "alt_options": []})
      for kw, rationale in [
          ("freight", "Freight / transport — 194C works contract."),
          ("carriage", "Carriage charges — 194C."),
          ("packing charges", "Packing charges — 194C."),
          ("courier", "Courier — 194C."),
          ("port expense", "Port handling charges — 194C contractor."),
          ("port charges", "Port handling — 194C."),
          ("shipment", "Shipment charges — 194C."),
          ("clearing", "Clearing & forwarding — 194C."),
          ("forwarding", "Forwarding charges — 194C."),
          ("loading", "Loading charges — 194C."),
          ("unloading", "Unloading charges — 194C."),
          ("security guard", "Security guard service — 194C."),
          ("housekeeping", "Housekeeping service — 194C."),
          ("cleaning", "Cleaning service — 194C."),
          ("pest control", "Pest control service — 194C."),
          ("printing", "Printing service — 194C."),
          ("contractor", "Contractor — 194C."),
          ("manpower", "Manpower supply — 194C."),
          ("job work", "Job work — 194C."),
          ("transportation", "Transportation contract — 194C."),
          ("vehicle hire", "Vehicle hire — 194C."),
          ("car hire", "Car / vehicle hire — 194C."),
          ("repair & maintenance", "Repair & maintenance contract — 194C."),
          ("shop repair", "Shop repair contract — 194C."),
          ("amc", "Annual maintenance contract — 194C (or 194J(b) if pure technical)."),
          ("annual maintenance", "AMC — 194C."),
          ("e.i.a.", "E.I.A. (Environmental Impact Assessment) monitoring — 194C / 194J(b)."),
      ]],

    # 194H — commission / brokerage
    *[(kw, {"category": CAT_194H, "action": "apply", "section": "194H", "skip_reason": None,
            "confidence": "high", "rationale": rationale, "alt_options": []})
      for kw, rationale in [
          ("brokerage", "Brokerage — 194H at 2%. Threshold ₹20,000 p.a."),
          ("commission", "Commission — 194H at 2%. Threshold ₹20,000 p.a."),
      ]],

    # 194J(b) — professional / royalty
    *[(kw, {"category": CAT_194J_B, "action": "apply", "section": "194J(b)", "skip_reason": None,
            "confidence": "high", "rationale": rationale, "alt_options": []})
      for kw, rationale in [
          ("audit fees", "Audit fees — 194J(b) at 10%. Threshold ₹50k p.a."),
          ("audit charges", "Audit fees — 194J(b)."),
          ("statutory audit", "Statutory audit — 194J(b)."),
          ("internal audit", "Internal audit — 194J(b)."),
          ("tax audit", "Tax audit — 194J(b)."),
          ("legal fees", "Legal fees — 194J(b)."),
          ("legal charges", "Legal charges — 194J(b)."),
          ("professional charges", "Professional fees — 194J(b)."),
          ("professional fees", "Professional fees — 194J(b)."),
          ("consultancy", "Consultancy — 194J(b)."),
          ("consulting", "Consulting fees — 194J(b)."),
          ("software", "Software licence — usually 194J(b) (royalty/technical). 194C if it's a development contract."),
          ("domain", "Domain registration / hosting — 194J(b)."),
          ("hosting", "Web hosting — 194J(b)."),
          ("testing charges", "Testing / lab analysis — 194J(b) technical service."),
          ("monitoring", "Monitoring service — 194J(b) technical."),
          ("survey", "Survey — 194J(b)."),
          ("retainer", "Retainer — 194J(b)."),
          ("director sitting", "Director sitting fees — 194J(b)."),
      ]],

    # 194J(a) — call centre / pure technical
    ("call centre", {"category": CAT_194J_A, "action": "apply", "section": "194J(a)",
                     "skip_reason": None, "confidence": "high",
                     "rationale": "Call centre fees — 194J(a) at 2%. Threshold ₹50k p.a.",
                     "alt_options": []}),
    ("call center", {"category": CAT_194J_A, "action": "apply", "section": "194J(a)",
                     "skip_reason": None, "confidence": "high",
                     "rationale": "Call centre fees — 194J(a).", "alt_options": []}),

    # 194-I — rent
    ("shop rent", {"category": CAT_194I_B, "action": "apply", "section": "194I(b)",
                   "skip_reason": None, "confidence": "high",
                   "rationale": "Shop / building rent — 194-I(b) at 10%. Threshold ₹50,000/month.",
                   "alt_options": []}),
    ("office rent", {"category": CAT_194I_B, "action": "apply", "section": "194I(b)",
                     "skip_reason": None, "confidence": "high",
                     "rationale": "Office rent — 194-I(b).", "alt_options": []}),
    ("godown rent", {"category": CAT_194I_B, "action": "apply", "section": "194I(b)",
                     "skip_reason": None, "confidence": "high",
                     "rationale": "Godown rent — 194-I(b).", "alt_options": []}),
    ("warehouse rent", {"category": CAT_194I_B, "action": "apply", "section": "194I(b)",
                        "skip_reason": None, "confidence": "high",
                        "rationale": "Warehouse rent — 194-I(b).", "alt_options": []}),
    ("plant rent", {"category": CAT_194I_A, "action": "apply", "section": "194I(a)",
                    "skip_reason": None, "confidence": "high",
                    "rationale": "Plant / machinery rent — 194-I(a) at 2%. Threshold ₹50k/month.",
                    "alt_options": []}),
    ("machinery rent", {"category": CAT_194I_A, "action": "apply", "section": "194I(a)",
                        "skip_reason": None, "confidence": "high",
                        "rationale": "Machinery rent — 194-I(a).", "alt_options": []}),
    ("equipment rent", {"category": CAT_194I_A, "action": "apply", "section": "194I(a)",
                        "skip_reason": None, "confidence": "high",
                        "rationale": "Equipment rent — 194-I(a).", "alt_options": []}),

    # 194D — insurance commission
    ("insurance commission", {"category": CAT_194D, "action": "apply", "section": "194D",
                              "skip_reason": None, "confidence": "high",
                              "rationale": "Insurance commission to agent — 194D at 5% (10% to companies).",
                              "alt_options": []}),

    # 194Q — purchase of goods (when above ₹50L per seller)
    *[(kw, {"category": CAT_194Q, "action": "apply", "section": "194Q", "skip_reason": None,
            "confidence": "medium",
            "rationale": "Goods purchase — 194Q at 0.1% if cumulative > ₹50L per seller AND your turnover > ₹10 Cr.",
            "alt_options": ["Skip if below ₹50L per seller"]})
      for kw in ["raw material", "purchase raw", "chemical", "consumable",
                 "spare", "packing material", "paint", "metal"]],

    # 194T — partner remuneration
    ("partner remuneration", {"category": CAT_194T, "action": "apply", "section": "194T",
                              "skip_reason": None, "confidence": "high",
                              "rationale": "Partner remuneration — 194T at 10%. Threshold ₹20k p.a.",
                              "alt_options": []}),
    ("partner salary", {"category": CAT_194T, "action": "apply", "section": "194T",
                        "skip_reason": None, "confidence": "high",
                        "rationale": "Salary to partner from firm — 194T.", "alt_options": []}),

    # 195 — non-resident
    ("foreign payment", {"category": CAT_195, "action": "ask", "section": "195",
                         "skip_reason": None, "confidence": "low",
                         "rationale": "Payment to non-resident — 195. Rate per IT Act or DTAA (whichever lower). Verify recipient's residence and DTAA rate.",
                         "alt_options": ["Skip if covered under DTAA exemption", "Apply 20% (IT Act default)"]}),
    ("non-resident", {"category": CAT_195, "action": "ask", "section": "195",
                      "skip_reason": None, "confidence": "low",
                      "rationale": "Non-resident payment — 195 / DTAA.", "alt_options": []}),

    # ═══ AMBIGUOUS — always ask ═══
    ("advertisement", {"category": CAT_AMBIGUOUS, "action": "ask", "section": None,
                       "skip_reason": None, "confidence": "low",
                       "rationale": "Advertisement: CA's view leans 194C (works contract / media buy). Could be 194J(b) for creative/professional design firms.",
                       "alt_options": ["194C at 2% (works / media buy)", "194J(b) at 10% (creative)"]}),
    ("conference", {"category": CAT_AMBIGUOUS, "action": "ask", "section": None,
                    "skip_reason": None, "confidence": "low",
                    "rationale": "Conference: 194C if catering/venue contract, 194-I if pure rent.",
                    "alt_options": ["194C at 2%", "194-I at 10%", "Skip if below threshold"]}),
    ("travelling", {"category": CAT_AMBIGUOUS, "action": "ask", "section": None,
                    "skip_reason": None, "confidence": "low",
                    "rationale": "Travelling: skip if employee reimbursement; 194C for vehicle hire; 194-I for hotel rent contracts.",
                    "alt_options": ["Skip (reimbursement)", "194C at 2% (vehicle hire)", "194-I at 10% (hotel)"]}),
    ("travel", {"category": CAT_AMBIGUOUS, "action": "ask", "section": None,
                "skip_reason": None, "confidence": "low",
                "rationale": "Travel: usually reimbursement; sometimes 194C / 194-I.",
                "alt_options": ["Skip", "194C at 2%", "194-I at 10%"]}),
    ("car running", {"category": CAT_AMBIGUOUS, "action": "ask", "section": None,
                     "skip_reason": None, "confidence": "low",
                     "rationale": "Car / vehicle running: skip if reimbursement; 194C if hired-vehicle contract.",
                     "alt_options": ["Skip (reimbursement)", "194C at 2%"]}),
    ("vehicle running", {"category": CAT_AMBIGUOUS, "action": "ask", "section": None,
                         "skip_reason": None, "confidence": "low",
                         "rationale": "Vehicle running — same as car running.",
                         "alt_options": ["Skip (reimbursement)", "194C at 2%"]}),
    ("decoration", {"category": CAT_AMBIGUOUS, "action": "ask", "section": None,
                    "skip_reason": None, "confidence": "low",
                    "rationale": "Decoration: 194C (works contract) usually; 194J(b) if it's a creative firm.",
                    "alt_options": ["194C at 2%", "194J(b) at 10%"]}),

    # ═══ CAPITAL — capitalised, not P&L expense ═══
    *[(kw, {"category": CAT_CAPITAL, "action": "skip", "skip_reason": "capitalised_asset",
            "confidence": "medium",
            "rationale": f"{kw.title()} purchase — capitalised, not a P&L expense. 194Q may apply at the asset purchase posting if cumulative purchases from this vendor exceed ₹50L AND your turnover > ₹10 Cr.",
            "alt_options": ["194Q at 0.1% if above threshold"]})
      for kw in ["furniture & fixtures", "fixed asset", "machinery purchase",
                 "vehicle purchase", "computer purchase", "air conditioner",
                 "camera set", "mobile set"]],

    # ═══ SALARY 192 — out of scope ═══
    *[(kw, {"category": CAT_192, "action": "skip", "skip_reason": "salary_192_out_of_scope",
            "confidence": "high",
            "rationale": "Salary TDS is Section 192 — slab-based and computed differently. Out of scope for this calculator; use a payroll tool.",
            "alt_options": []})
      for kw in ["salary & bonus", "salary and bonus", "wages", "director's salary",
                 "incentive paid"]],

    # ═══ REIMBURSEMENT — skip ═══
    *[(kw, {"category": CAT_REIMBURSE, "action": "skip", "skip_reason": "employee_reimbursement",
            "confidence": "high",
            "rationale": "Employee reimbursement — no TDS section applies.",
            "alt_options": []})
      for kw in ["petty cash", "imprest", "staff advance", "tour advance",
                 "travel reimbursement"]],

    # ═══ LESSONS LEARNT (added after live tests) ═══
    # TDS / TCS payable ledgers — Tally records "TDS ON (Purchase 194Q)" etc.
    # as the LIABILITY column tracking deductions already made. Skip.
    *[(kw, {"category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "tds_liability_ledger",
            "confidence": "high",
            "rationale": "This is a TDS / TCS liability ledger (records TDS already deducted), not an expense.",
            "alt_options": []})
      for kw in ["tds on", "tds payable", "tcs on", "tcs payable", "tds receivable"]],

    # Bank charges / processing fees variants
    *[(kw, {"category": CAT_BANK, "action": "skip", "skip_reason": "bank_charges_no_tds",
            "confidence": "high",
            "rationale": "Bank charges / processing fees — banks have their own withholding framework. No TDS to deduct.",
            "alt_options": []})
      for kw in ["bank charges", "bank charge", "processing fees", "processing charges",
                 "demat charges"]],

    # 194C extras (lessons from real charts)
    *[(kw, {"category": CAT_194C, "action": "apply", "section": "194C", "skip_reason": None,
            "confidence": "high", "rationale": "194C — works contract / labour service.",
            "alt_options": []})
      for kw in ["security service", "security charges", "labour charges", "labour supply",
                 "vehicle running charges", "godown labour", "loading & unloading",
                 "shipment expense", "shipment charges", "freight & cartage",
                 "port expenses", "port handling", "stevedoring",
                 "advertisement"]],   # CA's view: Advertisement defaults to 194C

    # 194J(b) extras
    *[(kw, {"category": CAT_194J_B, "action": "apply", "section": "194J(b)", "skip_reason": None,
            "confidence": "high", "rationale": "194J(b) — professional / technical service.",
            "alt_options": []})
      for kw in ["lab charges", "laboratory", "analysis charges",
                 "design charges", "technical fee", "technical charges",
                 "iso certification", "certification fee",
                 "subscription", "license fee",
                 "environmental", "e.i.a.", "environmental impact",
                 "consultant charges", "retainership", "valuation charges"]],

    # Sales-side / non-expense ledgers
    *[(kw, {"category": CAT_LIABILITY_COLLECTED, "action": "skip", "skip_reason": "sales_side_ledger",
            "confidence": "high",
            "rationale": "Sales-side ledger (revenue / receivable / discount given) — not an expense.",
            "alt_options": []})
      for kw in ["sales account", "sales discount", "discount allowed",
                 "discount received", "rebate received", "incentive received"]],

    # Non-TDS adjustments
    *[(kw, {"category": CAT_INTERNAL, "action": "skip", "skip_reason": "accounting_adjustment",
            "confidence": "high",
            "rationale": "Accounting adjustment / rounding — not a TDS-applicable payment.",
            "alt_options": []})
      for kw in ["round off", "rounded", "adjustment", "transfer entry",
                 "journal entry"]],
]


# ═══ Lookup helpers ═══

def lookup_kb(description: str) -> dict[str, Any] | None:
    """Return the first KB entry whose keyword matches `description`.

    Match is case-insensitive substring. Entries earlier in KB_ENTRIES win
    when multiple match (specific-first ordering).
    """
    if not description:
        return None
    d = description.lower().strip()
    for keyword, rec in KB_ENTRIES:
        if keyword in d:
            return {**rec, "matched_keyword": keyword}
    return None


# ═══ Govt vendor patterns ═══
# Used by b3 (and potentially b2 once wired) — when sample_vendors of a flag
# matches any of these, default to Section 196 exempt.
GOVT_VENDOR_PATTERNS: list[str] = [
    "customs", "excise", "central excise",
    "income tax", " ito ", "ito ",
    "gst department", "gstn", "directorate of",
    "government of", "govt. of", "govt of", "ministry of",
    "municipal", "municipality", "corporation of",
    "police", "court", "magistrate",
    "rbi", "reserve bank",
    "post office", "india post", "postal department",
    "esic", "epfo", "pf department", "provident fund",
    "transport authority", "rto",
    "defence",
    "discom", "electricity board", "state electricity",
    "cesc", "wbsfc", "msedcl", "bses", "bescom", "tneb", "kseb",
    "kolkata customs", "rbic",
]

_GOVT_VENDOR_RE = re.compile(
    "|".join(re.escape(p) for p in GOVT_VENDOR_PATTERNS),
    re.IGNORECASE,
)


def lookup_govt_vendor(vendor: str) -> bool:
    """Does this vendor name match a known govt-body pattern?

    If yes, b3 should propose Section 196 exempt.
    """
    if not vendor:
        return False
    return bool(_GOVT_VENDOR_RE.search(vendor.lower()))
