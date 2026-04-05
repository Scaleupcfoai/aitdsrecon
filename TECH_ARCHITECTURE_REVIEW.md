# Lekha AI — Technical Architecture Review
## TDS Reconciliation Platform v3.0.0
**Date:** April 5, 2026  
**Prepared for:** External Technical Reviewer  
**Status:** Pre-production (local development)

---

## 1. Executive Summary

Lekha AI is a multi-agent TDS (Tax Deducted at Source) reconciliation platform for Indian CA firms. It reconciles government Form 26 TDS records against company accounting books (Tally) using a 6-pass matching engine with LLM augmentation.

**Current state:** Working prototype with significant data quality and architectural gaps identified through database audit. No production deployment yet.

**Tech stack:**
- **Backend:** Python 3.11, FastAPI 3.0, Supabase (PostgreSQL + Auth + RLS), Groq LLM (Llama 3.3 70B)
- **Frontend:** React 18, Vite, Supabase Auth (JWT), fetch-based SSE
- **Infrastructure:** Local development only. No CI/CD, no staging, no containerization.

---

## 2. System Architecture

### 2.1 High-Level Components

```
┌─────────────────────┐     ┌──────────────────────────────────────────┐
│   React Frontend    │────▶│  FastAPI Backend (app/main.py)           │
│   (aibookclose)     │ JWT │                                          │
│                     │◀────│  6 API Routers:                          │
│  - TdsRecon.jsx     │ SSE │    /api/auth         (JWT verification)  │
│  - AuthContext       │     │    /api/upload       (file upload)       │
│  - Supabase Auth    │     │    /api/reconciliation (pipeline + SSE)  │
│                     │     │    /api/reports       (download reports)  │
│                     │     │    /api/chat          (LLM chat agent)   │
│                     │     │    /api/company       (CRUD)             │
│                     │     │                                          │
│                     │     │  Pipeline:                               │
│                     │     │    Orchestrator → Parser → Matcher →     │
│                     │     │    Checker → Reporter                    │
│                     │     │                                          │
└─────────────────────┘     │  External Services:                      │
                            │    Supabase (DB + Auth + RLS)            │
                            │    Groq API (LLM - Llama 3.3 70B)       │
                            └──────────────────────────────────────────┘
```

### 2.2 API Surface

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/health` | No | Health check + LLM availability |
| POST | `/api/auth/register-firm` | Yes | Register CA firm |
| POST | `/api/upload` | Yes | Upload Form 26 + Tally XLSX |
| POST | `/api/upload/map-columns` | Yes | Run column detection (unused by frontend) |
| GET | `/api/reconciliation/stream` | Yes | Run pipeline with SSE streaming |
| POST | `/api/reconciliation/run` | Yes | Run pipeline (blocking) |
| GET | `/api/reconciliation/status/{run_id}` | Yes | Poll run status |
| GET | `/api/reconciliation/runs` | Yes | List runs for company |
| POST | `/api/answer` | No | Submit answer to pipeline question |
| POST | `/api/chat/stream` | Yes | LLM chat with streaming |
| POST | `/api/chat/reset` | Yes | Clear chat history |
| GET | `/api/reports/{run_id}/summary` | **No** | Get reconciliation summary |
| GET | `/api/reports/{run_id}/findings` | **No** | Get compliance findings |
| GET | `/api/reports/{run_id}/download/{filename}` | **No** | Download report file |
| GET | `/api/companies` | Yes | List companies for firm |
| POST | `/api/companies` | Yes | Create company |

### 2.3 Database Schema (Supabase PostgreSQL)

**15 tables with Row-Level Security (RLS):**

| Table | Rows (Current) | Purpose | Status |
|-------|----------------|---------|--------|
| ca_firm | 3 | CA firm master | Working |
| app_user | 0 | User accounts | **Empty — auth users not syncing** |
| company | 2 | Client companies | Working |
| uploaded_file | 0 | File upload records | **Never populated** |
| column_map | 106 | Column mapping cache | Working (but mappings wrong) |
| reconciliation_run | 7 | Run tracking | Working |
| run_progress | 6 | Per-section progress | Working |
| tds_entry | 255 | Form 26 parsed entries | **Data quality: critical** |
| ledger_entry | 2,874 | Tally parsed entries | **Data quality: critical** |
| match_result | 0 | Match outcomes | **Never populated** |
| discrepancy_action | 0 | Compliance findings | **Never populated** |
| match_summary | 5 | Summary aggregates | Partial |
| match_type_registry | 0 | Match type catalog | **Never populated** |
| resolved_pattern | 0 | Learned patterns (pgvector) | **Never populated** |
| resolution_feedback | 1 | User feedback | 1 test row |

---

## 3. Functional Scope

### 3.1 Pipeline Flow

```
Upload XLSX files
    ↓
Parser (column_mapper + entry extraction)
    ↓
Matcher (6-pass matching engine)
    ↓
TDS Checker (5 compliance checks)
    ↓
Reporter (JSON + CSV + Excel reports)
```

### 3.2 Parser — Column Mapping + Entry Extraction

**Column Mapper (`app/services/column_mapper.py`):**
- Fuzzy keyword matching (SequenceMatcher) for 8 TDS fields + 5 ledger fields
- Confidence >= 0.8 → auto-map; < 0.8 → LLM fallback (Groq)
- Saved to DB for reuse per (company_id, file_type)

**Known Issues:**
- Column mapping produces wrong results: 55% of ledger entries have `party_name='None'`, some have numbers as names (e.g., "70168.0")
- All 255 TDS entries have `tds_amount=0`, `date_of_deduction=NULL`, `tax_rate=0`
- Root cause: `col_index` was being dropped from final mappings in a previous bug. Fix applied on production branch but column mapper still unreliable

### 3.3 Matcher — 6-Pass Matching Engine

| Pass | Method | Name Threshold | Amount Tolerance | Date Window | Confidence |
|------|--------|---------------|-----------------|-------------|-----------|
| 1 | Exact | 100% (identical) | 0% (exact) | ±3 days | 1.00 |
| 2 | GST-Adjusted | ≥50% | ±0.5% | ±90 days | 0.95 |
| 3 | Exempt Filter | N/A | <₹100 | N/A | N/A |
| 4 | Fuzzy | ≥40% | ±0.5% | ±30 days | 0.50–1.00 |
| 5 | Aggregated | ≥50% | ±0.5% | Month/Quarter/Cumulative | 0.70–0.90 |
| 6 | LLM-Assisted | ≥30% (candidate filter) | LLM decides | LLM decides | ≥0.60 |

**Pass 5 sub-strategies (in priority order):**
1. Monthly sum → 2. Cumulative to date → 3. Subset-sum (≤20 entries) → 4. All available → 5. Subset-sum all → 6. Quarterly sum

**Scope limitation:** Currently only matches sections **194A and 194C**. Sections 194H, 194I, 194J, 194Q are parsed but **not matched**.

### 3.4 TDS Checker — 5 Compliance Checks

| Check | Validates | Severity |
|-------|-----------|----------|
| Section Validation | Expense type matches TDS section | Error/Warning |
| Rate Validation | TDS rate matches statutory rate (tolerance <0.01%) | Error |
| Base Amount Validation | TDS on base amount, not GST-inclusive gross | Error |
| Threshold Validation | Aggregate annual amounts vs statutory thresholds | Info |
| Missing TDS Detection | Tally expenses without corresponding Form 26 entries | Error/Warning |

### 3.5 Reporter — Output Formats

- `reconciliation_summary.json` — Frontend-consumable summary
- `reconciliation_report.csv` — Flat match table
- `findings_report.csv` — Compliance findings
- `tds_recon_report.xlsx` — 4-sheet Excel workbook

### 3.6 Chat Agent

- LLM-driven conversational interface (Groq, tool-use loop)
- 6 tools: run_reconciliation, get_results_summary, get_match_details, get_findings, submit_review_decision, explain_finding
- In-memory session storage (per user_id dict)
- Streaming via SSE (POST /api/chat/stream)

### 3.7 Learning System

- Records human review decisions to `resolution_feedback`
- Extracts reusable patterns via LLM → stores in `resolved_pattern` with pgvector embedding
- Applied as "Pass 0" before matching on subsequent runs
- **Current state:** Placeholder. Pseudo-embeddings (SHA512 hash, not semantic). 0 patterns stored.

### 3.8 Knowledge Base

- Single JSON file: `app/knowledge/tds_rules.json` (v1.0.0)
- 19 TDS sections with rates, thresholds, entity types
- Penalty framework (201(1A), 234E, 271C, 271H, 276B)
- Due dates, forms, ambiguous expense classification
- Injected into every LLM prompt as verified context

---

## 4. Key Risks

### 4.1 CRITICAL — Data Quality

The database audit reveals the system **cannot produce correct reconciliation results**:

| Issue | Impact | Root Cause |
|-------|--------|-----------|
| TDS amount = 0 for 100% of entries | No TDS deduction data available for matching/checking | Parser column mapping reads wrong column for tds_amount |
| Date = NULL for 100% of TDS entries | Date-based matching (all 6 passes) cannot function | Parser fails to extract date column |
| Party name = 'None' for 55% of ledger entries | Over half of Tally entries cannot be name-matched | Column mapper maps wrong column as party_name |
| Party name = numeric value (e.g., "70168.0") | False entries pollute matching pool | Amount column read as name column |
| match_result table = 0 rows | No matches ever persisted to DB | Matcher `_matches_to_db_format()` may be failing silently |
| 6 of 15 tables completely empty | uploaded_file, app_user, discrepancy_action, match_type_registry, resolved_pattern never written to | Code paths to populate these tables are missing or broken |

### 4.2 CRITICAL — Security

| Issue | Severity | Location |
|-------|----------|----------|
| Reports endpoints have NO authentication | Critical | `app/api/reports.py` — all 3 endpoints unauthenticated |
| `/api/answer` has NO authentication | High | `app/api/reconciliation.py` — anyone can submit pipeline answers |
| JWT audience (aud) claim not verified | Medium | `app/auth/jwt.py` — `verify_aud: False` |
| Single hardcoded JWT public key | Medium | No key rotation mechanism |
| No rate limiting on any endpoint | Medium | All routers |
| In-memory chat sessions | Low | `app/api/chat.py` — breaks with multiple workers |

### 4.3 HIGH — Thread Safety

| Component | Issue | Consequence |
|-----------|-------|-------------|
| `events.py` — `_pending_answers` | Global mutable dict with no locks | Answer delivery race conditions under concurrent requests |
| `events.py` — question polling | `time.sleep(0.5)` in loop for 60 seconds | Blocks pipeline thread; wastes resources |
| `repository.py` | No connection pooling or thread synchronization | Concurrent DB writes from multiple agents may conflict |
| `llm_client.py` | Shared Groq client instance | Concurrent LLM calls may race on shared HTTP connection |

### 4.4 HIGH — Architectural Gaps

| Gap | Impact |
|-----|--------|
| **No error boundary in pipeline** — if parser fails, entire run fails with no partial recovery | Users see cryptic errors; no way to resume |
| **Matcher only handles 194A + 194C** — other sections parsed but silently ignored | Users see unmatched entries with no explanation |
| **No data validation after parsing** — 0 amounts, NULL dates, numeric names accepted silently | Bad data propagates through entire pipeline |
| **Reports use relative path** (`data/reports`) — depends on working directory | File-not-found in production deployments |
| **No request/response logging** — can't trace what happened after a failure | Debugging requires reproducing the issue |
| **Single-worker assumption** — in-memory sessions, global dicts, no message queue | Cannot scale horizontally |

### 4.5 MEDIUM — Performance

| Issue | Impact |
|-------|--------|
| N+1 queries in findings endpoint | Slow with large match result sets |
| No pagination on list endpoints | Memory issues with large datasets |
| Knowledge base rebuilt as string on every LLM call | Redundant string formatting |
| Subset-sum in Pass 5 uses greedy algorithm | May miss optimal matches that exhaustive search would find |
| No bulk insert chunking | Large Supabase payloads may be rejected |

---

## 5. External Dependencies

| Service | Purpose | Risk |
|---------|---------|------|
| **Supabase** (hosted) | PostgreSQL + Auth + RLS + Storage | Vendor lock-in; RLS complexity; no local dev fallback |
| **Groq API** (free tier) | LLM for column mapping, ambiguous matching, chat, remediation | Rate limits (30 req/min); free tier may be deprecated; no SLA |
| **Llama 3.3 70B** (via Groq) | Specific model dependency | Model updates may change behavior; no version pinning |

---

## 6. What Works vs What Doesn't

### Works
- FastAPI app structure with proper router separation
- Supabase Auth (JWT issuance, refresh, firm registration)
- File upload and storage (local)
- SSE streaming of pipeline events to frontend
- 6-pass matching algorithm (logic is sound, implementation has data quality issues)
- 5 compliance checks (section, rate, base amount, threshold, missing TDS)
- Report generation (JSON, CSV, Excel)
- Chat agent with tool-use loop (genuinely agentic)
- Knowledge base injection into LLM prompts
- Frontend: auth flow, file upload, event rendering, chat UI

### Doesn't Work
- Column mapping produces incorrect results → all downstream data is wrong
- 6 of 15 database tables never populated
- match_result never written (matcher results exist only in memory during run)
- No post-parse data validation
- Reports endpoints completely unauthenticated
- Learning system is placeholder (pseudo-embeddings, 0 patterns)
- Matcher ignores sections 194H, 194I, 194J, 194Q
- Chat session storage breaks with multiple workers

---

## 7. Recommendations for Tech Reviewer

### Immediate (Before any demo/pilot)
1. **Fix parser column mapping** — this is the #1 blocker. Every downstream result depends on correct parsing.
2. **Add data validation after parsing** — reject entries with NULL amounts or names; emit warning events.
3. **Add auth to reports endpoints** — currently anyone can access any run's data.
4. **Ensure match_result writes to DB** — verify `_matches_to_db_format()` works end-to-end.

### Short-term (Before production)
5. **Replace global `_pending_answers` with thread-safe mechanism** — use `threading.Event` or async queue.
6. **Add request logging** — every API call should be traceable.
7. **Add error handling to repository layer** — wrap Supabase calls with retry + timeout.
8. **Expand matcher to all TDS sections** — 194H, 194I, 194J, 194Q currently ignored.
9. **Add pagination to list endpoints** — prevent memory issues at scale.

### Medium-term (Production readiness)
10. **Move chat sessions to DB/Redis** — required for multi-worker deployment.
11. **Add CI/CD pipeline** — no automated testing exists.
12. **Implement real embeddings** in learning system — replace SHA512 pseudo-embeddings.
13. **Add monitoring/alerting** — no observability currently.
14. **Containerize** — no Dockerfile exists.

### Architecture Decisions Needed
15. **Agentic vs Deterministic orchestrator** — A new agentic orchestrator (LLM-in-a-loop) has been built on branch `claude/agentic-orchestrator` but is untested. Decide: ship the deterministic pipeline first, or invest in testing the agentic version?
16. **Column confirmation UX** — Should users confirm column mappings before pipeline runs? Endpoint exists (`/upload/map-columns`) but frontend doesn't use it.
17. **Groq dependency** — Free tier with rate limits. Plan for paid tier or switch to self-hosted model?

---

## 8. Repository & Branch Map

### Backend: `scaleupcfoai/aitdsrecon`

| Branch | Purpose | State |
|--------|---------|-------|
| `master` | Initial scaffold | Stale |
| `claude/prod-migration-Akcin` | Production backend (app/ structure) | Stable, tested |
| `claude/agentic-orchestrator` | New agentic orchestrator + all prod code | New, untested |
| `claude/continue-tds-frontend-i5SUW` | Old demo backend (tds-recon/ scripts, no DB) | Demo-ready |

### Frontend: `scaleupcfoai/aibookclose`

| Branch | Purpose | State |
|--------|---------|-------|
| `master` | Initial scaffold | Stale |
| `claude/continue-tds-frontend-JUkfj` | Demo frontend (fake thinking labels) | Demo-ready |
| `claude/real-agentic-ui` | Real LLM chat (no fake labels) | Working but rougher UX |

---

## 9. Appendix: Configuration Reference

```env
# Required
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJ...

# Required for backend operations (RLS bypass)
SUPABASE_SERVICE_ROLE_KEY=eyJ...

# Required for LLM features
GROQ_API_KEY=gsk_...

# Optional
LLM_MODEL=llama-3.3-70b-versatile    # Default
LLM_TEMPERATURE=0.1                   # Low = deterministic
LLM_MAX_TOKENS=2000                   # Per response
STORAGE_BACKEND=local                  # or "supabase"
LOCAL_STORAGE_PATH=data/uploads
CORS_ORIGINS=["http://localhost:5173"]
ENVIRONMENT=local                      # local | staging | production
```
