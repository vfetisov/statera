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

## LinkedIn ingestion

Persist the smoke-test previews into PostgreSQL.

```bash
source .venv/bin/activate
vi .env
```

Recommended values in `.env`:

```
LINKEDIN_DEBUG_PAUSE=false
LINKEDIN_DUMP_DOM=false
```

Run:

```bash
python scripts/linkedin_ingest.py
```

- The script reads up to 10 currently available LinkedIn cards.
- It creates or updates source/search/company/vacancy records.
- It is safe to run repeatedly; repeated jobs are matched by LinkedIn external
  ID.
- It does not yet fetch the full job description.
- It does not yet run LLM analysis.

SQL verification example:

```sql
SELECT
    v.external_id,
    v.title,
    c.name AS company,
    v.location,
    v.status,
    v.first_seen_at,
    v.last_seen_at
FROM vacancies v
LEFT JOIN companies c ON c.id = v.company_id
ORDER BY v.first_seen_at DESC;
```

## LinkedIn full description fetch

Fetch the current job description for LinkedIn vacancies that do not yet have
one, and store it (one `vacancy_contents` row per vacancy, version always 1).

```bash
source .venv/bin/activate
vi .env
```

Recommended settings in `.env`:

```
LINKEDIN_DEBUG_PAUSE=false
LINKEDIN_DUMP_DOM=false
LINKEDIN_DESCRIPTION_FETCH_LIMIT=5
```

Run:

```bash
python scripts/linkedin_fetch_descriptions.py
```

- Only LinkedIn vacancies without a current description are selected.
- The default batch size is 5.
- Only the current description is stored.
- `version` stays equal to 1.
- Repeated identical descriptions are not duplicated.
- No LLM analysis is performed.
- No applications are submitted.

SQL verification example:

```sql
SELECT
    v.external_id,
    v.title,
    c.name AS company,
    vc.version,
    length(vc.raw_text) AS description_length,
    vc.content_hash,
    vc.fetched_at
FROM vacancies v
JOIN vacancy_contents vc ON vc.vacancy_id = v.id
LEFT JOIN companies c ON c.id = v.company_id
ORDER BY vc.fetched_at DESC;
```

## Headless production (Ubuntu)

Manual LinkedIn login always runs **headed** on a machine with a GUI. All other
LinkedIn browser flows (smoke reader, ingestion, description fetching, headless
check) are configurable via `PLAYWRIGHT_HEADLESS`:

- local debugging: `PLAYWRIGHT_HEADLESS=false`
- Ubuntu production: `PLAYWRIGHT_HEADLESS=true`

Production configuration example (`.env`):

```
APP_ENV=production
PLAYWRIGHT_HEADLESS=true
LINKEDIN_DEBUG_PAUSE=false
LINKEDIN_DUMP_DOM=false
LINKEDIN_DESCRIPTION_FETCH_LIMIT=5
```

`LINKEDIN_DEBUG_PAUSE=true` is rejected in headless mode: interactive pause
needs a GUI and would hang a headless job.

### Ubuntu Playwright installation

```bash
python -m playwright install --with-deps chromium
```

This installs Chromium and the required Linux system dependencies. No desktop
environment and no X server are required for headless operation.

### Secure storage-state deployment

The authenticated storage-state file is created manually on macOS by
`python scripts/linkedin_login.py`. Copy it to the Ubuntu server and restrict
permissions:

```bash
scp var/playwright/linkedin-storage-state.json user@server:/opt/statera/var/playwright/
```

On Ubuntu:

```bash
chmod 600 /opt/statera/var/playwright/linkedin-storage-state.json
```

- The file provides authenticated access to LinkedIn.
- It must never be committed or shared.
- It must be readable only by the Statera service user.
- When the session expires, recreate it manually on macOS and copy it again.

Headless jobs never log in automatically; an expired session fails clearly with
`LinkedInAuthenticationRequired`.
