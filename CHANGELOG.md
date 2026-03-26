# CHANGELOG — Lekha AI (TDS Reconciliation + Payment Recon)

> This file is Claude Code's "memory" across sessions. Read it at the start. Update it at the end.

## Current State

- **Version:** 2.0.0
- **Status:** TDS Recon MVP complete — 5-agent pipeline, interactive chat UI, Excel reports, generic parser
- **Last session:** 2026-03-26
- **Next priority:** Run on new client data, validate parser with different Tally structures, chat UX Phase 2 (inline result cards in chat)

## Unreleased

### Added
- (nothing yet)

### Changed
- (nothing yet)

### Fixed
- (nothing yet)

### Known Issues
- `reset_client.py` needs evaluation before production use — review whether --keep-rules pattern retention is useful across clients
- aibookclose repo on GitHub only has initial commit — TDS Recon UI files must be manually copied from aitdsrecon/book-close-ui/
- 194H, 194J(b), 194Q sections are in Form 26 data but matcher only processes 194A + 194C (by design for MVP)
- Chat command parser is keyword-based — no NLP, just string matching

---

## Version History

### 2.0.0 — TDS Recon Agentic System (2026-03-26)

**5-Agent Pipeline:**
- Parser Agent — parses Form 26 + Tally XLSX with dynamic column detection
- Matcher Agent — 6-pass engine (exact, GST-adjusted, exempt, fuzzy, aggregated + learned rules)
- TDS Checker Agent — 5 compliance checks (section, rate, base amount, threshold, missing TDS)
- Reporter Agent — JSON summary + CSV reports + 3-sheet Excel workbook
- Learning Agent — human review decisions stored as rules for future runs

**Backend:**
- FastAPI server with SSE streaming (real-time events as agents execute)
- Individual agent endpoints (/api/run/parser, /matcher, /checker, /reporter)
- File upload endpoint + stream-from-upload pipeline
- Download endpoint for reports (Excel, CSV, JSON)

**UI:**
- Split-panel: Dashboard (left) + Interactive Chat (right)
- KPIs: Entries Analyzed, Reconciled (TDS + exempt), Actual TDS, TDS at Risk
- Tabs: Section Summary (with inline issues), TDS Details, Pending
- Chat: text commands, action chips, file drag-drop, download links
- Agent thinking blocks stream in real-time inside chat conversation

**Data:**
- Below-threshold entries (TDS=0) count as resolved, not pending review
- Excel report: Sheet 1 (Issues for Review), Sheet 2 (TDS Matched + expense head), Sheet 3 (Zero TDS Exempt with reason)
- Generic parser — no hardcoded column names, director names, or vendor names

### 1.0.0 — Complete Payment Recon Demo (2026-03-19)

- 3-panel layout with nav+chat, workflow center, detail slider
- Multi-step workflow: Upload files → Map columns → View results
- Grouped unreconciled transactions by issue type (accordion UI)
- 7 issue categories with category-level resolution actions
- Email modal for outreach workflows
- Lekha AI branding with custom SVG logo
- Mock data: 80 transactions (67 matched, 13 issues)

---

## Session Log

| Date | Session Summary | Files Touched | Version After |
|------|----------------|---------------|---------------|
| 2026-03-26 | TDS Recon MVP: 5-agent pipeline, SSE streaming, chat UI, Excel reports, generic parser, dashboard redesign | api_server.py, reconcile.py, parser_agent.py, matcher_agent.py, tds_checker_agent.py, reporter_agent.py, event_logger.py, learning_agent.py, TdsRecon.jsx, tds-recon.css, reset_client.py, requirements.txt, SOP-DEMO.md | 2.0.0 |
| 2026-03-19 | Rebranded to Lekha AI, added accordion grouping, category actions, email modal, SOP, pushed to GitHub | App.jsx, index.css, index.html, lekha-logo.svg, SOP.md | 1.0.0 |

---

## Versioning Rules

- **PATCH (0.0.x):** Bug fixes, style tweaks
- **MINOR (0.x.0):** New feature or view
- **MAJOR (x.0.0):** Backend integration or architectural change
