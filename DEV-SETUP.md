# Developer Setup Guide — Lekha AI

## Architecture

Two repos, two terminals:

```
aibookclose (frontend)              aitdsrecon (backend)
├── React + Vite                    ├── FastAPI + Python agents
├── All UI components               ├── TDS reconciliation pipeline
├── Connects to backend APIs         ├── SSE streaming, file upload
└── npm run dev → port 5173         └── uvicorn → port 8000
```

## Repos

| Repo | Purpose | URL |
|------|---------|-----|
| **aibookclose** | Frontend (all products) | https://github.com/Scaleupcfoai/aibookclose |
| **aitdsrecon** | TDS Recon backend | https://github.com/Scaleupcfoai/aitdsrecon |

## Prerequisites

- **Python 3.11+** — https://www.python.org/downloads/ (check "Add to PATH")
- **Node.js 18+** — https://nodejs.org/ (LTS version)
- **Git**

## Setup (One Time)

### 1. Clone both repos

```cmd
cd C:\Users\YourName
git clone https://github.com/Scaleupcfoai/aibookclose.git
git clone https://github.com/Scaleupcfoai/aitdsrecon.git
```

### 2. Switch to the right branches

```cmd
cd aibookclose
git checkout frontend-unified

cd ..\aitdsrecon
git checkout claude/chat-bridge-experiment-Akcin
```

### 3. Install frontend dependencies

```cmd
cd aibookclose
npm install
```

### 4. Install backend dependencies

```cmd
cd ..\aitdsrecon\tds-recon
pip install -r requirements.txt
```

If `pip` doesn't work, use `python -m pip install -r requirements.txt`

## Running the App

Open **two terminals**.

### Terminal 1 — Backend

```cmd
cd aitdsrecon\tds-recon
python -m uvicorn api_server:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Terminal 2 — Frontend

```cmd
cd aibookclose
npm run dev
```

You should see:
```
VITE v7.x.x  ready
➜  Local: http://localhost:5173/
```

### Open Browser

Go to `http://localhost:5173/`

## What You'll See

**Reconciliations page** (click "Reconciliations" in left sidebar):

| Tile | Status | Backend |
|------|--------|---------|
| Sales-Payment Reconciliation | Working (mock data) | Frontend only, no backend needed |
| ICICI Savings A/c | Demo data | Frontend only |
| Amex Corporate Card | Demo data | Frontend only |
| TDS Payable (all sections) | Working (real pipeline) | Needs backend on port 8000 |
| Other tiles | Demo data | Frontend only |

### Testing TDS Recon

1. Make sure Terminal 1 (backend) is running
2. Click **"TDS Payable"** tile (TAX badge, bottom row)
3. In the chat, type **"run reconciliation"** or click the action chip
4. Watch agents stream in real-time
5. Click **"Export Report"** to download Excel

### Testing Sales-Payment Recon

1. Click **"Sales-Payment Reconciliation"** tile (SALES badge, top-left)
2. Click **"Upload Sales Report"** → then **"Upload Payment Report"**
3. Click **"Continue to Column Mapping"**
4. Click **"Run Reconciliation"**
5. Explore issues, send emails, process refunds

## Repo Structure

### aibookclose (frontend)

```
aibookclose/
├── src/
│   ├── App.jsx              ← Main app shell (nav, tiles, routing)
│   ├── TdsRecon.jsx         ← TDS Recon workspace (chat + dashboard)
│   ├── tds-recon.css        ← TDS Recon styles
│   ├── PaymentRecon.jsx     ← Sales-Payment Recon workspace
│   ├── payment-recon.css    ← Payment Recon styles (light indigo theme)
│   ├── index.css            ← Global styles + design tokens
│   ├── main.jsx             ← React entry
│   └── data/
│       ├── mockData.js      ← Book Close demo data (tasks, recons, JEs)
│       └── paymentMockData.js ← Payment recon mock (80 transactions)
├── package.json
└── vite.config.js
```

### aitdsrecon (backend)

```
aitdsrecon/
├── tds-recon/
│   ├── api_server.py        ← FastAPI (SSE streaming, upload, download, chat)
│   ├── reconcile.py         ← Pipeline orchestrator
│   ├── chat_bridge.py       ← Claude AI chat brain (experimental)
│   ├── reset_client.py      ← Clear data for new client
│   ├── requirements.txt     ← Python dependencies
│   ├── agents/
│   │   ├── parser_agent.py      ← Parse Form 26 + Tally XLSX
│   │   ├── matcher_agent.py     ← 6-pass matching engine
│   │   ├── tds_checker_agent.py ← 5 compliance checks
│   │   ├── reporter_agent.py    ← Reports (JSON, CSV, Excel)
│   │   ├── learning_agent.py    ← Human review → learned rules
│   │   └── event_logger.py      ← Structured events + SSE callback
│   └── data/
│       ├── parsed/          ← Parsed JSON (generated)
│       ├── results/         ← Match results, reports (generated)
│       ├── rules/           ← Learned rules
│       └── uploads/         ← Uploaded XLSX files
├── data/hpc/                ← Sample XLSX files for testing
├── CHANGELOG.md
└── DEV-SETUP.md             ← This file
```

## Key API Endpoints (port 8000)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/run/stream` | Run full pipeline (SSE streaming) |
| POST | `/api/upload` | Upload Form 26 + Tally XLSX |
| GET | `/api/run/stream/upload` | Run pipeline on uploaded files |
| GET | `/api/download/{filename}` | Download reports |
| GET | `/api/results` | Get cached results |
| POST | `/api/chat` | Send message to Claude chat bridge |
| POST | `/api/review` | Submit human review decisions |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `uvicorn not recognized` | Use `python -m uvicorn api_server:app --reload --port 8000` |
| `vite not recognized` | Run `npm install` first |
| `npm` blocked in PowerShell | Use Command Prompt (`cmd`) or run `Set-ExecutionPolicy RemoteSigned` |
| CORS error in browser | Backend not running — start Terminal 1 |
| Blank page | Frontend not running — start Terminal 2 |
| Port already in use | Kill existing process: `taskkill /F /IM node.exe` or `taskkill /F /IM python.exe` |

## Switching Clients (Backend)

To clear old client data before running on new data:

```cmd
cd aitdsrecon\tds-recon
python reset_client.py --keep-rules
```

Then upload new files via the UI.
