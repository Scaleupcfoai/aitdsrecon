# AI TDS Recon — New Joinee Onboarding Guide

> Last updated: 2026-03-25

---

## 1. What Is This Project?

**AI TDS Recon** is an automated TDS (Tax Deducted at Source) reconciliation system for Indian businesses. It takes two inputs:

- **Form 26 (Deduction Register)** — the government's record of TDS deducted by a company
- **Tally Extract** — the company's own accounting records from Tally ERP

The system reconciles these two sources to find mismatches, missing deductions, incorrect rates, and compliance issues — work that CAs and accountants currently do manually in Excel, often taking days.

This sits inside the broader **Lekha AI** product vision, which also includes a payment reconciliation demo (frontend-only, React+Vite) already built and shared with stakeholders.

---

## 2. Why Are We Building This? (The Problem)

### The pain today

Every Indian company that deducts TDS must file quarterly returns (Form 24Q/26Q/27Q). Before filing, they must reconcile:

- What they **actually deducted** (Tally books) vs. what the **government recorded** (Form 26AS / Deduction Register)
- Whether the correct **TDS section** was applied (194A for interest, 194C for contractors, etc.)
- Whether the correct **TDS rate** was used (depends on PAN entity type)
- Whether TDS was computed on the **right base amount** (pre-GST, not gross)
- Whether any **expenses are missing TDS** entirely (non-compliance risk)

### Why this is hard

- Tally data is messy — multi-register, 2D layouts, inconsistent naming
- Vendor names differ between Form 26 and Tally (e.g., "Inland World" vs "Inland World Logistics Pvt. Ltd.")
- One Form 26 entry may correspond to multiple Tally invoices aggregated monthly
- GST complicates base amount calculations
- Thresholds and rates vary by section and entity type

### What goes wrong without automation

- Missed TDS → penalty under Section 201(1A) + interest
- Wrong section → incorrect return filing
- Manual process takes 2-5 days per quarter for a mid-size company
- CAs charge ₹15K-50K per quarter for this work

### Our goal

Reduce TDS reconciliation from **days to minutes**, with clear compliance reports and actionable findings that a CA or CFO can review and act on.

---

## 3. What We Have Achieved So Far

### A. Payment Reconciliation Demo (Lekha AI v1) — COMPLETE

A fully functional React SPA demonstrating payment-to-sales reconciliation for e-commerce/D2C brands.

- **Stack:** React 19 + Vite 7, no backend (mock data)
- **Features:** 3-panel layout, file upload wizard, AI chat, grouped unreconciled transactions, 7 issue categories with resolution actions, email modal
- **Status:** Demo complete, pushed to GitHub, shared with developer
- **Run it:** `npm install && npm run dev` → http://localhost:5174/

### B. TDS Reconciliation Pipeline (v2 Backend) — FUNCTIONAL

A Python CLI pipeline with **5 specialized agents** and a **gated orchestrator**.

#### The 5 Agents

| Agent | File | Lines | What It Does |
|-------|------|-------|-------------|
| **Parser** | `agents/parser_agent.py` | 547 | Reads Form 26 + 3 Tally registers (Journal, Purchase GST Exp, Purchase) → normalized JSON |
| **Matcher** | `agents/matcher_agent.py` | 923 | 6-pass matching engine: exact → GST-adjusted → exempt filter → fuzzy → aggregated |
| **TDS Checker** | `agents/tds_checker_agent.py` | 812 | 5 compliance checks: section, rate, base amount, threshold, missing TDS |
| **Learning** | `agents/learning_agent.py` | 618 | Captures human decisions → reusable rules (vendor aliases, exemptions, overrides) |
| **Reporter** | `agents/reporter_agent.py` | 395 | Generates executive summary (JSON) + reconciliation report (CSV) + findings report (CSV) |

#### The Orchestrator

`reconcile.py` (640 lines) wires everything together with **gates** and **routing**:

```
XLSX Inputs
  → [GATE 1] Validate inputs (files exist? parseable?)
  → [STAGE 1] Parser Agent → parsed JSON
  → [GATE 2] Check parsed output (entries > 0?)
  → [STAGE 2] Matcher Agent → match results
  → [ROUTING] If 0 unmatched → skip checker
  → [STAGE 3] TDS Checker Agent → compliance findings
  → [ROUTING] If errors → flag for human review
  → [STAGE 4] Reporter Agent → summary + CSV reports
  → [BUILD] Human Review Queue (prioritized list of items needing attention)
  → Output: pipeline_result.json
```

#### Results on Real Data (HPC Customer, 2026-03-24)

| Metric | Value |
|--------|-------|
| Form 26 entries in scope | 56 (sections 194A + 194C) |
| **Match rate** | **100%** (56/56) |
| Average confidence | 0.957 |
| Exact matches | 28 (50%) |
| Fuzzy matches | 9 (16%) |
| Aggregated matches | 18 (32%) |
| GST-adjusted matches | 1 (2%) |
| Compliance findings | 8 (3 errors, 5 warnings) |
| Missing TDS exposure | ₹1,21,397 |

#### Sections Currently Supported

| Section | Description | Status |
|---------|------------|--------|
| 194A | Interest payments | Fully supported |
| 194C | Contractor/freight payments | Fully supported |
| 194H | Commission/brokerage | Parsed, not yet matched |
| 194J(b) | Professional fees | Parsed, not yet matched |
| 194Q | Purchase of goods | Parsed, not yet matched |

---

## 4. Why This Approach? (Architecture Decisions)

### Why deterministic agents, not LLM-based?

- **Accuracy matters more than flexibility** — TDS compliance has zero tolerance for hallucination. A wrong section or rate means penalties.
- **Auditability** — Every match has a confidence score, pass number, and match details. A CA can verify why any entry was matched.
- **Speed** — The full pipeline runs in seconds on 85 Form 26 entries. No API calls, no token costs.
- **Reproducibility** — Same inputs → same outputs, every time. Critical for compliance work.

### Why a multi-pass matcher instead of a single algorithm?

- Real-world data has multiple matching patterns. Some entries match exactly (same name, amount, date). Others need fuzzy matching (slightly different names). Others are monthly aggregations (30 small Tally invoices → 1 Form 26 entry).
- Running passes in priority order (exact first, then fuzzy, then aggregated) gives the highest confidence matches first and prevents false positives from grabbing entries that would exact-match later.

### Why a gated orchestrator?

- **Fail fast** — If parsing fails, don't waste time matching garbage data.
- **Smart routing** — If everything matches perfectly, skip the compliance checker entirely.
- **Human-in-the-loop** — The review queue ensures edge cases get human attention rather than being silently miscategorized.

### Why a learning agent?

- Every company has unique vendor names, expense categorizations, and edge cases.
- Rather than hardcoding rules for every client, the Learning Agent captures human decisions (e.g., "Inland World = Inland World Logistics") and applies them automatically in future runs.
- This means the system gets better with each reconciliation cycle.

### Why separate frontend and backend?

- The payment recon demo (React) was built first to validate UX with stakeholders.
- The TDS backend (Python) was built separately because the domain logic is fundamentally different.
- These will eventually be integrated, but keeping them separate now allows faster iteration on each.

---

## 5. Problems Faced, Resolved, and Open

### Resolved

| Problem | How We Solved It |
|---------|-----------------|
| **Tally data is 2D** — registers have nested multi-row transactions with merged cells | Parser agent detects register type and handles each layout separately (Journal = 68 cols, Purchase GST Exp = 42 cols, Purchase = separate) |
| **Vendor names differ** between Form 26 and Tally | Multi-pass approach: exact match first, then normalized fuzzy matching (strip Pvt. Ltd., lowercase, token overlap), plus vendor alias rules from Learning Agent |
| **One F26 entry = many Tally invoices** | Aggregated matching (Pass 5): monthly sum, cumulative sum, subset-sum search, quarterly sum — with 5 strategies tried in order |
| **GST inflates amounts** | GST-adjusted matching (Pass 2): compare F26 amount against Tally base_amount (pre-GST). TDS Checker also verifies TDS was computed on pre-GST base per CBDT Circular 23/2017 |
| **Different TDS rates for different entity types** | Checker extracts entity type from PAN 4th character (C=Company, P=Individual, H=HUF) and looks up expected rate from TDS_RATES table |
| **False positives in fuzzy matching** | Strict thresholds (name similarity ≥ 0.4, amount ±0.5%, date ±30 days) + weighted scoring + running after exact match consumes the easy ones |
| **Small expenses cluttering review queue** | Exempt filter (Pass 3) removes Tally entries below ₹100 |

### Open / Known Limitations

| Issue | Impact | Planned Approach |
|-------|--------|-----------------|
| **3 sections not yet matched** (194H, 194J(b), 194Q) | ~40 Form 26 entries not reconciled | Extend matcher with section-specific logic for commission, professional fees, and goods purchase |
| **No automated tests** | Regressions possible when adding new sections | Add pytest suite covering each agent + integration tests for the full pipeline |
| **Subset-sum is O(2^n)** | Currently capped at 20 entries per vendor — could miss matches for high-volume vendors | Optimize with dynamic programming or approximation for vendors with >20 monthly invoices |
| **No UI for TDS recon** | Pipeline is CLI-only; CAs can't use it without technical help | Build a web interface (likely extending the Lekha AI frontend) with file upload, progress tracking, and interactive review queue |
| **Learning Agent not battle-tested** | Rules exist but haven't been validated across multiple clients | Test with 2-3 more client datasets; tune auto-seed thresholds |
| **No logging framework** | Uses print statements; hard to debug in production | Migrate to Python `logging` module with structured log levels |
| **Frontend and backend are disconnected** | Two separate apps with no data flow | Plan integration via API layer (FastAPI or similar) |

---

## 6. Future Plans

### Short-term (Next 2-4 weeks)
1. **Complete section coverage** — Add matching logic for 194H, 194J(b), 194Q
2. **Add test suite** — pytest for each agent + end-to-end pipeline tests
3. **Validate on more data** — Run pipeline on 2-3 more client datasets to stress-test edge cases

### Medium-term (1-2 months)
4. **Build TDS recon UI** — Web interface for upload, review queue, and report download
5. **Integrate Learning Agent into workflow** — Interactive review mode in the UI
6. **Add logging and error handling** — Production-grade observability

### Long-term (3+ months)
7. **Connect frontend and backend** — Unified Lekha AI product with both payment recon and TDS recon
8. **Multi-client support** — Separate rule sets per client, data isolation
9. **Quarterly filing assistance** — Generate Form 24Q/26Q/27Q-ready data from reconciled output
10. **Explore AI augmentation** — Use LLMs for ambiguous expense classification and vendor name resolution where deterministic rules fall short

---

## 7. How to Get Started

```bash
# Clone and enter the repo
git clone https://github.com/Scaleupcfoai/aitdsrecon.git
cd aitdsrecon

# --- Frontend (Payment Recon Demo) ---
npm install
npm run dev                  # → http://localhost:5174/

# --- Backend (TDS Recon Pipeline) ---
pip install openpyxl         # Only dependency
python tds-recon/reconcile.py   # Uses pre-parsed data in tds-recon/data/parsed/

# Check the outputs
ls tds-recon/data/results/
# → pipeline_result.json, match_results.json, checker_results.json,
#   reconciliation_summary.json, reconciliation_report.csv, findings_report.csv
```

### Key files to read first

1. `CHANGELOG.md` — Version history and current status
2. `tds-recon/reconcile.py` — The orchestrator; read this to understand the full flow
3. `tds-recon/agents/matcher_agent.py` — The core matching logic (most complex agent)
4. `tds-recon/agents/tds_checker_agent.py` — Compliance rules engine
5. `tds-recon/data/results/reconciliation_summary.json` — Sample output to see what the pipeline produces

---

## 8. Repo Structure

```
aitdsrecon/
├── CLAUDE.md                          # Project identity & instructions
├── CHANGELOG.md                       # Version history
├── ONBOARDING.md                      # This file
├── SOP.md                             # Startup guide
├── package.json                       # Frontend dependencies
│
├── src/                               # Frontend (Lekha AI v1 — Payment Recon)
│   ├── App.jsx                        # All UI logic (929 lines)
│   ├── index.css                      # All styles (648 lines)
│   └── data/mockData.js               # 80 mock transactions
│
├── data/hpc/                          # Real client data (HPC)
│   ├── Form 26 - Deduction Register.xlsx
│   └── Tally extract.xlsx
│
└── tds-recon/                         # Backend (TDS Reconciliation Pipeline)
    ├── reconcile.py                   # Orchestrator (640 lines)
    ├── agents/
    │   ├── parser_agent.py            # XLSX → JSON (547 lines)
    │   ├── matcher_agent.py           # 6-pass matching (923 lines)
    │   ├── tds_checker_agent.py       # 5 compliance checks (812 lines)
    │   ├── learning_agent.py          # Rules DB + human feedback (618 lines)
    │   └── reporter_agent.py          # Report generation (395 lines)
    └── data/
        ├── parsed/                    # Parser outputs (JSON)
        ├── results/                   # Pipeline outputs (JSON + CSV)
        └── rules/                     # Learned rules DB
```

---

*Questions? Reach out to Ashish (Founder) or check the codebase — the code is well-structured and the agent names tell you exactly what each file does.*
