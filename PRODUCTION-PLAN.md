# TDS Recon: 4-Week Production Migration Plan

## Context

Migrate TDS Recon from file-based MVP to production-ready app with Supabase, multi-tenancy, auth, and AWS deployment. The MVP (5 agents, SSE streaming, chat) is working — now making it production-grade.

**Confirmed Decisions:**
- **Repo:** New branch `prod/migration` on aitdsrecon (MVP is leverage)
- **Database:** Supabase (project: `acgfqezkvmttvoyuwdnb`, 15 tables, RLS enabled)
- **Frontend:** aibookclose repo (auth lives here — shared across all recon products)
- **Backend:** FastAPI (aitdsrecon) — only validates JWT, no auth management
- **pgvector:** From Day 2 (needed for learning agent pattern matching)
- **TDS Scope:** ALL sections under Income Tax Act (not just 194A + 194C)
- **Anthropic API:** Added at end, everything else functional first
- **Input Formats:** XLSX/CSV in any structure (expense ledger or Trial Balance). PDF deferred.
- **Team:** Ashish + Claude Code (mishr reviews occasionally)

---

## Cost Implications

| Resource | Cost | Notes |
|----------|------|-------|
| Supabase Free Tier | $0 | 500MB DB, 1GB storage, 50K auth users |
| Supabase Pro (if needed) | $25/month | If free tier exceeded |
| AWS ECS Fargate | ~$30-50/month | 0.5 vCPU, 1GB RAM |
| AWS ALB | ~$16/month | Required for HTTPS + WebSocket |
| Anthropic API | ~$50/month dev | $0.01-0.10 per chat message |
| GitHub Actions | Free | 2000 min/month (private repos) |
| Domain + SSL | ~$12/year | Route53 + ACM |
| **Total (dev phase)** | **~$50-100/month** | Mostly Anthropic API |

---

## Milestones

| Milestone | Weeks | Definition of Done |
|-----------|-------|--------------------|
| **M1: Local Prod-Grade** | 1-2 | Supabase DB, intelligent file parser (any format XLSX/CSV, expense ledger or Trial Balance), ALL TDS sections covered, run_id tracking, comprehensive tests, frontend works |
| **M2: Deployed Multi-Tenant** | 3-4 | AWS hosted, Supabase Auth (frontend), RLS, WebSocket chat, pgvector learning, CI/CD, full test suite |

---

## WEEK 1: Foundation + Intelligent Parser + Core Agents

### Day 1 (Mon) — Branch + Package + Config + pgvector (~3 hrs)
- Create branch `prod/migration`
- `pyproject.toml` with all deps (fastapi, supabase, asyncpg, python-jose, pytest, anthropic)
- `app/config.py` — Pydantic Settings
- `.env.example` with all env vars
- Verify pgvector extension enabled in Supabase (already in schema)
- **Verify:** Config imports, Supabase connection works, pgvector query succeeds
- **Tests:** `test_config.py` — settings load from .env, missing vars raise clear errors

### Day 2 (Tue) — Supabase Client + Models + Repository (~5 hrs)
- `app/db/client.py` — supabase-py + asyncpg pool
- `app/db/models.py` — 15 Pydantic models matching all tables
- `app/db/repository.py` — FirmRepo, CompanyRepo, RunRepo, EntryRepo, MatchRepo, LearningRepo
- **Verify:** Client connects, CRUD works, firm isolation works
- **Tests:** `test_db_repository.py`
  - Create firm → get firm
  - Create company → list by firm
  - Create run → update status
  - Bulk insert 50 entries → query by run_id
  - Firm A data invisible to Firm B query
  - Delete run → cascade deletes entries

### Day 3 (Wed) — Intelligent Column Mapper (any format XLS/CSV) (~6 hrs)
- `app/services/column_mapper.py` — reads any XLSX/CSV headers, identifies columns:
  - Rule-based first: known patterns ("Particulars" → party_name, "Gross Total" → amount)
  - Fuzzy matching: "Vendor Name" → party_name, "Tax Amt" → tds_amount
  - Fallback: present ambiguous columns to user for confirmation via `column_map` table
- Stores confirmed mappings in `column_map` table (reusable per company)
- Handles: Form 26 (any column order), Tally Journal/GST/Purchase (any sheet names), CSV files
- Input can be expense ledger OR complete Trial Balance — agent identifies TDS-relevant accounts and extracts only those
- PDF support deferred to post-launch phase
- **Verify:** Feed 3 different XLSX formats → correct column detection
- **Tests:** `test_column_mapper.py`
  - Known format (current HPC data) → auto-maps correctly
  - Renamed columns → fuzzy matches
  - Missing required column → clear error message
  - CSV input → correct parsing
  - Trial Balance input → TDS-relevant accounts extracted
  - Previously confirmed mapping → reused from DB

### Day 4 (Thu) — Parser Agent + Base Agent Class (~5 hrs)
- `app/agents/base.py` — AgentBase(run_id, firm_id, db, event_emitter)
- `app/pipeline/events.py` — EventEmitter scoped per run (not global singleton)
- `app/agents/parser_agent.py` — uses column_mapper, writes to ledger_entry + tds_entry
- **Verify:** Parse sample XLSX → entries in DB → counts match MVP
- **Tests:** `test_parser_agent.py`
  - Parse Form 26 → 85 tds_entry rows
  - Parse Tally → 716 JR + 222 GST + 626 PR ledger_entry rows
  - All entries have correct run_id and firm_id
  - Dates parsed correctly
  - PAN extracted from vendor name field
  - Empty/malformed rows skipped gracefully

### Day 5 (Fri) — Matcher Agent → DB + All TDS Sections (~7 hrs)
- `app/agents/matcher_agent.py` — ALL 5 passes preserved, reads from DB, writes to match_result
- `app/agents/utils.py` — shared helpers (normalize_name, name_similarity, amount_close)
- **Expand to ALL TDS sections** — Tally entry builders for each:
  - 194A (Interest), 194C (Contractor/Freight) — already in MVP
  - 194H (Commission/Brokerage), 194I(a/b) (Rent), 194J(a/b) (Technical/Professional)
  - 194Q (Purchase of Goods), 194O (E-commerce), 192 (Salary)
  - 194D/DA (Insurance), 194M (Individual/HUF payments), 195 (Non-resident)
- Section detection driven by expanded SECTION_EXPENSE_MAP (keyword → section)
- Document each pass's logic as a "prompt" for future LLM orchestration
- **Verify:** Full match run covers all sections present in data
- **Tests:** `test_matcher_logic.py`
  - pass1_exact: known pair → match, off-by-1-day → no match
  - pass2_gst: gross amount with 18% GST → base match
  - pass3_exempt: vendor with 15G → marked exempt
  - pass4_fuzzy: "INLAND WORLD PVT LTD" vs "Inland World" → match at >40% similarity
  - pass5_aggregated: 3 small entries summing to F26 amount → aggregated match
  - Section routing: freight → 194C, interest → 194A, professional → 194J(b), rent → 194I(b)
  - Regression: 194A+194C counts identical to MVP

---

## WEEK 2: Remaining Agents + API + Integration

### Day 6 (Mon) — TDS Checker Agent → DB + All Sections (~6 hrs)
- `app/agents/tds_checker_agent.py` — 5 checks, findings to discrepancy_action table
- **Expand rules engine to ALL sections:**
  - TDS_RATES: add rates for 194H (2%), 194I(a) (2%), 194I(b) (10%), 194J(a) (2%), 194J(b) (10%), 194Q (0.1%), 194O (1%), 192 (slab), 194D (5%), 194M (5%), 195 (varies)
  - TDS_THRESHOLDS: add limits for each section (194H ₹15K, 194I ₹2.4L, 194J ₹30K, 194Q ₹50L, etc.)
  - SECTION_EXPENSE_MAP: expand keywords for rent, insurance, e-commerce, salary, non-resident
- **Verify:** All section rates/thresholds match Income Tax Act provisions
- **Tests:** `test_tds_checker_logic.py`
  - check_section: freight → 194C OK, rent → 194I OK, professional → 194J(b) OK
  - check_rate: 194C company 2% → OK, 194H at 5% (old rate) → error
  - check_rate: 194I(b) individual 10% → OK
  - check_base_amount: TDS on GST-inclusive → error
  - check_thresholds: 194C below ₹1L → OK, 194J below ₹30K → OK, 194Q below ₹50L → OK
  - detect_missing_tds: vendor in Tally but not Form 26 → error
  - Each section's rate + threshold validated against IT Act
  - Each check returns correct severity and message

### Day 7 (Tue) — Reporter + Learning Agent → DB (~5 hrs)
- `app/agents/reporter_agent.py` — summary to match_summary, reports to storage
- `app/agents/learning_agent.py` — rules to resolved_pattern + resolution_feedback
  - pgvector embeddings stored for pattern similarity search
- **Verify:** Summary matches MVP, reports downloadable, rules persist
- **Tests:** `test_reporter_agent.py`, `test_learning_agent.py`
  - Summary KPIs match MVP reconciliation_summary.json
  - Excel has 3 sheets with correct row counts
  - Rule created → retrieved → applied on next run
  - Similar pattern found via pgvector similarity search

### Day 8 (Wed) — Orchestrator + File Storage (~4 hrs)
- `app/pipeline/orchestrator.py` — run_reconciliation with run_id, updates run_progress
- `app/services/file_storage.py` — Local/S3/Supabase Storage abstraction
- Errors per-agent caught, partial results preserved
- **Verify:** run_progress has 4 rows, reconciliation_run complete
- **Tests:** `test_pipeline_integration.py`
  - Full pipeline: upload → parse → match → check → report
  - Agent failure mid-pipeline → partial results saved
  - Re-run same data → new run_id, old run preserved

### Day 9 (Thu) — FastAPI App Shell (~5 hrs)
- `app/main.py` — app factory with routers
- `app/dependencies.py` — get_db, get_current_user (hardcoded for M1), get_file_storage
- Routers: upload.py, reconciliation.py, review.py, reports.py
- SSE streaming preserved
- **Verify:** uvicorn starts, all endpoints respond, frontend works
- **Tests:** `test_api_endpoints.py`
  - GET /api/status → 200
  - POST /api/upload → file stored + DB record
  - GET /api/run/stream → SSE events stream
  - GET /api/download/tds_recon_report.xlsx → valid file
  - POST /api/review → rule created

### Day 10 (Fri) — M1 Integration + Buffer (~4 hrs)
- Full E2E: fresh DB → upload → pipeline → results → download → review → re-run
- Fix all broken tests, hit 15+ tests passing
- Update CHANGELOG.md, PRODUCTION-PLAN.md progress
- **M1 Acceptance:**
  1. All data in Supabase PostgreSQL (zero JSON files)
  2. Intelligent column mapper handles any XLSX/CSV format
  3. Identical results to MVP (regression tests pass)
  4. SSE streaming works
  5. Reports downloadable
  6. 15+ tests passing

---

## WEEK 3: Auth (Frontend) + Multi-Tenancy + Chat

### Day 11 (Mon) — Supabase Auth in Frontend (~4 hrs)
- Add `@supabase/supabase-js` to aibookclose
- Create auth components: LoginPage, SignupPage, AuthProvider (React context)
- JWT stored in localStorage, attached to all API calls as Bearer token
- Shared auth across all recon products (TDS, Sales-Payment, future)
- **Verify:** Signup → login → JWT in headers → API responds
- **Tests:** Frontend: auth flow renders, token persisted. Backend: `test_api_auth.py` — no token=401, valid token=200

### Day 12 (Tue) — Backend JWT Verification + RLS (~5 hrs)
- `app/auth/jwt.py` — verify Supabase JWT, extract user_id + firm_id
- `app/auth/middleware.py` — require Bearer token on all routes except /health
- RLS: Supabase client passes JWT → RLS auto-applies
- For asyncpg: SET session variable for firm_id
- **Verify:** Firm A cannot see Firm B data
- **Tests:** `test_api_auth.py`
  - Missing token → 401
  - Expired token → 401
  - Valid token → 200 + correct firm_id extracted
  - Firm isolation: 2 firms, cross-query returns empty

### Day 13 (Wed) — User + Company Management (~4 hrs)
- `app/api/auth.py` — signup (creates firm + user), /me
- `app/api/company.py` — CRUD companies under firm
- Reconciliation endpoints scoped to company_id
- **Verify:** Create firm → create 2 companies → run for A → B has no data
- **Tests:** Company CRUD, firm ownership, reconciliation scoping

### Day 14 (Thu) — WebSocket Chat + Prompt Engineering (~6 hrs)
- `app/api/chat.py` — WebSocket endpoint
- `app/services/chat_service.py` — Anthropic SDK, same system prompt + tools
- Stream responses via WebSocket (replaces file polling)
- Persist conversation in DB
- **Verify:** WebSocket connects, Claude answers questions, tools work
- **Tests:** `test_chat_service.py`
  - System prompt includes correct TDS knowledge
  - Tool definitions match available agents
  - Tool execution returns correct data
  - Conversation history persists across reconnects

### Day 15 (Fri) — Frontend Auth Integration + Polish (~4 hrs)
- Protected routes in aibookclose (redirect to login if no JWT)
- Company selector in UI
- API calls include company_id
- **Verify:** Full flow: login → select company → upload → run → chat → logout

---

## WEEK 4: Deployment + AI + Security

### Day 16 (Mon) — Docker + docker-compose (~3 hrs)
- Dockerfile, docker-compose.yml
- **Verify:** `docker-compose up` → full stack runs

### Day 17 (Tue) — AWS Infrastructure (~5 hrs)
- ECR, ECS Fargate, ALB (HTTPS + WebSocket), Secrets Manager
- Schema on production Supabase
- **Verify:** ECS starts, ALB health passes, curl returns 200

### Day 18 (Wed) — CI/CD + pgvector Learning (~5 hrs)
- GitHub Actions: test → build → push ECR → update ECS
- Implement embedding generation for resolved_pattern
- Similarity search: "this vendor pattern looks like a previous resolution"
- **Verify:** Push triggers deploy, pattern search returns similar resolutions

### Day 19 (Thu) — Anthropic API + Full E2E (~5 hrs)
- Enable ANTHROPIC_API_KEY in production
- Rate limiting on chat endpoint
- Full E2E on deployed: signup → company → upload → run → chat → review → re-run
- **Verify:** All steps pass on deployed environment

### Day 20 (Fri) — Security + Monitoring + Docs (~4 hrs)
- CORS locked, rate limiting, file size limits, audit logging
- CloudWatch, health check, error tracking
- Update all docs: CLAUDE.md, CHANGELOG.md (v3.0.0), DEV-SETUP.md
- Final PRODUCTION-PLAN.md progress report
- **M2 Acceptance:**
  1. AWS hosted, HTTPS
  2. Multi-tenant with Supabase Auth (frontend) + JWT verification (backend)
  3. RLS isolates firms
  4. WebSocket chat with Anthropic API
  5. pgvector pattern learning
  6. CI/CD deploys on push
  7. 25+ tests passing
  8. Audit logging on mutations

---

## Time Estimates

| Day | Work | Hours |
|-----|------|-------|
| 1 | Package, config, pgvector setup | 3 |
| 2 | DB client, models, repository + tests | 5 |
| 3 | Intelligent column mapper + tests | 6 |
| 4 | Parser agent + base class + tests | 5 |
| 5 | Matcher agent + ALL sections + tests | 7 |
| 6 | TDS Checker + ALL section rates/thresholds + tests | 6 |
| 7 | Reporter + Learning + pgvector + tests | 5 |
| 8 | Orchestrator + file storage + tests | 4 |
| 9 | FastAPI shell + endpoint tests | 5 |
| 10 | M1 integration + buffer | 4 |
| 11 | Frontend auth (Supabase JS) | 4 |
| 12 | Backend JWT + RLS + tests | 5 |
| 13 | User + Company management | 4 |
| 14 | WebSocket chat + prompt tests | 6 |
| 15 | Frontend auth integration | 4 |
| 16 | Docker | 3 |
| 17 | AWS infrastructure | 5 |
| 18 | CI/CD + pgvector learning | 5 |
| 19 | Anthropic API + E2E | 5 |
| 20 | Security + docs | 4 |
| **Total** | | **~95 hrs** |

---

## Comprehensive Test Strategy

### P0 — Core Business Logic (must never break)
| Test File | Cases | What Breaks If Wrong |
|-----------|-------|---------------------|
| `test_matcher_logic.py` | 15+ cases | Wrong matches, missed matches, double-counting |
| `test_tds_checker_logic.py` | 12+ cases | Wrong compliance findings, missed violations |
| `test_parser_agent.py` | 10+ cases | Data corruption, missing entries |
| `test_column_mapper.py` | 10+ cases | Can't process new client's files |

### P1 — Infrastructure
| Test File | Cases | What Breaks If Wrong |
|-----------|-------|---------------------|
| `test_db_repository.py` | 10+ cases | Data loss, wrong queries, leaking between firms |
| `test_api_endpoints.py` | 8+ cases | API errors, upload failures, download broken |
| `test_api_auth.py` | 8+ cases | Unauthorized access, auth bypass |
| `test_pipeline_integration.py` | 5+ cases | Pipeline hangs, partial results lost |

### P2 — Services
| Test File | Cases | What Breaks If Wrong |
|-----------|-------|---------------------|
| `test_chat_service.py` | 6+ cases | Chat doesn't work, tools fail |
| `test_file_storage.py` | 4+ cases | Upload/download broken |
| `test_learning_agent.py` | 5+ cases | Rules not applied, patterns not found |

**Total: 90+ test cases across 11 test files**

---

## Handoff Prompt System

**Location:** `PRODUCTION-PLAN.md` in repo root (committed after each day)

**Structure:**
```
# Production Plan Progress

## Current Status
- Day: [N] of 20
- Milestone: [M1/M2]
- Last completed: [summary]
- Next: [Day N+1 deliverables]
- Blockers: [any]

## What's Working
- [list of functional components]

## What's Not Working Yet
- [list of pending items]

## How to Start Next Session
> Read CLAUDE.md, CHANGELOG.md, PRODUCTION-PLAN.md.
> Today is Day [N+1]. Deliverables: [list from plan].
> Start by reading [specific files]. Run tests after each change.
```

Updated at end of each day's work, committed and pushed.

---

## Scope Trimming (If Behind)

Cut in this order:
1. Day 15 (Company mgmt) — hardcode single company
2. Day 18 (CI/CD) — manual deploy
3. Day 14 (WebSocket) — keep file polling
4. Day 20 (Security) — minimum CORS + file limits

**Never cut:** Days 1-5 (foundation), Days 11-12 (auth/RLS), Days 16-17 (Docker/AWS)

---

## Schema Reference

15 tables in Supabase (project: acgfqezkvmttvoyuwdnb, all RLS enabled):
- **Layer 1:** ca_firm, app_user
- **Layer 2:** company
- **Layer 3:** uploaded_file, column_map
- **Layer 4:** reconciliation_run, run_progress
- **Layer 5:** ledger_entry, tds_entry
- **Layer 6:** match_result, discrepancy_action, match_summary
- **Layer 7:** match_type_registry, resolved_pattern (pgvector), resolution_feedback (pgvector)

## TDS Sections Covered (All under Income Tax Act)

| Section | Nature of Payment | Rate (Ind/HUF) | Rate (Company) | Threshold |
|---------|------------------|-----------------|----------------|-----------|
| 192 | Salary | Slab rates | N/A | Basic exemption |
| 194A | Interest (other than securities) | 10% | 10% | ₹5,000/yr |
| 194C | Contractor/Sub-contractor | 1% | 2% | ₹30K single / ₹1L annual |
| 194D | Insurance commission | 5% | 5% | ₹15,000/yr |
| 194DA | Life insurance maturity | 5% | 5% | ₹1,00,000 |
| 194H | Commission/Brokerage | 2% | 2% | ₹15,000/yr |
| 194I(a) | Rent - Plant/Machinery | 2% | 2% | ₹2,40,000/yr |
| 194I(b) | Rent - Land/Building | 10% | 10% | ₹2,40,000/yr |
| 194J(a) | Technical services | 2% | 2% | ₹30,000/yr |
| 194J(b) | Professional/Consultancy | 10% | 10% | ₹30,000/yr |
| 194K | Mutual fund units | 10% | 10% | ₹5,000 |
| 194LA | Immovable property compensation | 10% | 10% | ₹2,50,000 |
| 194M | Payments by individual/HUF | 5% | N/A | ₹50,00,000/yr |
| 194N | Cash withdrawal | 2% | 2% | ₹1 Cr |
| 194O | E-commerce operator | 1% | 1% | ₹5,00,000 |
| 194Q | Purchase of goods | 0.1% | 0.1% | ₹50,00,000/yr |
| 195 | Non-resident payments | Varies | Varies | No threshold |

MVP covers 194A + 194C. Production covers ALL sections above.

---

## Critical MVP Files to Preserve

- `agents/matcher_agent.py` — 5-pass matching engine (core IP)
- `agents/tds_checker_agent.py` — TDS rules engine (rates, thresholds, sections)
- `chat_bridge.py` — system prompt, tool definitions, agentic loop pattern
- `reconcile.py` — pipeline orchestration pattern
