# Run Lekha TDS Calculator locally

Two terminals. Founder uses Windows — commands shown for PowerShell and bash/zsh.

## 1. One-time setup

### `backend/.env`

Copy the template and fill the values:

```bash
# bash / zsh (Mac / Linux / WSL)
cp .env.example backend/.env
```

```powershell
# PowerShell (Windows)
Copy-Item .env.example backend\.env
```

Open `backend/.env` and set:

```
GEMINI_API_KEY=<paste a fresh key from https://aistudio.google.com/app/apikey>
SESSION_SECRET=<run the generate command below, paste the output>
```

Generate a session secret once and paste it in:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Leave `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` empty for now — the app
will fall back to a dev-bypass login so you can test immediately.

### Google OAuth (optional — enable when you want to test the Google flow)

1. Go to https://console.cloud.google.com → APIs & Services → Credentials.
2. Click **Create Credentials → OAuth client ID**.
3. Application type: **Web application**.
4. Authorised JavaScript origins: `http://localhost:5173`.
5. Authorised redirect URIs: `http://localhost:8000/auth/google/callback`.
6. Copy the Client ID + Client Secret into `backend/.env`:
   ```
   GOOGLE_CLIENT_ID=<paste>
   GOOGLE_CLIENT_SECRET=<paste>
   ```
7. Restart the backend. The login screen now shows "Continue with Google".

## 2. Run the backend (terminal 1)

```bash
# bash / zsh
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api_server:app --reload --port 8000
```

```powershell
# PowerShell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn api_server:app --reload --port 8000
```

Health check: http://localhost:8000/api/health
Should return `{"status":"ok", "llm_configured": true}`.

## 3. Run the frontend (terminal 2)

```bash
# bash / zsh
cd frontend
npm install
npm run dev
```

```powershell
# PowerShell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

## 4. Test flow

1. The login screen appears.
2. If Google OAuth is configured → click **Continue with Google**.
   Otherwise → type any email in the **Dev bypass** box and **Continue**.
3. You land on the upload page. Drag-and-drop an Excel or CSV.
4. Watch the activity stream. If any rows are ambiguous, Lekha will ask
   questions one at a time with a progress tracker.
5. When done, the Party / Section / Quarter report renders and the
   **Download Excel** button gives you the 5-sheet branded report.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `API offline` in header | Backend not running or wrong port. Check terminal 1. |
| `Mock mode` in header | `GEMINI_API_KEY` missing from `backend/.env`. |
| Login screen stuck on dev-bypass | OAuth env vars missing. Set them and restart. |
| Google callback redirects to a 404 | Redirect URI in Google Console doesn't match `OAUTH_REDIRECT_URI` in `.env`. |
| CORS error in browser console | Frontend running on a port other than 5173. Add it to `CORS_ORIGINS` in `.env`. |
