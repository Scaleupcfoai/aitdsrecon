# Lekha AI v1 — Startup SOP

## Standard Operating Procedure: Running the Demo Locally

---

### Prerequisites

1. **Node.js** (v18 or later) — [Download](https://nodejs.org/)
   - Verify: Open a terminal and run `node --version`
2. **npm** (comes with Node.js)
   - Verify: `npm --version`

---

### First-Time Setup (One-Time Only)

1. Open **Command Prompt** or **PowerShell**

2. Navigate to the project folder:
   ```
   cd C:\Users\Ashish\recon-demo
   ```

3. Install dependencies:
   ```
   npm install
   ```
   This creates the `node_modules/` folder. Takes ~30 seconds.

---

### Starting the Dev Server

1. Open **Command Prompt** or **PowerShell**

2. Navigate to the project folder:
   ```
   cd C:\Users\Ashish\recon-demo
   ```

3. Start the Vite dev server:
   ```
   npm run dev
   ```

4. You should see output like:
   ```
   VITE v7.x.x  ready in XXX ms

   ➜  Local:   http://localhost:5173/
   ➜  Network: http://x.x.x.x:5173/
   ```

5. Open your browser and go to the URL shown (usually **http://localhost:5173/**)

---

### Stopping the Server

- Press **Ctrl + C** in the terminal where the server is running
- Type `Y` if prompted to confirm

---

### Using the Demo

1. **Upload Phase**: Click "Use sample data" at the bottom-left chat area, or click the upload boxes to simulate file uploads
2. **Map Columns Phase**: Review the auto-detected column mappings and click "Run Reconciliation"
3. **Results Phase**:
   - View the summary dashboard (matched, unmatched, total amounts)
   - Expand issue groups (accordion) to see individual unreconciled transactions
   - Use "Next Steps" action buttons per category (Email, Call, Check Files)
   - Click individual transactions to see details in the right panel

---

### Troubleshooting

| Issue | Solution |
|-------|----------|
| `npm run dev` fails | Run `npm install` first to ensure dependencies are installed |
| Port already in use | Kill the existing process or use `npx vite --port 5175` |
| Blank white page | Open browser DevTools (F12) → Console tab → check for errors |
| `node` not recognized | Install Node.js and restart your terminal |
| Changes not reflecting | Vite has hot reload — changes should appear automatically. If not, hard refresh with Ctrl+Shift+R |

---

### Project Structure (Key Files)

```
recon-demo/
├── index.html              # Entry point HTML
├── package.json            # Dependencies and scripts
├── vite.config.js          # Vite configuration
├── public/
│   └── lekha-logo.svg      # Lekha AI logo
└── src/
    ├── main.jsx            # React entry point
    ├── App.jsx             # Main application (all UI logic)
    ├── index.css           # All styles
    └── data/
        └── mockData.js     # Sample reconciliation data (80 transactions)
```

---

### Sharing with Others

To share this demo with a developer:

1. Push to GitHub (if not already):
   ```
   git remote add origin https://github.com/<username>/lekha-ai-demo.git
   git push -u origin master
   ```

2. They clone and run:
   ```
   git clone https://github.com/<username>/lekha-ai-demo.git
   cd lekha-ai-demo
   npm install
   npm run dev
   ```

---

*Last updated: March 19, 2026*
