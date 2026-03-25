# SOP — TDS Recon Demo Startup

## Prerequisites

- Node.js 18+ installed
- Python 3.11+ installed
- Both repos cloned:
  - `aitdsrecon` — TDS Recon agents + API server
  - `aibookclose` — Book Close demo UI

## One-Time Setup

### 1. Install Python dependencies (aitdsrecon)

```bash
cd aitdsrecon/tds-recon
pip install fastapi uvicorn
```

### 2. Install Node dependencies (aibookclose)

```bash
cd aibookclose
npm install
```

### 3. Copy TDS Recon UI files into Book Close app

```bash
cp aitdsrecon/book-close-ui/TdsRecon.jsx   aibookclose/src/
cp aitdsrecon/book-close-ui/tds-recon.css   aibookclose/src/
cp aitdsrecon/book-close-ui/index.css.updated   aibookclose/src/index.css
cp aitdsrecon/book-close-ui/App.jsx.updated   aibookclose/src/App.jsx
```

## Starting the Demo

### Terminal 1 — API Server (Python agents)

```bash
cd aitdsrecon/tds-recon
uvicorn api_server:app --reload --port 8000
```

Verify: `curl http://localhost:8000/api/status` should return `{"parsed_ready": true, ...}`

### Terminal 2 — Book Close UI (React)

```bash
cd aibookclose
npm run dev
```

Opens at: `http://localhost:5175/`

## Demo Flow

1. Open `http://localhost:5175/` in browser
2. Click **Reconciliations** in the left nav
3. You see 9 reconciliation tiles (2 done, 3 in progress, 4 not started)
4. Click the **"TDS Payable (all sections)"** tile (bottom-left, red TAX badge)
5. The center panel transforms into the TDS Reconciliation workspace

### Running Reconciliation

6. Click **"Run Reconciliation"** button (top-right)
7. **Right panel** streams agent activity in real-time:
   - Parser Agent: parses Form 26 (85 entries) + Tally (3 registers)
   - Matcher Agent: runs 6 passes (Pass 0: learned rules → Pass 5: aggregated)
   - TDS Checker: validates compliance (section, rate, threshold, missing TDS)
   - Reporter: generates summary + CSV reports
8. **Left panel** populates with results:
   - KPI cards: 56/56 matched, 95% confidence, 8 findings, Rs 1.2L exposure
   - Summary tab: section-wise breakdown (194A, 194C matched; 194H, 194J, 194Q pending)

### Exploring Results

9. Click **Matches** tab → expand Section 194A or 194C → see individual matches
   - Each row: vendor name, amount, match type (Exact/Fuzzy/Aggregated/GST), confidence %
10. Click **Findings** tab → see 3 missing TDS errors + 5 section validation warnings
    - Each finding has: severity badge, vendor, message, remediation guidance

### Human Review (Learning Loop)

11. Click **Review** tab → see unmatched vendors sorted by total amount
12. For each vendor, click **"Below Threshold"** or **"Ignore"**:
    - Example: "Bharti Airtel Ltd." (38 entries, Rs 22,308) → Below Threshold
    - Example: "United India Insurance" (8 entries, Rs 1,01,921) → Ignore (insurance)
13. Click **"Submit X Decisions & Re-run"**
14. **Right panel** shows Learning Agent activity:
    - "Created 3 new rules"
    - "Bharti Airtel: 38 entries → below_threshold"
    - "Resolved 47 entries across 3 vendors"
    - Only Checker + Reporter re-run (NOT full pipeline)
15. **Left panel** updates: unmatched count drops (225 → 178)
16. Repeat steps 12-15 to show the system getting smarter

### Returning to Book Close

17. Click **"← Back to Reconciliations"** to return to the reconciliation grid

## Key Talking Points for CA Firm

- **6-pass matching engine**: exact → GST-adjusted → exempt → fuzzy → aggregated → learned rules
- **Learning loop**: human decisions become reusable rules — system gets smarter with each review
- **Only affected entries re-processed**: Learning Agent doesn't re-run the full pipeline, just applies corrections and re-validates
- **Compliance checks**: section validation, rate validation, base amount (pre-GST), threshold, missing TDS detection
- **Remediation guidance**: each finding includes specific action items (file revised return, check Form 15G/15H, etc.)
- **Sections covered**: 194A (interest) + 194C (contractor/freight) fully reconciled; 194H, 194J(b), 194Q ready to add

## Troubleshooting

| Issue | Fix |
|---|---|
| "Failed to connect to API" in UI | Make sure `uvicorn api_server:app --reload --port 8000` is running in Terminal 1 |
| CORS error in browser console | The API server has CORS configured for all origins — restart uvicorn |
| Port 5175 in use | Change port in `aibookclose/vite.config.js` or kill the process using it |
| Port 8000 in use | Use `uvicorn api_server:app --port 8001` and update `API` const in TdsRecon.jsx |
