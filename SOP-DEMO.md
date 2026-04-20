# SOP — TDS Recon Demo Startup

## Paths (Windows)

```
C:\Users\Ashish\aitdsrecon\              ← TDS Recon backend (Python, FastAPI)
C:\Users\Ashish\aitdsrecon\tds-recon\    ← Agents + API server
C:\Users\Ashish\aitdsrecon\tds-recon\data\  ← Parsed data + results

C:\Users\Ashish\aibookclose\             ← Frontend (React + Vite)
C:\Users\Ashish\aibookclose\src\TdsRecon.jsx   ← TDS Recon component
C:\Users\Ashish\aibookclose\src\App.jsx        ← 15-tile reconciliation grid
```

## Active Branches

| Repo | Branch |
|------|--------|
| aitdsrecon (backend) | `claude/continue-tds-frontend-i5SUW-v2` |
| aibookclose (frontend) | `claude/all-15-recons-homepage` |

## Step-by-Step: Starting the Demo

### Step 1 — Open PowerShell / Command Prompt #1 (Backend)

```powershell
cd C:\Users\Ashish\aitdsrecon
git checkout claude/continue-tds-frontend-i5SUW-v2
git pull origin claude/continue-tds-frontend-i5SUW-v2
```

If git pull fails due to local result files, stash first:
```powershell
git stash
git pull origin claude/continue-tds-frontend-i5SUW-v2
```

### Step 2 — Start the Backend API Server

```powershell
python -m uvicorn tds-recon.api_server:app --host 0.0.0.0 --port 8000 --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Started reloader process
INFO:     Application startup complete.
```

**Leave this window open.** Do not close it.

### Step 3 — Open PowerShell / Command Prompt #2 (Frontend)

```powershell
cd C:\Users\Ashish\aibookclose
git checkout claude/all-15-recons-homepage
git pull origin claude/all-15-recons-homepage
```

### Step 4 — Start the React UI

```powershell
npm run dev
```

You should see:
```
  VITE v7.3.1  ready in 300 ms
  ➜  Local:   http://localhost:5173/
```

Note the port (usually 5173). **Leave this window open.**

### Step 5 — Open the Browser

Navigate to: **http://localhost:5173/**

You should see the Lekha AI Book Close dashboard.

### Step 6 — Navigate to Reconciliations

Click **"Reconciliations"** in the left sidebar.

You will see 15 reconciliation tiles in a 3-column grid, organized in order:
- **Revenue**: Platform Sales-to-Cash, GST Output
- **Expense**: Bank Payments, Amex Credit Card, Prepaid Expenses, Platform Fees
- **Tax**: TDS 26Q, TDS 24Q, GST ITC, GST Liability
- **Balance Sheet**: HDFC Bank, ICICI Bank, Intercompany, Accrued Liabilities, Payroll

### Step 7 — Open TDS Reconciliation

Click the **"TDS — 26Q vs Books (Vendor Payments)"** tile (top-left, TDS orange badge).

The center panel transforms into the TDS Reconciliation workspace with the vertical stacked layout — 5 KPI cards on top, tabs + data below, chat panel at the bottom.

### Step 8 — Run the Reconciliation

Click **"Run Reconciliation"** button (top-right corner).

Watch the chat panel stream real-time progress:
- **Parser Agent** — reads Form 26 + Form 24 + Tally books (~1 sec)
- **Matcher Agent** — 5-pass matching across all 6 sections (~2 sec)
- **TDS Checker** — section, rate, PAN, timing validations (~2 sec)
- **Reporter Agent** — generates 6-sheet Excel (~1 sec)

Total: ~30 seconds (includes 30s auto-continue timeout on unmatched entries decision).

### Step 9 — Explore Results

**5 KPI cards** update with actual numbers:
1. Number of GE in Books analysed
2. Entries Reconciled (with match rate bar)
3. TDS Amount Reconciled
4. Expense Exempted
5. TDS Variance Flagged for Review (clickable → Pending tab)

**Tabs** (all clickable):
- **Section Summary** — section-wise breakdown with inline findings
- **TDS Details** — all matched entries grouped by section
- **Pending** — issues needing review (with `*` tooltip)

**Proactive insight** appears in chat:
> "Reconciliation complete — 327 entries reconciled.
> 2 vendors with potential missing TDS: Kochar Tradelink LLP (₹44,932), Pukesh Sharma (₹20,877)
> ..."

Action buttons:
- Review Discrepancies
- Explore Reconciled Entries
- Review Name Mismatches
- Generate Remediation Memo

### Step 10 — Download Excel Report

Click **"Generate Remediation Memo"** or type "export" in chat.

Download the 6-sheet Excel:
1. Executive Summary (NEW — KPIs + expense head drill-down + timing summary)
2. Issues for Review
3. TDS Matched
4. Zero TDS — Exempt
5. Late TDS Deduction (14 entries, ₹2,876 interest)
6. Late TDS Deposit (✓ All on time)

### Step 11 — Return to Dashboard

Click **"← Back to Reconciliations"** at the top to return to the 15-tile grid.

## Shutting Down

- Backend window: Press `Ctrl+C`
- Frontend window: Press `Ctrl+C`

## Troubleshooting

| Problem | Solution |
|---|---|
| "Failed to connect to API" in browser | Backend window is not running. Go back to Step 2. |
| Blank page in browser | Frontend window is not running. Go back to Step 4. |
| Pipeline stuck at Parser | Parsed data files missing. Re-pull branch: `git pull origin claude/continue-tds-frontend-i5SUW-v2` |
| `git pull` fails with merge conflicts on result files | Run `git stash` first, then `git pull` |
| Port 8000 already in use | Kill process: `netstat -ano \| findstr :8000` then `taskkill /PID <pid> /F` |
| Port 5173 already in use | Kill process: `netstat -ano \| findstr :5173` then `taskkill /PID <pid> /F` |
| "uvicorn not found" | Install: `pip install fastapi uvicorn openpyxl python-multipart` |
| "npm not found" | Install Node.js from nodejs.org |

## Quick Restart (Both Servers)

**Backend:**
```powershell
cd C:\Users\Ashish\aitdsrecon && python -m uvicorn tds-recon.api_server:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```powershell
cd C:\Users\Ashish\aibookclose && npm run dev
```

Open http://localhost:5173/
