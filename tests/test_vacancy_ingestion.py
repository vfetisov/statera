"""Tests for vacancy ingestion.

Uses an in-memory SQLite database with only the tables required by ingestion
(job_sources, searches, companies, vacancies); no LinkedIn access is needed.
"""

import time

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.vacancy_ingestion as ingestion
from app.db.base import Base
from app.db.models.company import Company
from app.db.models.job_source import JobSource
from app.db.models.search import Search
from app.db.models.vacancy import Vacancy
from app.sources.linkedin.smoke import LinkedInJobPreview

SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords=python"


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            JobSource.__table__,
            Search.__table__,
            Company.__table__,
            Vacancy.__table__,
        ],
    )
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield db
    db.close()
    engine.dispose()


def _preview(
    external_id: str | None,
    title: str | None = "Title",
    company: str | None = None,
    location: str | None = None,
    url: str | None = None,
) -> LinkedInJobPreview:
    return LinkedInJobPreview(
        external_id=external_id,
        title=title,
        company=company,
        location=location,
        url=url
        or (f"https://www.linkedin.com/jobs/view/{external_id}/" if external_id else None),
    )


def _vacancy_by_external(db, external_id: str) -> Vacancy:
    return db.scalar(select(Vacancy).where(Vacancy.external_id == external_id))


def test_normalize_company_name() -> None:
    assert ingestion.normalize_company_name("Ashby") == "ashby"
    assert ingestion.normalize_company_name("  Instrumental   Inc. ") == "instrumental inc."
    assert ingestion.normalize_company_name("Google") == "google"
    assert ingestion.normalize_company_name("") == ""


def test_deduplicates_input_and_skips_invalid(session) -> None:
    previews = [
        _preview("1", title="First"),
        _preview("1", title="Duplicate"),
        _preview(None, title="No id"),
        _preview("2", title=None),
    ]
    result = ingestion.ingest_linkedin_previews(session, SEARCH_URL, previews)
    session.commit()

    assert result.vacancies_created == 1
    assert result.vacancies_updated == 0
    assert result.vacancies_unchanged == 0
    assert _vacancy_by_external(session, "1").title == "First"


def test_source_created_once(session) -> None:
    result1 = ingestion.ingest_linkedin_previews(session, SEARCH_URL, [_preview("1")])
    session.commit()
    result2 = ingestion.ingest_linkedin_previews(session, SEARCH_URL, [_preview("2")])
    session.commit()

    assert result1.source_created is True
    assert result2.source_created is False
    assert session.scalar(select(func.count()).select_from(JobSource)) == 1


def test_search_reused(session) -> None:
    result1 = ingestion.ingest_linkedin_previews(session, SEARCH_URL, [_preview("1")])
    session.commit()
    result2 = ingestion.ingest_linkedin_previews(session, SEARCH_URL, [_preview("2")])
    session.commit()

    assert result1.search_created is True
    assert result2.search_created is False
    assert session.scalar(select(func.count()).select_from(Search)) == 1


def test_company_created_and_reused_by_normalized_name(session) -> None:
    result1 = ingestion.ingest_linkedin_previews(
        session, SEARCH_URL, [_preview("1", company="  Instrumental   Inc. ")]
    )
    session.commit()
    result2 = ingestion.ingest_linkedin_previews(
        session, SEARCH_URL, [_preview("2", company="instrumental   inc.")]
    )
    session.commit()

    assert result1.companies_created == 1
    assert result2.companies_created == 0
    company = session.scalar(select(Company))
    assert company.normalized_name == "instrumental inc."
    assert company.name == "Instrumental   Inc."  # original trimmed, not overwritten
    assert session.scalar(select(func.count()).select_from(Company)) == 1


def test_first_ingestion_creates_vacancies(session) -> None:
    previews = [
        _preview("1", title="A", company="Acme", location="Remote"),
        _preview("2", title="B", company="Globex", location="Berlin"),
    ]
    result = ingestion.ingest_linkedin_previews(session, SEARCH_URL, previews)
    session.commit()

    assert result.vacancies_created == 2
    assert result.vacancies_updated == 0
    assert result.vacancies_unchanged == 0


def test_second_identical_ingestion_is_unchanged(session) -> None:
    previews = [
        _preview("1", title="A", company="Acme", location="Remote"),
        _preview("2", title="B", company="Globex", location="Berlin"),
    ]
    ingestion.ingest_linkedin_previews(session, SEARCH_URL, previews)
    session.commit()

    result = ingestion.ingest_linkedin_previews(session, SEARCH_URL, previews)
    session.commit()

    assert result.vacancies_created == 0
    assert result.vacancies_updated == 0
    assert result.vacancies_unchanged == 2


def test_changed_title_or_location_counts_as_updated(session) -> None:
    ingestion.ingest_linkedin_previews(
        session,
        SEARCH_URL,
        [_preview("1", title="Old Title", company="Acme", location="Remote")],
    )
    session.commit()

    result = ingestion.ingest_linkedin_previews(
        session,
        SEARCH_URL,
        [_preview("1", title="New Title", company="Acme", location="New York, NY")],
    )
    session.commit()

    assert result.vacancies_updated == 1
    vacancy = _vacancy_by_external(session, "1")
    assert vacancy.title == "New Title"
    assert vacancy.location == "New York, NY"


def test_first_seen_stable_and_last_seen_advances(session) -> None:
    ingestion.ingest_linkedin_previews(session, SEARCH_URL, [_preview("1", company="Acme")])
    session.commit()
    first1 = _vacancy_by_external(session, "1").first_seen_at
    last1 = _vacancy_by_external(session, "1").last_seen_at

    time.sleep(0.02)
    ingestion.ingest_linkedin_previews(session, SEARCH_URL, [_preview("1", company="Acme")])
    session.commit()

    vacancy = _vacancy_by_external(session, "1")
    assert vacancy.first_seen_at == first1
    assert vacancy.last_seen_at > last1


def test_status_unchanged_on_update(session) -> None:
    ingestion.ingest_linkedin_previews(session, SEARCH_URL, [_preview("1", title="A")])
    session.commit()
    vacancy = _vacancy_by_external(session, "1")
    vacancy.status = "applied"
    session.commit()

    result = ingestion.ingest_linkedin_previews(
        session, SEARCH_URL, [_preview("1", title="B")]
    )
    session.commit()

    assert result.vacancies_updated == 1
    assert _vacancy_by_external(session, "1").status == "applied"


def test_company_none_leaves_company_id_nullable(session) -> None:
    result = ingestion.ingest_linkedin_previews(
        session, SEARCH_URL, [_preview("1", company=None)]
    )
    session.commit()

    assert result.companies_created == 0
    assert _vacancy_by_external(session, "1").company_id is None
