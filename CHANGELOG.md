# CHANGELOG — Lekha AI (TDS Reconciliation + Payment Recon)

> This file is Claude Code's "memory" across sessions. Read it at the start. Update it at the end.

## Current State

- **Version:** 3.0.0
- **Status:** Production-grade 7-agent LLM architecture. Supabase DB, auth, knowledge base, 182 tests. Deployment + frontend auth UI pending (Phase 2).
- **Last session:** 2026-03-29
- **Next priority:** Phase 2 — AWS deployment, frontend auth UI, real embeddings, security hardening

## Version History

### 3.0.0 — Production Architecture (7-Agent LLM System) (2026-03-29)

**Architecture:**
- 7 LLM-powered agents: Parser, Matcher (6 passes), TDS Checker, Reporter, Learning (pgvector), Chat (6 tools), Orchestrator
- Knowledge Base: tds_rules.json — 16 TDS sections, verified source of truth
- Every LLM call uses controlled data, not training data (eliminates black box risk)
- Supabase PostgreSQL with 15 tables, RLS, pgvector

**Agents:**
- Parser: dynamic column mapper (Approach 1: fuzzy + LLM for uncertain)
- Matcher: 5 deterministic passes + Pass 6 LLM-assisted for ambiguous
- Checker: LLM section classification + CA-level remediation writing
- Reporter: LLM narrative summaries + 4-sheet Excel report
- Learning: human decisions → LLM pattern extraction → pgvector similarity
- Chat: 100% LLM with agentic loop, 6 tools, SSE streaming
- Orchestrator: error isolation, run tracking, Learning Pass 0

**Infrastructure:**
- FastAPI with 22 endpoints, 6 routers
- SSE streaming with 12 event types (LLM insights visible in real-time)
- Supabase Auth JWT verification
- 182 tests across 12 files (unit, service, agent, integration, edge cases)

**Phase 2 backlog:**
- AWS deployment (ECS Fargate)
- Frontend auth UI (LoginPage, SignupPage in aibookclose)
- Real embeddings (replace pseudo-embeddings with Anthropic/OpenAI)
- Knowledge base in DB (for multi-FY support)
- Security hardening (rate limiting, audit logging)
- CI/CD pipeline

### Changed
- (nothing yet)

### Fixed
- (nothing yet)

### Known Issues
- `reset_client.py` needs evaluation before production use
- Claude chat bridge (experiment branch) requires Anthropic API key — not yet tested end-to-end
- Chat bridge uses file-based polling (500ms) — replace with WebSocket for production
- `book-close-ui/` directory still exists in repo (legacy copies) — can be removed once ui/ is confirmed stable
- 194H, 194J(b), 194Q sections not matched by Matcher (by design for MVP scope 194A + 194C)

---

## Version History

### 2.1.0 — Unified Repo + Chat Bridge + Dashboard Redesign (2026-03-26)

**Repo restructure:**
- Moved frontend from aibookclose into aitdsrecon/ui/ — single repo, one git pull
- Added DEV-SETUP.md for new developer onboarding

**Dashboard redesign:**
- New KPIs: Entries Analyzed, Entries Reconciled (TDS + exempt), Actual TDS Deducted, TDS at Risk
- TDS at Risk only shows genuinely missing/wrong TDS (not zero-rate exempt)
- Tabs: Section Summary (inline issues per section), TDS Details (with Zero TDS group), Pending
- Section Summary shows amount + TDS + matched in one line with issue badge

**Chat bridge experiment (branch: claude/chat-bridge-experiment-Akcin):**
- File-based bridge: UI → FastAPI → inbox.json → Claude (Anthropic SDK) → outbox.json → UI
- Claude has system prompt with TDS knowledge + tool definitions for all agents
- Tools: run_full_pipeline, run_parser, run_matcher, run_checker, run_reporter, get_results, get_findings, submit_review
- Thinking dots in UI while Claude processes
- Graceful fallback if bridge not running

**Other:**
- 3-sheet Excel report (Issues, TDS Matched, Zero TDS Exempt) with styled headers
- Downloadable reports from chat (Excel, CSV)
- Generic parser — no hardcoded client data
- Real-time SSE streaming for pipeline execution
- File upload from chat (drag-drop + paperclip)
- Windows encoding fix (UTF-8 for CSV)

### 2.0.0 — TDS Recon Agentic System (2026-03-26)

**5-Agent Pipeline:**
- Parser Agent — parses Form 26 + Tally XLSX with dynamic column detection
- Matcher Agent — 6-pass engine (exact, GST-adjusted, exempt, fuzzy, aggregated + learned rules)
- TDS Checker Agent — 5 compliance checks (section, rate, base amount, threshold, missing TDS)
- Reporter Agent — JSON summary + CSV reports + 3-sheet Excel workbook
- Learning Agent — human review decisions stored as rules for future runs

### 1.0.0 — Complete Payment Recon Demo (2026-03-19)

- 3-panel layout with nav+chat, workflow center, detail slider
- Multi-step workflow: Upload files → Map columns → View results
- Mock data: 80 transactions (67 matched, 13 issues)

---

## Session Log

| Date | Session Summary | Files Touched | Version After |
|------|----------------|---------------|---------------|
| 2026-03-26 (cont.) | Unified repo, dashboard redesign, Excel reports, chat bridge experiment, DEV-SETUP.md | ui/*, api_server.py, reporter_agent.py, TdsRecon.jsx, tds-recon.css, chat_bridge.py, DEV-SETUP.md | 2.1.0 |
| 2026-03-26 | TDS Recon MVP: 5-agent pipeline, SSE streaming, chat UI, generic parser | All agent files, api_server.py, reconcile.py, TdsRecon.jsx | 2.0.0 |
| 2026-03-19 | Rebranded to Lekha AI, accordion grouping, category actions, email modal | App.jsx, index.css, index.html, lekha-logo.svg, SOP.md | 1.0.0 |

---

## Branches

| Branch | Purpose | Status |
|--------|---------|--------|
| `claude/sub-agents-mvp-guide-Akcin` | Main dev branch — stable MVP | Active |
| `claude/chat-bridge-experiment-Akcin` | Claude chat brain experiment | Experimental |

---

## Versioning Rules

- **PATCH (0.0.x):** Bug fixes, style tweaks
- **MINOR (0.x.0):** New feature or view
- **MAJOR (x.0.0):** Backend integration or architectural change
