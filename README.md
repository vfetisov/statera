# Statera

Personal AI Career Assistant.

## Local development

Create a virtual environment, install dependencies and start the server:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Check the health endpoints:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/health/db
```

## LinkedIn smoke test

A minimal Playwright smoke test that verifies Chromium launches, the saved
LinkedIn session can be reused, and visible job cards can be read from one
saved-search URL.

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env
vi .env
python scripts/linkedin_login.py
python scripts/linkedin_smoke.py
```

Notes:

- **Login is manual.** `python scripts/linkedin_login.py` opens a visible
  Chromium window; you sign in to LinkedIn by hand, then press Enter in the
  terminal. Credentials are never handled by the code.
- **`LINKEDIN_SEARCH_URL`** should contain one saved-search URL copied from
  your browser (for example `https://www.linkedin.com/jobs/search/?keywords=example`).
- The **storage-state file** (`var/playwright/linkedin-storage-state.json` by
  default, overridable via `LINKEDIN_STORAGE_STATE`) contains authenticated
  session data. It must **never be committed or shared** — it is Git-ignored.
- The smoke test only **reads currently visible** job cards. It does not apply
  to jobs, does not paginate, and does not write to the database.
