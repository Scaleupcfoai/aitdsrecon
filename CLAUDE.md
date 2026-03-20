# CLAUDE.md — Lekha AI v1 (Payment Reconciliation)

> **Read CHANGELOG.md first** before making any changes. It contains the current version, recent changes, and known issues.

## Project Identity

- **Product:** Lekha AI v1 — AI-Powered Payment Reconciliation Demo
- **Owner:** Ashish (Founder, not a full-time engineer)
- **Stage:** Demo complete, shared with developer
- **Stack:** React 19 + Vite 7 (frontend only, mock data, no backend)
- **Location:** `C:\Users\Ashish\recon-demo`
- **GitHub:** https://github.com/Scaleupcfoai/aitdsrecon
- **Dev Server:** `npm run dev` → http://localhost:5174/

## What This Does

Payment-to-sales reconciliation for e-commerce/D2C brands. Upload a sales report + payment settlement file → map columns → AI matches transactions → groups unreconciled by issue type → category-level resolution actions.

## Repo Structure

```
recon-demo/
├── CLAUDE.md / CHANGELOG.md  ← Version control
├── SOP.md                     ← Startup instructions
├── index.html                 ← Entry point
├── public/lekha-logo.svg      ← Logo
└── src/
    ├── App.jsx                ← All UI logic (~750 lines)
    ├── index.css              ← All styles (~640 lines)
    └── data/mockData.js       ← 80 transactions, 67 matched, 13 issues
```

## Key Features

- 3-panel layout (nav+chat, workflow, detail slider)
- Multi-step workflow: Upload → Map Columns → Results
- Grouped unreconciled transactions by issue type (accordion)
- 7 issue categories with context-specific actions (email, call, check files)
- Email modal for outreach workflows
- Lekha AI branding with custom logo

## Related Projects

- **Book Close Demo:** `C:\Users\Ashish\book-close-demo` (port 5175)
- **TDS Recon (v2):** Planned, not yet built
