# SOP — TDS Recon Demo Startup

## Paths on This Machine

```
/home/user/aitdsrecon/          ← TDS Recon agents + API server
/home/user/aitdsrecon/tds-recon/api_server.py   ← FastAPI server
/home/user/aitdsrecon/tds-recon/data/           ← Parsed data + results
/home/user/aitdsrecon/book-close-ui/            ← UI files (already copied to aibookclose)

/home/user/aibookclose/         ← Book Close demo UI (React + Vite)
/home/user/aibookclose/src/TdsRecon.jsx         ← TDS Recon component
/home/user/aibookclose/src/tds-recon.css        ← TDS Recon styles
```

## Step-by-Step: Starting the Demo

### Step 1 — Open Terminal 1

Open a terminal window.

### Step 2 — Start the API server

```bash
cd /home/user/aitdsrecon/tds-recon
```

```bash
uvicorn api_server:app --reload --port 8000
```

You should see output like:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Started reloader process
```

Leave this terminal running. Do not close it.

### Step 3 — Open Terminal 2

Open a second terminal window.

### Step 4 — Start the React UI

```bash
cd /home/user/aibookclose
```

```bash
npm run dev
```

You should see output like:
```
  VITE v7.3.1  ready in 300 ms

  ➜  Local:   http://localhost:5173/
```

Note the port number shown (could be 5173, 5174, or 5175 depending on what's running).

Leave this terminal running. Do not close it.

### Step 5 — Open the browser

Open the URL shown in Terminal 2 output (e.g. `http://localhost:5173/`).

You should see the Lekha AI Book Close app with a white background.

### Step 6 — Navigate to Reconciliations

Click **"Reconciliations"** in the left sidebar (3rd item, shows "2/9").

You will see 9 reconciliation tiles arranged in a 3x3 grid.

### Step 7 — Open TDS Recon

Click the **"TDS Payable (all sections)"** tile.
It is in the bottom row, left side, with a red "TAX" badge and "Not Started" status.

The center panel will transform into the TDS Reconciliation workspace.

### Step 8 — Run the reconciliation

Click the **"Run Reconciliation"** button in the top-right corner.

Watch:
- **Right panel**: Agent activity log streams messages one by one
  - Parser Agent parses Form 26 + Tally data
  - Matcher Agent runs 6 matching passes
  - TDS Checker validates compliance
  - Reporter generates reports
- **Left panel**: KPI cards and results appear after pipeline completes

### Step 9 — Explore results

- **Summary tab** (default): Section-wise breakdown. Click a section to expand.
- **Matches tab**: Individual matches grouped by section (194A, 194C). Shows vendor, amount, match type, confidence.
- **Findings tab**: Compliance issues — errors (missing TDS) and warnings (ambiguous sections). Each has remediation guidance.
- **Review tab**: Unmatched vendors for human classification.

### Step 10 — Demo the learning loop

1. Click the **Review** tab
2. Find a vendor like "Bharti Airtel Ltd." — click **"Below Threshold"**
3. Find "United India Insurance Co. Ltd." — click **"Ignore"**
4. Click **"Submit 2 Decisions & Re-run"**
5. Watch the right panel — Learning Agent applies corrections, only re-runs Checker + Reporter
6. Left panel updates with fewer unmatched entries

### Step 11 — Return to Book Close

Click **"← Back to Reconciliations"** at the top to go back to the 9-tile grid.

## Shutting Down

- Terminal 1 (API server): Press `Ctrl+C`
- Terminal 2 (React UI): Press `Ctrl+C`

## Troubleshooting

| Problem | Solution |
|---|---|
| "Failed to connect to API" in browser | Terminal 1 is not running. Go back to Step 2. |
| Blank page in browser | Terminal 2 is not running. Go back to Step 4. |
| "Run Reconciliation" does nothing | Check browser console (F12) for errors. Likely API server not reachable. |
| Port already in use | Kill the process using it: `lsof -ti:8000 \| xargs kill` or `lsof -ti:5173 \| xargs kill` |
