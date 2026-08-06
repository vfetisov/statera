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

## Provider-independent LLM architecture

Statera analyzes vacancies through a provider-neutral LLM layer. Only the
OpenAI adapter imports the OpenAI SDK; everything else works against the common
`LLMProvider` interface, so a different provider (Anthropic, Gemini, Ollama,
...) can be added later without rewriting career-data, context, prompt,
selection, validation, or persistence code.

How it works:

- **Private career files are loaded by Statera.** Documents placed in
  `var/private/` are read, normalized, hashed, and kept as separate logical
  assets. **LLM providers never access the filesystem directly** and never
  decide which files to read.
- **Task-specific context builders select only relevant assets.** For vacancy
  fit analysis: the full Master Career Brief (required) plus optional
  `SCORING_RULES`. The Master Resume, Resume Template, and Application Rules
  are loaded if configured but are intentionally **not** sent to the model for
  this task; later tasks (resume tailoring, applications) will use their own
  context types.
- **The same context and schema work with any provider.** `VacancyFitAnalysis`
  in `app/llm/schemas.py` is provider-neutral and enforces score ranges,
  recommendation values, and list-item limits.
- **Business services depend on `LLMProvider`, not an SDK.** Selection,
  context assembly, prompt building, and persistence live in
  `app/services/vacancy_analysis.py`, `app/llm/context/`, and
  `app/llm/prompts/` and contain no provider imports.
- **The first concrete adapter is OpenAI** (`app/llm/providers/openai.py`)
  using the Responses API with strict Pydantic structured output.
- **Future providers** require only: provider settings, one adapter module
  implementing `LLMProvider`, and one branch in the factory
  (`app/llm/providers/factory.py`). No business service changes.
- **Provider-qualified names are stored in the current `model` field.**
  Because the existing `analyses` table has no provider column (and the schema
  must not change), the stored model identifier is `provider:model`, for
  example `openai:gpt-5-mini`. This keeps provider identity without a
  migration.

### Private assets

Place private career documents under `var/private/` (Git-ignored):

```bash
mkdir -p var/private
chmod 700 var/private
cp "/path/to/Master Career Brief.docx" var/private/master-career-brief.docx
cp "/path/to/Master Resume.docx" var/private/master-resume.docx
cp "/path/to/Resume Template.docx" var/private/resume-template.docx
cp "/path/to/Scoring Rules.md" var/private/scoring-rules.md
chmod 600 var/private/*
```

Example `.env`:

```
LLM_PROVIDER=openai
LLM_MODEL=gpt-5-mini
LLM_REASONING_EFFORT=medium
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=2
LLM_MAX_CONTEXT_CHARACTERS=

VACANCY_ANALYSIS_BATCH_LIMIT=5
VACANCY_ANALYSIS_PROMPT_VERSION=vacancy-fit-v3

MASTER_CAREER_BRIEF_PATH=var/private/master-career-brief.docx
MASTER_RESUME_PATH=var/private/master-resume.docx
RESUME_TEMPLATE_PATH=var/private/resume-template.docx
APPLICATION_RULES_PATH=
SCORING_RULES_PATH=

OPENAI_API_KEY=...
```

`inspect_career_assets.py` shows which assets Statera will use (metadata only —
never the text) before spending API credits.

### Fit analysis

Vacancy analysis currently uses:

- Master Career Brief
- optional scoring rules
- the full vacancy description

It intentionally does **not** use:

- Master Resume
- Resume Template
- Application Rules

Those assets are reserved for later task-specific context builders.

Commands:

```bash
python scripts/inspect_career_assets.py   # verify loaded assets (metadata only)
python scripts/show_analysis_queue.py     # vacancies awaiting analysis (no LLM)
python scripts/analyze_vacancies.py       # run one bounded analysis batch
```

The analyzer is idempotent: a vacancy with an analysis for the same
`vacancy_content_id`, provider-qualified `model`, and `prompt_version` is
skipped. A different provider/model, prompt version, or vacancy content may
create a new analysis row. Each vacancy is processed in its own savepoint, so
one failure does not discard previous successes, and the batch limit is set by
`VACANCY_ANALYSIS_BATCH_LIMIT` (1–20, default 5).

SQL verification:

```sql
SELECT
    v.external_id,
    v.title,
    c.name AS company,
    a.overall_score,
    a.technical_score,
    a.leadership_score,
    a.location_score,
    a.recommendation,
    a.summary,
    a.strengths,
    a.weaknesses,
    a.risks,
    a.model,
    a.prompt_version,
    a.created_at
FROM analyses a
JOIN vacancies v ON v.id = a.vacancy_id
LEFT JOIN companies c ON c.id = v.company_id
ORDER BY
    a.overall_score DESC NULLS LAST,
    a.created_at DESC;
```

## DeepSeek provider

Statera can run the same vacancy-analysis pipeline through the official
DeepSeek API.

- Statera uses the official DeepSeek endpoint (`https://api.deepseek.com`).
- The adapter (`app/llm/providers/deepseek.py`) uses the **OpenAI-compatible
  Chat Completions API** with JSON output
  (`response_format={"type": "json_object"}`).
- The `openai` Python SDK is used **only as the HTTP protocol client** for the
  DeepSeek endpoint. OpenAI billing and OpenAI API keys are not involved.
- DeepSeek has its own API key (`DEEPSEEK_API_KEY`) and its own balance.
- The current default model is `deepseek-v4-flash`; `deepseek-v4-pro` may be
  selected for comparison.
- The deprecated model names `deepseek-chat` and `deepseek-reasoner` must not
  be used.
- JSON output is validated locally with the common `VacancyFitAnalysis`
  Pydantic schema. The model is told exactly which JSON object to return, to
  not wrap it in Markdown fences, and to add no commentary around it.
- Career assets, context builders, prompts, and business logic remain
  provider-neutral; only the adapter knows about DeepSeek.

Example `.env`:

```
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-v4-flash
LLM_REASONING_EFFORT=medium
LLM_TIMEOUT_SECONDS=120
LLM_MAX_RETRIES=2

DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com

VACANCY_ANALYSIS_BATCH_LIMIT=5
VACANCY_ANALYSIS_PROMPT_VERSION=vacancy-fit-v3

MASTER_CAREER_BRIEF_PATH=var/private/master-career-brief.docx
```

Commands:

```bash
python scripts/check_llm_provider.py   # minimal auth/response check (tiny cost)
python scripts/show_analysis_queue.py  # vacancies awaiting analysis (no LLM)
python scripts/analyze_vacancies.py    # run one bounded analysis batch
```

Switching providers requires configuration only:

```
LLM_PROVIDER=openai
```

or:

```
LLM_PROVIDER=deepseek
```

No career assets, context builders, prompt builders, schemas, vacancy
selection, or persistence logic change. Provider-qualified model names (for
example `deepseek:deepseek-v4-flash` or `openai:gpt-5-mini`) are stored in the
existing `analyses.model` column, so analyses from different providers coexist
without a schema change.

## Vacancy fit scoring v3

`vacancy-fit-v3` scoring separates professional fit from geographic and legal
eligibility:

- `overall_score` is **professional role fit before geography**. It ignores
  location, residency, work authorization, visa status, timezone, and
  employment arrangement, and reflects career-experience relevance, role
  scope, seniority, and domain alignment.
- `location_score` is **practical eligibility**: residency and authorization
  requirements, hybrid/onsite presence, country-specific remote restrictions,
  timezone, mandatory travel, and stated language requirements.
- `recommendation` combines both professional fit and eligibility. A vacancy
  may have high professional fit and low location fit at the same time.
- Location uncertainty is **not automatically rejection**. Confirmed blockers
  must be based on explicit JD language; unresolved eligibility is not `reject`.
- `technical_score` and `leadership_score` are geographic-independent and
  should stay stable for duplicate job descriptions advertised in different
  locations (normally within 3 points).
- Eligibility is expressed through `location_score`, `risks`, and `summary`
  wording such as "Confirmed location blocker", "Likely regional restriction",
  "Eligibility unresolved", or "Location appears compatible". No new database
  columns are added.

Example result for a strong professional match with a likely geographic
restriction:

```json
{
  "overall_score": 86,
  "technical_score": 82,
  "leadership_score": 93,
  "location_score": 15,
  "recommendation": "consider"
}
```

Interpretation:

- strong professional match
- likely geographic restriction
- worth human review before applying

## Vacancy shortlist

A read-only human-review layer over existing `vacancy-fit-v3` analyses. It
never calls an LLM and never modifies vacancy status.

```bash
python scripts/show_vacancy_shortlist.py
```

Only meaningful professional matches:

```bash
python scripts/show_vacancy_shortlist.py --min-score 60
```

Only `strong_match` and `consider`:

```bash
python scripts/show_vacancy_shortlist.py \
  --recommendation strong_match \
  --recommendation consider
```

Only review candidates:

```bash
python scripts/show_vacancy_shortlist.py --category REVIEW
```

JSON-lines for future integrations:

```bash
python scripts/show_vacancy_shortlist.py --format json
```

Options: `--limit` (1–200, default 50), `--min-score`, repeatable
`--recommendation`, `--category` (`PRIORITY` / `REVIEW` / `LOW_PRIORITY` /
`REJECT`), and `--format` (`text` / `json`). The shortlist is ordered by
`overall_score` descending, then recommendation priority (`strong_match` →
`consider` → `weak_match` → `reject`), then `location_score` descending, then
`first_seen_at` descending.

Categories:

- **PRIORITY** — strong professional and practical match.
- **REVIEW** — good professional fit but material gaps or eligibility
  uncertainty.
- **LOW_PRIORITY** — limited fit or important role mismatch.
- **REJECT** — fundamental mismatch or confirmed blocker.

Categories never change vacancy status.

Detailed vacancy (analysis for the configured prompt version and qualified
model):

```bash
python scripts/show_vacancy_details.py 4429016090
```

With the full normalized job description:

```bash
python scripts/show_vacancy_details.py 4429016090 --show-description
```

The detail script prints all stored analysis fields, the current vacancy
status, and the JD character count. The full job description is hidden by
default and only printed under `JOB DESCRIPTION` with `--show-description`.

## Structured output retry

When a provider returns output that is not valid structured output (malformed
JSON, schema-validation failure, empty response, Markdown-fenced JSON, trailing
prose), Statera makes **one corrective retry** before counting the vacancy as
failed.

- The retry repeats the **complete original context** (full Master Career
  Brief and full vacancy description) and appends a strict-JSON corrective
  instruction: exactly one JSON object, exact field names, integer scores, an
  allowed recommendation value, string arrays, no Markdown fences, no
  commentary, no omitted or extra fields.
- Maximum attempts per vacancy: **2** (initial attempt + one corrective
  retry).
- Only `LLMStructuredOutputError` triggers this retry. Authentication, quota
  (rate limit), timeout, configuration, generic provider, refusal, and
  context-size failures are **not** retried by this mechanism.
- A persistent structured-output failure leaves no analysis row and **remains
  in the analysis queue** for a future run.
- A validated retry creates **only one analysis row**; rerunning the batch
  stays idempotent.

Batch summaries now include `retried` (second requests sent) and
`recovered_after_retry` (vacancies successfully analyzed on the retry).

## Web review interface

A minimal read-only human-review web UI built on FastAPI + Jinja2. It shows
analyzed vacancies (list + detail) and lets you change their review status
via POST-only forms. No LLM calls and no LinkedIn data collection happen from
HTTP requests, and there is **no authentication yet** — run it only on
`127.0.0.1`.

- **List** (`GET /vacancies`): status tabs (New / Selected / Ignored /
  Applied / All), filters (category, recommendation, minimum overall score),
  sorting (overall, leadership, technical, location, newest), pagination, and
  per-status counts in the top bar. Category (PRIORITY / REVIEW /
  LOW_PRIORITY / REJECT) is derived from the same `classify_scores` rules as
  the shortlist.
- **Detail** (`GET /vacancies/{external_id}`): full scores, recommendation,
  summary, strengths / weaknesses / risks, and the job description
  (collapsed, with a character count).
- **Status mutation** (`POST /vacancies/{external_id}/status`): allowed
  transitions are enforced server-side (`new → selected|ignored`,
  `selected → new|ignored|applied`, `ignored → new|selected`,
  `applied → selected`). Forbidden transitions return `409`. The applied
  action is guarded by a client-side confirm dialog. After mutation the
  server redirects with HTTP `303` to a safe local path (open-redirect
  inputs fall back to the list page).
- **Scores are never edited** from the web UI; analysis rows are read-only.

Run locally:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/vacancies>.

