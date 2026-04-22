# BACKLOG — Lekha AI TDS Reconciliation

> Updated: 2026-04-20

## P1 — High Priority (Demo & Product Critical)

### P1.0 Memory Management + Orchestration Agent ⭐ TOP PRIORITY
**Status:** Architecture discussed, JSON memory layer designed. Picking up next session.
**What:** Stateful thinking orchestrator that reasons about reconciliation results like a CA
**Components:**
- **Memory layer** — `session.json` (chat + decisions), `run_history.json` (cross-run), `vendor_notes.json` (annotations)
- **LLM orchestrator** (Gemini) — system prompt as CA identity, results + memory as context
- **Action planning** — draft emails, suggest next steps, provide reasoned analysis
- **Vendor context** — rich vendor profiles from HPC client (expense nature, typical edge cases per section)
**Needs from client:** Vendor context data, section-wise edge case documentation
**Depends on:** Gemini API key (user has it), HPC vendor context data (pending)

### P1.1 LLM Chat Integration (F1)
**Status:** Ready to build — needs Gemini API key from user
**What:** Replace keyword-matching chat with real LLM (Gemini) powered responses
**Why:** Chat is the primary interaction layer. Current keyword matching breaks on any non-template question. LLM with results JSON as context can answer any question about the reconciliation.
**Backend:** `/api/chat` endpoint → system prompt + results JSON → Gemini API → stream response
**Frontend:** Wire chat input to POST `/api/chat` instead of `handleCommand()`

### P1.2 Stateful Orchestration Agent
**Status:** Architecture discussed, not started
**What:** Post-pipeline reasoning layer that thinks about results like a CA
**Why:** Currently pipeline dumps results and stops. Orchestrator should analyze, suggest actions, draft emails, track decisions across runs.
**Depends on:** P1.1 (LLM chat) for conversational reasoning
**Design:** LLM system prompt with CA identity + structured results as context + tool calling for actions

### P1.3 Production Migration
**Status:** Architecture planned, not started
**What:** Migrate demo logic to production DB-backed system (Supabase, 15 tables)
**Why:** Demo uses JSON files. Production needs proper data persistence, auth, multi-tenancy.
**Approach:** Extract pure logic functions → thin adapter layer for DB I/O → same matching/checking logic

### P1.4 Column Confirmation Stage (F5)
**Status:** Backend endpoint exists, frontend not built
**What:** After file upload, show detected columns → user confirms mapping → parser adapts
**Why:** Foundation for multi-format data pipeline (Tally, Zoho, GL dumps)

### P1.5 Multi-Format Data Pipeline
**Status:** Tally export guide created, adapters not built
**What:** Accept CSV, different Excel formats, GL dumps — not just Tally 3-sheet format
**Why:** Product can't scale if locked to one export format
**Substeps:**
- CSV adapter (1 hour)
- Zoho Books adapter
- Generic GL dump parser
- Tally XML Server connector (for automated sync)

## P2 — Medium Priority (Polish & Edge Cases)

### P2.1 TDS Timing Compliance — CA Review
**Status:** Built, pending CA feedback on edge cases
**What:** Late deduction (1%) and late deposit (1.5%) penalty calculator
**Pending:**
- Section 192 salary timing confirmation
- Calendar months vs 30-day periods for penalty
- Challan interest already paid (avoid double-counting)
- Provisions vs payments trigger dates

### P2.2 Debit Note / Credit Note Handling
**Status:** Not started
**What:** Purchase returns (debit notes) reduce TDS base amount
**Why:** If vendor was paid ₹1L and ₹10K returned, TDS should be on ₹90K

### P2.3 PAN Name Verification for Fuzzy Matches
**Status:** `pan_name_initial_matches()` function written but not wired
**What:** After fuzzy match, verify PAN 5th character matches vendor name initial
**Why:** Catches wrong vendor matches where names are similar but PAN doesn't align

### P2.4 Expand/Collapse + Sales Payment Reconciliation Modules
**Status:** Exists on other branches, not in demo
**What:** Bring accordion expand/collapse and sales payment recon into demo version
**Why:** Demo completeness

### P2.5 Separate Below-Threshold Sheet in Excel
**Status:** Not started
**What:** 7th sheet: "TDS Deducted Below Threshold" for voluntary TDS entries
**Why:** Distinguish voluntary TDS from exempt entries

### P2.6 Cross-Section Same-PAN Consolidation
**Status:** Not started  
**What:** Detect same PAN across multiple sections (e.g., vendor in both 194C and 194J)
**Why:** May indicate section misclassification

## Completed ✓

| Feature | Version | Date |
|---------|---------|------|
| All 6 TDS sections + Form 24 | v3.0.0 | Apr 2026 |
| Batch-level progress (F3) | v3.1.0 | Apr 2026 |
| Post-pipeline proactive insights (F4) | v3.1.0 | Apr 2026 |
| CA feedback: cross-register dedup | v3.0.2 | Apr 2026 |
| CA feedback: partial TDS coverage (Sahib fix) | v3.0.2 | Apr 2026 |
| Zero TDS section hardcode fix | v3.0.2 | Apr 2026 |
| GST Exp routing to correct section pools | v3.0.2 | Apr 2026 |
| TDS timing compliance check (Check 6) | v3.1.0 | Apr 2026 |
| PAN validation + Section 206AA | v3.1.0 | Apr 2026 |
| Threshold check: per-section books total | v3.1.0 | Apr 2026 |
| Executive Summary Excel sheet | v3.1.0 | Apr 2026 |
| Late Deduction + Late Deposit Excel sheets | v3.1.0 | Apr 2026 |
| Vertical stacked UI layout | — | Apr 2026 |
| Glass-spine UI design | — | Apr 2026 |
| 15-tile reconciliation homepage | — | Apr 2026 |
| 5-box KPI cards | — | Apr 2026 |
| Sticky user message in chat | — | Apr 2026 |
| Tally export guide for clients | — | Apr 2026 |
| Backend development report (Word) | — | Apr 2026 |
