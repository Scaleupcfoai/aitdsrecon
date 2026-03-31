# Lekha AI — TDS Recon Production Migration

## Learning Log & Progress Report

---

## Day 1 — Branch + Package Structure + Config

**Date:** 2026-03-28
**Branch:** `claude/prod-migration-Akcin`
**Hours:** ~3

### What was built
| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata + dependencies (replaces requirements.txt) |
| `app/config.py` | Pydantic Settings — all config from .env, type-safe |
| `.env.example` | Template for new devs (no secrets) |
| `.env` | Real Supabase credentials (gitignored) |
| `.gitignore` | Updated for Python + secrets |
| `app/` package dirs | Empty `__init__.py` for auth, db, api, agents, pipeline, services |

### What I learned

**1. pyproject.toml > requirements.txt**
- One file for project name, version, Python version, all dependencies
- `pip install -e ".[dev]"` = editable install + test tools (for development)
- `pip install .` = frozen install, production deps only (for Docker/AWS)
- `-e` means "editable" — code changes reflect immediately without reinstalling
- `[dev]` includes pytest etc. — not installed in production

**2. Pydantic Settings**
- Type-safe config loaded from `.env` file or environment variables
- If a required variable is missing, app crashes on startup with clear error (fail-fast)
- `self` in Python = `this` in C++
- One `settings` object imported everywhere: `from app.config import settings`
- Production uses env vars (no .env file), local uses .env — same code reads both

**3. .env + .env.example pattern**
- `.env` has real secrets → gitignored, never committed
- `.env.example` has placeholder values → committed, template for new devs
- New dev: `copy .env.example .env` then fills in real values

### Verification
- `python -c "from app.config import Settings"` → imports OK
- Supabase: 15 tables exist, pgvector 0.8.0 enabled (verified via MCP)

---

## Day 2 — Supabase Client + Models + Repository + Tests

**Date:** 2026-03-28
**Hours:** ~5

### What was built
| File | Purpose |
|------|---------|
| `app/db/client.py` | Supabase connections — `get_client()` (anon) + `get_admin_client()` (service_role) |
| `app/db/models.py` | 15 Pydantic models matching all database tables |
| `app/db/repository.py` | Repository class with 13 sub-repositories for all CRUD operations |
| `tests/test_db_repository.py` | 13 tests — connection, firm, company, run, entries, matches, progress |

### What I learned

**1. Python classes and constructors**
- `__init__` = constructor (like C++ constructor)
- `self.x = y` stores data on the object (`this->x = y` in C++)
- `self` in Python = `this` in C++ (explicit in Python, implicit in C++)
- No `new` keyword — just call the class: `repo = Repository()` (vs `new Repository()` in C++)
- Python uses `.` for everything, C++ uses `->` for pointers

**2. Repository pattern**
- One class per table group (FirmRepository, EntryRepository, etc.)
- One master `Repository` class creates all sub-repos with the same DB connection
- All database calls go through repository — never scattered in agent code
- Change query logic in one place, not 20 files
- Like a "library of database operations"

**3. Bulk insert vs one-by-one**
- One-by-one: 50 entries = 50 round trips to database (~2.75 seconds)
- Bulk: 50 entries = 1 round trip (~0.07 seconds) — 40x faster
- Database parses SQL once, writes all rows in one transaction
- In Supabase: pass a list of dicts instead of one dict: `client.table("x").insert([...]).execute()`

**4. RLS (Row Level Security)**
- Every table has RLS enabled — data is isolated per firm
- `anon` key = guest, RLS blocks inserts/reads without JWT user context
- `service_role` key = admin master key, bypasses all RLS
- Tests use service_role (need to insert test data freely)
- Production API uses anon + user JWT (RLS filters by firm automatically)
- Found service_role key in: Supabase Dashboard → Settings → API

**5. Pydantic models**
- Like MongoDB schema — defines what a database row looks like in Python
- Converts raw dict from DB to typed Python object with validation
- `CaFirm(**raw_data)` → validated object with autocomplete
- `to_insert_dict()` strips empty IDs and None values before insert (let DB use defaults)

**6. pytest and testing**
- Any function starting with `test_` is a test
- `assert x == y` — if true, passes silently; if false, shows what went wrong
- `@pytest.fixture` with `yield` = setup + cleanup pattern:
  - Before yield = ARRANGE (create test data in real DB)
  - yield = hand data to test function
  - After yield = CLEANUP (delete test data)
- Arrange-Act-Assert pattern: fixture does Arrange + Cleanup, test does Act + Assert
- Fixture dependencies chain: test_run needs test_company needs test_firm needs repo
- These are integration tests (real DB) — unit tests with mocking added later

**7. @lru_cache()**
- Decorator that makes a function return the cached result after first call
- `get_client()` creates the Supabase connection once, returns same object forever
- Like a singleton pattern but simpler

### Verification
- 13/13 tests passing on local machine against real Supabase
- All tables accessible via service_role key
- Cleanup works — tables empty after tests

### Issues encountered
- RLS blocked all inserts with anon key → fixed by adding `get_admin_client()` with service_role key
- Proxy in cloud environment blocks HTTP to Supabase → verified via MCP tools instead, Python tests run locally

---

## Day 3 — (Upcoming)

**Plan:** Intelligent Column Mapper — reads any XLSX/CSV format, identifies columns, extracts TDS-relevant data from Trial Balance or Expense Ledger.

---

## Architecture Notes

### Repository structure
```
aitdsrecon/                    ← repo root
├── app/                       ← PRODUCTION CODE
│   ├── config.py              ← Settings from .env
│   ├── db/
│   │   ├── client.py          ← Supabase connection
│   │   ├── models.py          ← 15 Pydantic models
│   │   └── repository.py      ← All CRUD operations
│   ├── auth/                  ← (Week 3)
│   ├── api/                   ← (Day 9)
│   ├── agents/                ← (Day 4-7)
│   ├── pipeline/              ← (Day 7-8)
│   └── services/              ← (Day 8)
├── tests/                     ← Test files
├── tds-recon/                 ← MVP (reference, delete after migration)
├── pyproject.toml             ← Dependencies
├── .env.example               ← Config template
└── PRODUCTION-PLAN.md         ← Day-by-day plan
```

### Key concepts index
| Concept | Day learned | One-line summary |
|---------|------------|------------------|
| pyproject.toml | Day 1 | Modern Python packaging — replaces requirements.txt |
| Pydantic Settings | Day 1 | Type-safe config from .env, fail-fast on missing vars |
| .env pattern | Day 1 | Secrets local (gitignored), template committed |
| Python __init__ | Day 2 | Constructor — `self` = `this` in C++ |
| Repository pattern | Day 2 | Centralize all DB queries in one place |
| Bulk insert | Day 2 | Pass list to DB = 1 call, not N calls |
| RLS | Day 2 | Row-level security filters data per firm |
| pytest fixtures | Day 2 | Setup before yield, cleanup after yield |
| @lru_cache | Day 2 | Function returns cached result after first call |
| LLM Client pattern | Day 1R | Unified interface, swap provider in one place |
| Prompt templates | Day 1R | Version-controlled prompts, {placeholders} filled at runtime |
| SSE event emission | Day 1R | Every LLM call emits event → UI shows "thinking" |
| Graceful fallback | Day 1R | LLM returns None on failure → agent uses deterministic result |
| Approach 1 (column mapping) | Day 2R | confidence >= 0.8 auto-map, < 0.8 send to LLM only |
| Dynamic parser | Day 2R | Column mapper output drives parser — zero hardcoded positions |
| Expense classification | Day 2R | Keyword-based → TDS section mapping (freight→194C, etc.) |

---

## Day 1 (Rework) — LLM Client + Prompt Templates

**Date:** 2026-03-29
**Hours:** ~5

### What was built
| File | Purpose |
|------|---------|
| `app/services/llm_client.py` | Unified LLM client — all agents call `self.llm.complete()` |
| `app/services/llm_prompts.py` | 14 prompt templates for all 7 agents |
| `tests/test_llm_client.py` | 5 tests (availability, complete, JSON, fallback, events) |

### What I learned

**1. LLM Client as a single interface**
- All 7 agents use the same `LLMClient` class
- Currently uses Groq (free). Swap to Anthropic = change one line in config
- Every LLM call emits an SSE event: `llm_call` (starting) and `llm_response` (done)
- If LLM fails → returns `None` → agent falls back to deterministic logic (never crashes)
- JSON mode: `complete_json()` requests structured output, parses it, handles malformed JSON

**2. Prompt engineering as version-controlled templates**
- Each agent has a SYSTEM prompt (who it is) and a USER prompt (what to do)
- Templates use `{placeholders}` filled at runtime with actual data
- All prompts in one file → change a prompt, all agents update
- Example: `MATCHER_AMBIGUOUS_PROMPT` includes Form 26 entry + candidate Tally entries + asks LLM to reason about the match

**3. AgentBase now has LLM**
- `self.llm` available in every agent automatically
- Agents don't import Groq directly — they use the abstraction

---

## Day 2 (Rework) — Column Mapper Approach 1 + Dynamic Parser

**Date:** 2026-03-29
**Hours:** ~6

### What was built
| File | Purpose |
|------|---------|
| `app/services/column_mapper.py` | REWRITTEN — Approach 1 (no cross-verify) |
| `app/agents/parser_agent.py` | REWRITTEN — fully dynamic, zero hardcoded positions |
| `tests/test_column_mapper.py` | REWRITTEN — Approach 1 tests |

### What I learned

**1. Approach 1 vs Approach 2 (column mapping)**
- Approach 2 (old): fuzzy → send ALL to LLM → cross-verify fuzzy vs LLM → flag disagreements
- Approach 1 (new): fuzzy → if >= 0.8 auto-map (done) → if < 0.8 send ONLY uncertain to LLM → done
- Simpler, cheaper, faster. Cross-verify adds complexity we don't need yet.
- We'll add cross-verify later IF accuracy needs it (data-driven decision, not premature)

**2. Why hardcoded column positions are bad**
- Old parser: `row[1].value` = name, `row[3].value` = amount. Works for ONE specific file format.
- New client has columns in different order? Parser breaks.
- Dynamic parser: column mapper tells us "party_name is column 5" → parser reads column 5
- Same parser works for ANY client's file format. Zero code changes needed per client.

**3. How the dynamic parser works**
```
Column mapper: "Name" → party_name (col B), "Section" → tds_section (col C), ...
                     ↓
field_to_col = {"party_name": 1, "tds_section": 2, "gross_amount": 3, ...}
                     ↓
For each row: values["party_name"] = row[field_to_col["party_name"]].value
```
No `row[1]`, no `row[3]`. Only `values["party_name"]`, `values["gross_amount"]`.

**4. Tally 2D registers — unmapped columns as data**
- Tally's Journal Register has 68 columns. Only 5 are meta (Date, Particulars, Voucher, Value, Total).
- The other 63 are expense account heads (Interest Paid, Freight Charges, etc.)
- Column mapper maps the 5 meta columns. Parser collects the other 63 as `expense_heads` dict.
- Each expense head is classified (freight→194C, brokerage→194H) for section assignment.

**5. Expense classification chain**
```
Column name "Freight Charges_18%"
    → classify_expense() → "freight_expense" (keyword match)
    → EXPENSE_TO_SECTION → "194C"
    → Stored in ledger_entry.tds_section
    → Matcher uses this to match against Form 26 194C entries
```

### Issues resolved
- Parser was using hardcoded `row[1]`, `row[3]` etc. — completely replaced with dynamic field lookup
- Column mapper was doing unnecessary cross-verification — simplified to Approach 1

---

## Day 3R — Matcher Pass 6 (LLM-Assisted Matching)

**Hours:** ~6

### What was built
| File | Purpose |
|------|---------|
| `app/agents/matcher_agent.py` | Added Pass 6 — LLM resolves ambiguous matches |
| `tests/test_matcher_llm.py` | 7 tests with MockLLMClient |

### What I learned
- **Pass 6 is a fallback, not a replacement.** Deterministic passes (1-5) run first. Only unmatched entries go to LLM. This saves API cost — most entries match without LLM.
- **MockLLMClient pattern:** Create a mock that returns predefined responses. Test the logic without real API calls. All tests run in <1 second.
- **Confidence threshold:** LLM confidence >= 0.6 → auto-match. < 0.6 → flag for human. The threshold is a design choice, not a technical one.
- **Event types:** `llm_insight` (match confirmed), `human_needed` (unsure). Frontend renders these differently.

---

## Day 4 — TDS Checker LLM (Section + Remediation)

**Hours:** ~5

### What was built
- `app/agents/tds_checker_agent.py` — LLM section classification + remediation writing
- `tests/test_checker_llm.py` — 7 tests

### What I learned
- **Ambiguous expenses:** "Advertisement" can be 194C (works contract) or 194J(b) (professional). Deterministic rules can't decide — LLM looks at vendor name + expense context to classify.
- **Remediation writing:** LLM writes CA-level advice: what's wrong, why it matters, action steps, deadline, penalty risk. Not template text — specific to each vendor and amount.
- **Discrepancy actions in DB:** Findings now stored in `discrepancy_action` table with `llm_reasoning` and `proposed_action`.

---

## Day 5 — Reporter LLM (Narrative Summaries)

**Hours:** ~5

### What was built
- `app/agents/reporter_agent.py` — LLM narrative generation
- `tests/test_reporter_llm.py` — 4 tests

### What I learned
- **LLM narratives vs templates:** Instead of "3 errors, 5 warnings", LLM writes: "We found 3 vendors where TDS was not deducted — Kamal Kishor (Rs 16,845 brokerage)..." with specific vendor names, amounts, sections.
- **Excel with narrative:** New "Executive Summary" sheet in the Excel report with the LLM-generated narrative.
- **Graceful fallback:** LLM fails → reports still generate with all data (CSV, Excel, JSON). Just no narrative text.

---

## Day 5.5 — TDS Knowledge Base

**Hours:** ~4

### What was built
| File | Purpose |
|------|---------|
| `app/knowledge/tds_rules.json` | 16 TDS sections, rates, thresholds, penalties, due dates, forms |
| `app/knowledge/__init__.py` | Loader — get_section_rate(), get_threshold(), get_llm_context() |

### What I learned
- **BLACK BOX RISK:** LLMs trained on data that may be outdated. Budget 2025 changed 194H from 5% to 2%. LLM might still say 5%. Unacceptable for a financial product.
- **Solution: Knowledge Base + LLM as reasoning engine.** We maintain verified rules in `tds_rules.json`. Every LLM prompt includes: "Use ONLY these rules. Do NOT use training data." LLM reasons on controlled data, not unknown training data.
- **Single source of truth:** Budget changes? Update one JSON file. All 7 agents, all 14 prompts update automatically.
- **78 keyword→section mappings** auto-generated from knowledge base. No hardcoded Python dicts anywhere.

---

## Day 6 — Learning Agent (pgvector + Patterns)

**Hours:** ~7

### What was built
- `app/agents/learning_agent.py` — record decisions, extract patterns, pgvector similarity
- `tests/test_learning_agent.py` — 9 tests

### What I learned
- **pgvector:** PostgreSQL extension for storing vector embeddings. When user marks "Xpress Cargo" as below threshold, we store the pattern as a 1536-dimension vector. Later, when "VRL Logistics" appears, pgvector finds the similar pattern.
- **HNSW index:** Hierarchical Navigable Small World — fast approximate nearest neighbor search. Already created in Supabase schema.
- **Pseudo-embeddings:** Real embeddings need an API call (OpenAI/Anthropic). For now, using hash-based pseudo-embeddings as placeholder. Same infrastructure, swap later.
- **Pass 0:** Learning Agent runs BEFORE Matcher. Applies learned rules (below_threshold, ignore) to mark entries before matching starts.

---

## Day 7 — Chat Agent (100% LLM + Tools)

**Hours:** ~6

### What was built
- `app/agents/chat_agent.py` — agentic loop with 6 tools
- `tests/test_chat_agent.py` — 10 tests

### What I learned
- **Agentic loop:** User message → LLM → LLM calls tool → execute tool → feed result back → LLM responds. This loop repeats until LLM gives a final text response (no more tool calls).
- **Tool calling:** LLM decides WHICH tool to call based on user's message. "Why is Anderson flagged?" → LLM calls `explain_finding("Anderson")`. "Run reconciliation" → LLM calls `run_reconciliation()`.
- **System prompt = personality + knowledge.** 6,532 chars including TDS knowledge base. The LLM IS a knowledgeable CA who can also run agents.
- **Streaming:** `chat_stream()` yields tokens + tool call status. UI shows "🔧 Calling get_findings..." between response chunks.

---

## Day 8 — Orchestrator (All Agents Wired)

**Hours:** ~5

### What was built
- `app/pipeline/orchestrator.py` — rewritten with LLM client, error handling, Learning Pass 0

### What I learned
- **Error isolation:** Each agent runs in its own try/catch. Parser fails → full stop (no data). Matcher fails → Checker + Reporter still run with partial data. No single agent can crash the entire pipeline.
- **Shared LLM client:** One `LLMClient` instance shared across all agents in a run. Events scoped to run_id.
- **Status tracking:** `reconciliation_run` table tracks: processing_status (parsing → matching → checking → reporting → done), current_section. UI can poll this.

---

## Day 9 — FastAPI App (22 Endpoints)

**Hours:** ~7

### What was built
- `app/main.py` — app factory
- 6 routers: upload, reconciliation, reports, chat, company, auth
- `app/dependencies.py` — get_db, get_llm, get_current_user

### What I learned
- **Dependency injection:** `Depends(get_db)` in route signature → FastAPI creates Repository and passes it. No global state. Each request gets its own dependencies.
- **SSE endpoint pattern:** Start pipeline in background thread → push events to queue → yield from queue as SSE data → frontend receives in real-time.
- **App factory:** `create_app()` returns configured FastAPI instance. Can create multiple instances for testing with different configs.

---

## Day 10 — SSE Event Types

**Hours:** ~2

### What I learned
- **12 event types** — each rendered differently in the UI: agent_start (spinner), agent_done (checkmark), llm_call (💭), llm_insight (prominent), human_needed (action button).
- **The "Claude Code" feel:** Every LLM call is visible to the user. They see "Parser asking LLM to classify 3 columns..." then "LLM mapped: 'Amt Paid' → gross_amount". Transparency builds trust.

---

## Day 11 — Auth (Supabase JWT)

**Hours:** ~6

### What was built
- `app/auth/jwt.py` — verify_token()
- `app/auth/dependencies.py` — UserContext dataclass, get_current_user
- `tests/test_auth.py` — 8 tests

### What I learned
- **JWT verification:** Supabase signs tokens with a secret. Backend decodes and extracts user_id, email, firm_id. 401 if invalid/expired.
- **Local dev fallback:** No auth header in local env → returns placeholder user. No friction during development.
- **UserContext dataclass:** Type-safe user info throughout the app. `user.firm_id` not `user["firm_id"]`.

---

## Days 12-13 — Integration + Logic Tests

**Hours:** ~11

### What was built
- `tests/conftest.py` — shared fixtures (MockLLMClient, EventEmitter, TestClient, repo)
- `tests/test_api_endpoints.py` — 11 API tests
- `tests/test_integration.py` — full E2E pipeline test
- `tests/test_matcher_logic.py` — 28 pure logic tests
- `tests/test_checker_logic.py` — 21 pure logic tests

### What I learned
- **Test layers:** Unit (no DB, no LLM) → Service (mock LLM) → Agent (mock LLM + real DB) → Integration (everything). Each layer catches different bugs.
- **conftest.py:** Shared fixtures imported automatically by pytest. Write once, use in every test file.
- **Golden reference testing:** Same input XLSX → same match counts as MVP. If numbers change, something broke.

---

## Day 14 — Edge Cases (61 Tests)

**Hours:** ~5

### What was built
- `tests/test_edge_cases.py` — 61 edge case tests across all layers

### What I learned
- **Financial edge cases are critical:** `safe_float("1,00,000")` must return 100000, not crash. Indian number format uses commas differently.
- **Every None path must be handled.** Parser gets None date? Return None, not crash. LLM returns empty string? Return None, not crash. PAN has 3 characters? Return "unknown", not crash.
- **LLM JSON is unreliable.** LLM might wrap in markdown, return array instead of object, or put confidence as string "0.85" instead of float 0.85. Handle all cases.

---

## Architecture Notes (Updated)

### Full file structure (Day 15)
```
aitdsrecon/
├── app/
│   ├── config.py              ← Settings from .env
│   ├── main.py                ← FastAPI app (22 endpoints)
│   ├── dependencies.py        ← DI: get_db, get_llm, get_current_user
│   ├── auth/
│   │   ├── jwt.py             ← Supabase JWT verification
│   │   └── dependencies.py    ← UserContext, get_current_user
│   ├── db/
│   │   ├── client.py          ← Supabase connection (anon + admin)
│   │   ├── models.py          ← 15 Pydantic models
│   │   └── repository.py      ← 13 sub-repositories
│   ├── knowledge/
│   │   ├── tds_rules.json     ← Single source of truth (16 sections)
│   │   └── __init__.py        ← Loader + LLM context generator
│   ├── agents/
│   │   ├── base.py            ← AgentBase (run_id, db, events, llm)
│   │   ├── utils.py           ← normalize_name, name_similarity, etc.
│   │   ├── parser_agent.py    ← Dynamic parser (column mapper driven)
│   │   ├── matcher_agent.py   ← 6-pass engine (5 deterministic + 1 LLM)
│   │   ├── tds_checker_agent.py ← 5 checks + LLM section/remediation
│   │   ├── reporter_agent.py  ← Reports + LLM narratives
│   │   ├── learning_agent.py  ← Patterns + pgvector + Pass 0
│   │   └── chat_agent.py      ← 100% LLM with 6 tools
│   ├── pipeline/
│   │   ├── events.py          ← EventEmitter (12 types, SSE callback)
│   │   └── orchestrator.py    ← Wires all 7 agents
│   ├── services/
│   │   ├── llm_client.py      ← Unified LLM (Groq→Anthropic swap)
│   │   ├── llm_prompts.py     ← 14 prompt templates
│   │   └── column_mapper.py   ← Approach 1 (fuzzy + LLM for <0.8)
│   └── api/
│       ├── upload.py, reconciliation.py, reports.py
│       ├── chat.py, company.py, auth.py
│       └── (22 endpoints total)
├── tests/                     ← 182 tests across 12 files
├── tds-recon/                 ← MVP reference (will be removed)
└── pyproject.toml, .env.example, PRODUCTION-PLAN.md
```

### Key concepts index (complete)
| Concept | Day | One-line summary |
|---------|-----|------------------|
| pyproject.toml | 1 | Modern Python packaging |
| Pydantic Settings | 1 | Type-safe config from .env |
| Repository pattern | 2 | Centralize all DB queries |
| Bulk insert | 2 | 1 API call for N rows |
| RLS | 2 | Row-level security per firm |
| pytest fixtures | 2 | Setup before yield, cleanup after |
| Approach 1 (column mapping) | 2R | >=0.8 auto-map, <0.8 → LLM |
| Dynamic parser | 2R | Column mapper drives parser |
| MockLLMClient | 3R | Test LLM logic without API calls |
| LLM confidence threshold | 3R | >=0.6 auto-match, <0.6 flag human |
| Discrepancy actions | 4 | Findings stored with LLM reasoning |
| LLM narratives | 5 | Professional summaries, not templates |
| Knowledge base | 5.5 | Verified rules, not training data |
| Black box risk | 5.5 | LLM reasons on controlled data only |
| pgvector | 6 | Vector similarity for pattern matching |
| Agentic loop | 7 | LLM → tool → result → LLM → respond |
| Tool calling | 7 | LLM decides which function to call |
| Error isolation | 8 | Per-agent try/catch, partial results |
| Dependency injection | 9 | Depends() in route signatures |
| SSE streaming | 10 | Server→browser one-way event pipe |
| JWT verification | 11 | Token → user_id + firm_id |
| conftest.py | 12 | Shared fixtures auto-imported |
| Edge cases | 14 | Every None/empty/invalid path handled |

---

## Day 3 (Rework) — (Upcoming)

**Plan:** Matcher Agent Pass 6 — LLM-assisted matching for ambiguous cases that deterministic passes can't resolve.
