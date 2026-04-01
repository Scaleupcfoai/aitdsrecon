
# LEKHA AI — TDS RECONCILIATION LOGIC
## Detailed Audit Notes for CA Review
### Date: April 2026 | System Version: 3.0.0

---

## 1. SYSTEM OVERVIEW

Lekha AI automates TDS reconciliation between **Form 26 (government TDS records)** and **Tally accounting books**. The system:

1. **Parses** uploaded Excel files (Form 26 + Tally registers)
2. **Maps columns** using fuzzy matching + LLM for uncertain columns
3. **Matches** Form 26 entries to Tally entries using 6 progressive passes
4. **Checks compliance** with 5 validation rules
5. **Generates reports** (JSON, CSV, Excel)

**LLM Used:** Groq (Llama 3.3 70B) — used for ambiguous column mapping, ambiguous match resolution, section classification, and remediation writing. All TDS rates/thresholds come from a verified knowledge base, NOT from LLM training data.

**TDS Sections Currently In Scope:** 194A (Interest) and 194C (Contractors). Other sections (194H, 194J, 194Q etc.) are defined in the knowledge base but not yet active in matching.

---

## 2. FILE PARSING LOGIC

### 2.1 Form 26 (TDS Deduction Register)

**Source:** Excel file, typically from TRACES portal

**Column Detection:** Automated via fuzzy matching against known keywords:
| Target Field | Detection Keywords |
|---|---|
| party_name | name, party, vendor, deductee, payee, particulars |
| pan | pan, pan no, pan number |
| tds_section | section, tds section, sec |
| gross_amount | amount paid, amt paid, gross amount, amount credited |
| tds_amount | tax deducted, tds amount, tds deducted, income tax |
| date_of_deduction | date, deduction date, tax date, payment date |
| tax_rate | rate, tax rate, tds rate, rate % |
| certificate_number | certificate, cert no, tds certificate |

**Column Mapping Confidence:**
- **≥ 0.8** → Auto-mapped (no human review needed)
- **< 0.8** → Sent to LLM for classification
- **LLM confidence < 0.6** → Flagged `needs_review` for human confirmation

**Vendor Name Parsing:**
- Pattern: `"Name (ID); PAN: XXXX"`
- Regex extracts: name, numeric ID, PAN separately

**Date Handling:**
- Excel serial numbers (1–55000 range) → converted to dates
- DD/MM/YYYY strings → parsed
- Invalid/out-of-range → stored as NULL (not rejected)

### 2.2 Tally Journal Register

**Source:** Tally export, typically 68+ columns

**Entry Classification by Account Postings:**
| Account Column(s) with Value | Entry Type | TDS Section |
|---|---|---|
| Interest Paid + Loan column | interest_payment | 194A |
| Freight Charges | freight_expense | 194C |
| Brokerage and Commission | brokerage | 194H |
| Audit Fees | audit_fees | 194J(b) |
| Professional Charges | professional_fees | 194J(b) |
| Consultancy Charges | consultancy | 194J(b) |
| TDS Payable (only) | tds_deduction | Skipped |
| Salary & Bonus | salary | Skipped |

**Interest Party Extraction:** Pattern `"Name (Loan)"` → extracts name from loan reference

### 2.3 Tally Purchase GST Expense Register

**Source:** Tally export, typically 42+ columns

**GST Column Detection:** Matches patterns: "input c gst", "input s gst", "input i gst", "cgst", "sgst", "igst"

**Amount Computation:**
```
base_amount = SUM(all expense head columns)
total_gst   = SUM(all GST columns: CGST + SGST + IGST)
gross_total = base_amount + total_gst
```

**Critical Note:** TDS is computed on `base_amount` (pre-GST), NOT on `gross_total`. The parser stores both, and the matcher uses `base_amount` for comparison against Form 26.

### 2.4 Company Auto-Detection

- Row 1 of both files → company name
- Row 2 of Form 26 → form type (24Q/26Q) and period
- Row 3 of Tally → CIN number
- Auto-creates company in database if not found

---

## 3. MATCHING ENGINE — 6 PASSES

The matcher runs 6 progressive passes. Each pass only operates on **unmatched** entries from previous passes. Once an entry is matched, it's excluded from subsequent passes.

**Sections processed separately:** 194A entries match against 194A pool; 194C against 194C pool. No cross-section matching.

### Pass 1: Exact Match
| Parameter | Value |
|---|---|
| Confidence | 1.00 (fixed) |
| Name comparison | Exact match after normalization |
| Amount comparison | Exact (₹0 tolerance) |
| Date window | ±3 days |

**Name Normalization:**
- Lowercase
- Remove suffixes: "pvt. ltd.", "pvt ltd", "private limited", "ltd.", "ltd", "llp", "lp", "inc.", "inc", "co.", "company"
- Remove numeric IDs in parentheses: `(123)`
- Collapse whitespace

**Example:** "ABC Pvt. Ltd. (123)" → "abc"

### Pass 2: GST-Adjusted Match
| Parameter | Value |
|---|---|
| Confidence | 0.95 (fixed) |
| Name similarity | ≥ 50% token overlap |
| Amount comparison | Form 26 amount ≈ Tally base_amount (±0.5%) |
| Date window | ±90 days (same quarter) |
| Applies to | Only entries from `gst_exp` source (have GST breakup) |

**Rationale:** Form 26 records TDS on pre-GST base amount. Tally records gross (with GST). This pass uses the parser-computed `base_amount` to bridge the gap.

**Amount Closeness Formula:**
```
amount_close(a, b) = abs(a - b) / max(abs(a), abs(b)) ≤ 0.005
```

### Pass 3: Exempt Filter
| Parameter | Value |
|---|---|
| Threshold | Amount < ₹100 |
| Action | Marks Tally entry as exempt, removes from unmatched pool |

**⚠ AUDIT FLAG:** This ₹100 threshold is a placeholder. The actual TDS thresholds per section are:
- 194A: ₹5,000 annual
- 194C: ₹30,000 single / ₹1,00,000 annual
- 194H: ₹15,000 annual

The ₹100 filter only removes trivially small amounts. It does NOT implement proper threshold logic.

### Pass 4: Fuzzy Match
| Parameter | Value |
|---|---|
| Name similarity | ≥ 40% token overlap |
| Amount tolerance | ±0.5% |
| Date window | ±30 days |
| Minimum score | > 0.5 (weighted composite) |
| Best-match | Takes highest-scoring candidate only |

**Name Similarity Formula (Token Overlap):**
```
tokens_a = set(normalize(name_a).split())
tokens_b = set(normalize(name_b).split())
similarity = len(tokens_a ∩ tokens_b) / min(len(tokens_a), len(tokens_b))
```

**Composite Score:**
```
amount_diff = abs(f26_amount - tally_amount) / max(f26_amount, 1)
score = name_similarity × 0.5 + (1 - amount_diff) × 0.5
```

### Pass 5: Aggregated Match (6 strategies)

Handles cases where **multiple Tally entries** correspond to **one Form 26 entry** (e.g., many monthly freight invoices → one quarterly TDS deposit).

**Strategy order (stops at first match):**

| # | Strategy | Confidence | Logic |
|---|---|---|---|
| 1 | Monthly Sum | 0.90 | Sum Tally entries in same month as F26 |
| 2 | Cumulative to Date | 0.85 | Sum all Tally entries up to F26 date |
| 2b | Subset Sum (to date) | 0.80 | Find subset of entries up to F26 date that sum to F26 amount |
| 3 | All Available | 0.75 | Sum all available entries for vendor |
| 3b | Subset Sum (all) | 0.70 | Find subset of all entries that sum to F26 amount |
| 4 | Quarterly Sum | 0.85 | Sum entries in same quarter as F26 |

**Vendor matching:** ≥ 50% name similarity required

**Amount tolerance:** ±0.5% for all strategies

**Subset Sum Algorithm:** Greedy approach (date-ordered accumulation). If overshoot, tries removing one entry at a time. Limited to ≤ 20 entries for tractability.

**⚠ AUDIT FLAG:** The greedy subset-sum is not exhaustive. It may miss valid subsets. For example, if entries [100, 200, 300] need to match target 500, greedy takes [100, 200, 300] = 600 (overshoot), removes 100 → 500 ✓. But if entries are [300, 100, 200], greedy takes [300, 100] = 400, then [300, 100, 200] = 600, overshoot, removes 300 → 300 ✗. It would miss the [200, 300] combination.

### Pass 6: LLM-Assisted Match
| Parameter | Value |
|---|---|
| Trigger | Only for entries still unmatched after Passes 1–5 |
| Candidates | Tally entries with name similarity ≥ 30% |
| LLM Model | Llama 3.3 70B (via Groq) |
| Confidence | Set by LLM (0.0–1.0) |

**What goes to LLM:**
```
Form 26 entry: Vendor, Section, Amount, Date, PAN
Candidate Tally entries: Party name, Amount, Date, Expense type
```

**LLM decides:** Is there a match? Which candidate? Confidence? Reasoning?

**LLM is told to be conservative:** "A wrong match is worse than no match."

---

## 4. COMPLIANCE CHECKS — 5 VALIDATIONS

Run AFTER matching, on the matched entries.

### Check 1: Section Validation
**What:** Verifies Form 26 section matches the Tally expense type.

**Section-to-Expense Mapping:**
| Section | Expected Expense Keywords |
|---|---|
| 194A | interest, loan |
| 194C | freight, carriage, transport, logistics, packing, printing, maintenance, contractor |
| 194H | brokerage, commission |
| 194J(a) | call centre, technical |
| 194J(b) | professional, consultancy, audit, legal, software |
| 194Q | purchase |

**Ambiguous Expenses (flagged for review):**
- **Advertisement:** 194C (works contract) OR 194J(b) (professional)
- **AMC:** 194C (facility maintenance) OR 194J(b) (software/technical)
- **Software:** 194J(b) (license) OR 194C (development contract)

**Severity:** Mismatch = ERROR, Ambiguous = WARNING, Can't classify = INFO

### Check 2: Rate Validation
**What:** Compares declared TDS rate against statutory rate for section + entity type.

**Rate Table:**
| Section | Individual/HUF | Company | Default |
|---|---|---|---|
| 194A | 10.0% | 10.0% | 10.0% |
| 194C | 1.0% | 2.0% | 2.0% |
| 194H | 2.0% | 2.0% | 2.0% |
| 194J(a) | 2.0% | 2.0% | 2.0% |
| 194J(b) | 10.0% | 10.0% | 10.0% |
| 194Q | 0.1% | 0.1% | 0.1% |

**Entity Type from PAN (4th character):**
- C → Company
- P → Individual
- H → HUF
- F → Firm

**Tolerance:** < 0.01% difference allowed (essentially exact match)

**Severity:** ERROR

### Check 3: Base Amount Validation
**What:** Ensures TDS was computed on pre-GST base amount, not GST-inclusive gross.

**Logic:**
1. Compare Form 26 `amount_paid` against Tally `base_amount` and `gross_amount`
2. If F26 amount is closer to gross than to base → TDS computed on wrong base

**Tolerance:** ₹1 minimum or 0.5% of base amount

**Excess TDS Formula:**
```
gst_component = gross_total - base_total
excess_tds = (declared_rate / 100) × gst_component
```

**Severity:** ERROR

### Check 4: Threshold Validation
**What:** Checks if aggregate payments breach annual TDS thresholds.

**Thresholds:**
| Section | Single Payment Limit | Annual Aggregate Limit |
|---|---|---|
| 194A | None | ₹5,000 |
| 194C | ₹30,000 | ₹1,00,000 |
| 194H | None | ₹15,000 |
| 194J(a) | None | ₹30,000 |
| 194J(b) | None | ₹30,000 |
| 194Q | None | ₹50,00,000 |

**Logic:** Groups Form 26 entries by (vendor, section), sums aggregate. If below threshold but TDS was deducted → informational flag (not an error — voluntary deduction is allowed).

**Severity:** INFO

### Check 5: Missing TDS Detection
**What:** Finds Tally expenses where TDS should have been deducted but no Form 26 entry exists.

**Algorithm:**
1. Build set of Form 26 vendors (normalized) per section
2. For each unmatched Tally entry:
   - Classify expense head → expected TDS section
   - Check if vendor has Form 26 entry in that section
   - If not → potential missing TDS

**Name Matching:** ≥ 50% token overlap considered a match

**Skipped Entries:** TDS deductions, salary, discount entries in journal register

**Severity:**
- Aggregate above threshold → ERROR
- Aggregate below threshold → WARNING

---

## 5. KNOWLEDGE BASE (Single Source of Truth)

**File:** `app/knowledge/tds_rules.json`

**Source:** Income Tax Act 1961, Finance Act 2025, CBDT Circulars

**Covers 19 TDS sections:** 192, 194A, 194C, 194D, 194DA, 194H, 194I(a), 194I(b), 194J(a), 194J(b), 194K, 194LA, 194M, 194N, 194O, 194Q, 195

**Amendment Tracked:** 194H rate changed from 5% to 2% by Finance Act 2025

**Penalty Framework:**
| Provision | Consequence |
|---|---|
| 201(1A) | Interest: 1% per month (not deducted), 1.5% per month (deducted not deposited) |
| 234E | Late filing fee: ₹200/day, max = total TDS amount |
| 271C | Penalty for non-deduction: Equal to TDS amount |
| 271H | Late filing: ₹10,000–₹1,00,000 (if >1 year late) |
| 276B | Criminal prosecution: 3 months–7 years + fine |

**Due Dates:**
- TDS deposit: 7th of following month (March: 30th April)
- Return filing: Q1→31 Jul, Q2→31 Oct, Q3→31 Jan, Q4→31 May

**LLM Knowledge Injection:** Every LLM call receives the full knowledge base with instruction: "Use ONLY these verified rules. Do NOT rely on training data for rates, thresholds, or penalties."

---

## 6. ALL THRESHOLDS & MAGIC NUMBERS

| Parameter | Value | Location | Used In |
|---|---|---|---|
| Column auto-map confidence | ≥ 0.8 | column_mapper.py | Deciding which columns need LLM/human review |
| LLM column confidence threshold | < 0.6 → needs_review | column_mapper.py | Flagging uncertain columns |
| Pass 1 date window | ±3 days | matcher_agent.py | Exact matching |
| Pass 2 name similarity | ≥ 50% | matcher_agent.py | GST-adjusted matching |
| Pass 2 date window | ±90 days | matcher_agent.py | GST-adjusted matching |
| Pass 3 exempt threshold | < ₹100 | matcher_agent.py | **Placeholder — not proper threshold** |
| Pass 4 name similarity | ≥ 40% | matcher_agent.py | Fuzzy matching |
| Pass 4 minimum score | > 0.5 | matcher_agent.py | Fuzzy match acceptance |
| Pass 4 date window | ±30 days | matcher_agent.py | Fuzzy matching |
| Pass 5 name similarity | ≥ 50% | matcher_agent.py | Aggregated matching |
| Pass 5 subset-sum limit | ≤ 20 entries | matcher_agent.py | Computational limit |
| Amount tolerance (global) | ±0.5% | utils.py | All amount comparisons |
| Rate validation tolerance | < 0.01% | tds_checker_agent.py | TDS rate checking |
| Base amount tolerance | ₹1 or 0.5% | tds_checker_agent.py | GST base validation |
| Missing TDS name overlap | ≥ 50% | tds_checker_agent.py | Vendor matching |

---

## 7. KNOWN LIMITATIONS & AUDIT CONCERNS

### 7.1 Sections In Scope
Only **194A and 194C** are actively matched. Form 26 entries for other sections (194H, 194J, 194I, 194Q) are parsed but **excluded from matching** (hardcoded filter: `target_sections = {"194A", "194C"}`).

### 7.2 Pass 3 Exempt Threshold
The ₹100 threshold is a **placeholder**. It does not implement the actual statutory thresholds (₹30K/₹1L for 194C, ₹5K for 194A). This means entries between ₹100 and the actual threshold remain in the unmatched pool unnecessarily.

### 7.3 Subset-Sum Algorithm
The greedy subset-sum (Pass 5) is **not exhaustive**. It may miss valid combinations. A proper combinatorial search (with memoization) would be more accurate but computationally expensive.

### 7.4 Name Similarity False Positives
Token-overlap similarity can produce false matches for very short names. Example: "ABC" and "ABC Trucking" both normalize to tokens {"abc"} and {"abc", "trucking"} → 1/1 = 100% similarity, even though they may be different entities.

### 7.5 Date Handling
Excel serial numbers outside the 1–55000 range are rejected. Some Tally exports use non-standard date formats that may not be captured.

### 7.6 GST Rate Assumption
Pass 2 does not assume a GST rate — it uses the parser-computed `base_amount`. This is correct. However, if the parser's GST column detection fails (columns not recognized), `base_amount` may equal `gross_total`, causing Pass 2 to fail silently.

### 7.7 LLM Dependency
Pass 6 (LLM matching), ambiguous column mapping, and section classification all require LLM availability. If LLM is unavailable (rate limited, API down), these capabilities degrade silently to deterministic fallback.

### 7.8 No Reverse Matching
The system matches Form 26 → Tally (one direction). It does not independently verify if all TDS-liable Tally entries have corresponding Form 26 entries, except through Check 5 (Missing TDS Detection).

---

## 8. DATA FLOW SUMMARY

```
Form 26 XLSX ──→ Parser ──→ TDS Entries (DB)
                    │              │
                    │         ┌────┴────┐
                    │         ↓         ↓
Tally XLSX ───→ Parser ──→ Ledger   Matcher ──→ Match Results (DB)
                  Entries     (6 passes)          │
                  (DB)                             ↓
                                            Compliance Checker
                                            (5 checks)
                                                   │
                                                   ↓
                                             Reporter
                                          (JSON, CSV, Excel)
```

---

*Document prepared for CA audit of Lekha AI TDS Reconciliation Engine v3.0.0*
*All thresholds, rates, and logic extracted directly from source code.*
