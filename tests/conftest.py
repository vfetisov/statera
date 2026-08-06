"""Shared fixtures for the web review interface tests.

Uses an in-memory SQLite database (StaticPool) with the app's dependency
``get_db`` overridden, so no live PostgreSQL or LLM is required. A ``seed``
helper commits vacancy + content + analysis rows that the HTTP routes then
render.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.models  # noqa: F401  (import registers every table on Base)
from app.db.base import Base
from app.db.models.analysis import Analysis
from app.db.models.company import Company
from app.db.models.job_source import JobSource
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.db.session import get_db
from app.main import app

QUALIFIED = "deepseek:deepseek-v4-flash"
PROMPT = "vacancy-fit-v3"
DEFAULT_JD = (
    "Senior Software Engineer role. Responsibilities include building "
    "distributed systems, mentoring engineers, and shipping high-quality code."
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(element, compiler, **kw):
    """Render JSONB columns as SQLite JSON so the models compile there."""
    return "JSON"


def _make_source(db):
    source = (
        db.query(JobSource).filter(JobSource.code == "linkedin").one_or_none()
    )
    if source is None:
        source = JobSource(code="linkedin", name="LinkedIn")
        db.add(source)
        db.flush()
    return source


def _make_company(db, name):
    normalized = name.strip().lower().replace(" ", "-")
    company = (
        db.query(Company).filter(Company.normalized_name == normalized).one_or_none()
    )
    if company is None:
        company = Company(name=name, normalized_name=normalized)
        db.add(company)
        db.flush()
    return company


def seed_vacancy(
    db,
    external_id,
    *,
    status="new",
    company="Acme",
    location="Remote",
    overall=80,
    technical=75,
    leadership=70,
    location_score=60,
    recommendation="consider",
    strengths=None,
    weaknesses=None,
    risks=None,
    summary=None,
    jd_text=DEFAULT_JD,
    prompt_version=PROMPT,
    model=QUALIFIED,
    first_seen=None,
):
    """Insert a vacancy with one content version and one matching analysis."""
    source = _make_source(db)
    company_obj = _make_company(db, company)
    first_seen = first_seen or datetime(2026, 1, 1, tzinfo=timezone.utc)
    vacancy = Vacancy(
        source_id=source.id,
        external_id=external_id,
        url=f"https://www.linkedin.com/jobs/view/{external_id}/",
        title=f"Job {external_id}",
        location=location,
        status=status,
        first_seen_at=first_seen,
    )
    vacancy.company_id = company_obj.id
    db.add(vacancy)
    db.flush()

    content = VacancyContent(
        vacancy_id=vacancy.id,
        version=1,
        content_hash=jd_text,
        raw_text=jd_text,
    )
    db.add(content)
    db.flush()

    analysis = Analysis(
        vacancy_id=vacancy.id,
        vacancy_content_id=content.id,
        model=model,
        prompt_version=prompt_version,
        overall_score=overall,
        technical_score=technical,
        leadership_score=leadership,
        location_score=location_score,
        recommendation=recommendation,
        summary=summary or f"Summary for {external_id}",
        strengths=strengths or ["Strong backend experience", "Scalable systems"],
        weaknesses=weaknesses or ["No fintech domain knowledge"],
        risks=risks or ["On-site requirement"],
    )
    db.add(analysis)
    db.flush()
    return vacancy


@pytest.fixture()
def web_app(monkeypatch):
    """Yields ``(client, session_factory, app, seed)`` for the review UI."""
    # Pin the configured analysis prompt/model so the routes always match the
    # seeded data, regardless of any local .env overrides.
    from app.config import settings

    monkeypatch.setattr(settings, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(settings, "LLM_MODEL", "deepseek-v4-flash")
    monkeypatch.setattr(settings, "VACANCY_ANALYSIS_PROMPT_VERSION", PROMPT)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=True, autocommit=False)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    def seed(**kwargs):
        db = session_factory()
        try:
            vacancy = seed_vacancy(db, **kwargs)
            db.commit()
            return vacancy
        finally:
            db.close()

    with TestClient(app) as client:
        yield client, session_factory, app, seed

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture()
def service_env(web_app):
    """Yields ``(db, seed)`` for direct service-layer tests."""
    _, session_factory, _, seed = web_app
    db = session_factory()
    try:
        yield db, seed
    finally:
        db.close()
