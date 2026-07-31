-- Statera initial database schema
--
-- Creates the base tables for job sources, saved searches, companies,
-- vacancies, vacancy content versions, and analyses.
--
-- Safe to run repeatedly on the same database:
--   * CREATE TABLE / INDEX ... IF NOT EXISTS
--   * no DROP or TRUNCATE statements
--   * no sample/seed data
--
-- Mirrors the SQLAlchemy models in app/db/models/.
--
-- UUIDs use gen_random_uuid(), which is built into PostgreSQL 13+ (this
-- project targets PostgreSQL 17) and does not require the pgcrypto extension.

-- ---------------------------------------------------------------------------
-- job_sources
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS job_sources (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code        VARCHAR(50)  NOT NULL,
    name        VARCHAR(100) NOT NULL,
    enabled     BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_job_sources_code UNIQUE (code)
);

-- ---------------------------------------------------------------------------
-- searches
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS searches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID         NOT NULL REFERENCES job_sources (id),
    name            VARCHAR(200) NOT NULL,
    url             TEXT         NOT NULL,
    enabled         BOOLEAN      NOT NULL DEFAULT TRUE,
    last_scanned_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- companies
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(250) NOT NULL,
    normalized_name VARCHAR(250) NOT NULL,
    website         TEXT,
    linkedin_url    TEXT,
    country         VARCHAR(100),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_companies_normalized_name UNIQUE (normalized_name)
);

-- ---------------------------------------------------------------------------
-- vacancies
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vacancies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       UUID         NOT NULL REFERENCES job_sources (id),
    search_id       UUID         REFERENCES searches (id),
    company_id      UUID         REFERENCES companies (id),
    external_id     VARCHAR(250) NOT NULL,
    url             TEXT         NOT NULL,
    title           VARCHAR(300) NOT NULL,
    location        VARCHAR(250),
    remote_type     VARCHAR(50),
    employment_type VARCHAR(50),
    salary_min      NUMERIC,
    salary_max      NUMERIC,
    salary_currency VARCHAR(10),
    posted_at       TIMESTAMPTZ,
    first_seen_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status          VARCHAR(50)  NOT NULL DEFAULT 'new',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_vacancies_source_external UNIQUE (source_id, external_id)
);

CREATE INDEX IF NOT EXISTS ix_vacancies_status        ON vacancies (status);
CREATE INDEX IF NOT EXISTS ix_vacancies_first_seen_at ON vacancies (first_seen_at);
CREATE INDEX IF NOT EXISTS ix_vacancies_company_id    ON vacancies (company_id);

-- ---------------------------------------------------------------------------
-- vacancy_contents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vacancy_contents (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vacancy_id        UUID         NOT NULL REFERENCES vacancies (id) ON DELETE CASCADE,
    version           INTEGER      NOT NULL,
    content_hash      VARCHAR(64)  NOT NULL,
    raw_text          TEXT,
    markdown          TEXT,
    html_artifact_key TEXT,
    fetched_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT uq_vacancy_contents_vacancy_version UNIQUE (vacancy_id, version),
    CONSTRAINT uq_vacancy_contents_vacancy_hash   UNIQUE (vacancy_id, content_hash)
);

-- ---------------------------------------------------------------------------
-- analyses
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analyses (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vacancy_id         UUID         NOT NULL REFERENCES vacancies (id) ON DELETE CASCADE,
    vacancy_content_id UUID         NOT NULL REFERENCES vacancy_contents (id) ON DELETE CASCADE,
    model              VARCHAR(100) NOT NULL,
    prompt_version     VARCHAR(100) NOT NULL,
    overall_score      INTEGER,
    technical_score    INTEGER,
    leadership_score   INTEGER,
    location_score     INTEGER,
    summary            TEXT,
    strengths          JSONB,
    weaknesses         JSONB,
    risks              JSONB,
    recommendation     VARCHAR(50),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT ck_analyses_overall_score_range
        CHECK (overall_score IS NULL OR (overall_score >= 0 AND overall_score <= 100)),
    CONSTRAINT ck_analyses_technical_score_range
        CHECK (technical_score IS NULL OR (technical_score >= 0 AND technical_score <= 100)),
    CONSTRAINT ck_analyses_leadership_score_range
        CHECK (leadership_score IS NULL OR (leadership_score >= 0 AND leadership_score <= 100)),
    CONSTRAINT ck_analyses_location_score_range
        CHECK (location_score IS NULL OR (location_score >= 0 AND location_score <= 100))
);
