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
