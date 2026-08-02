"""Tests for vacancy-content persistence and description-fetch batch.

Uses an in-memory SQLite database with only the tables required by these
tests; LinkedIn fetching is replaced at the narrow service boundary.
"""

import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.vacancy_content as service
from app.db.base import Base
from app.db.models.job_source import JobSource
from app.db.models.search import Search
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.sources.linkedin.description import (
    LinkedInJobDescription,
    calculate_content_hash,
    normalize_job_description,
)


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
            Vacancy.__table__,
            VacancyContent.__table__,
        ],
    )
    db = sessionmaker(bind=engine, autoflush=True, autocommit=False)()
    yield db
    db.close()
    engine.dispose()


def _source_and_search(db):
    source = JobSource(code="linkedin", name="LinkedIn", enabled=True)
    db.add(source)
    db.flush()
    search = Search(
        source_id=source.id,
        name="LinkedIn saved search",
        url="https://www.linkedin.com/jobs/search/?keywords=python",
        enabled=True,
    )
    db.add(search)
    db.flush()
    return source, search


def _vacancy(db, external_id, source, search, status="new"):
    vacancy = Vacancy(
        source_id=source.id,
        search_id=search.id,
        external_id=external_id,
        url=f"https://www.linkedin.com/jobs/view/{external_id}/",
        title=f"Job {external_id}",
        status=status,
    )
    db.add(vacancy)
    db.flush()
    return vacancy


def _description(external_id, raw_text):
    return LinkedInJobDescription(
        external_id=external_id,
        raw_text=raw_text,
        markdown=None,
        source_url=f"https://www.linkedin.com/jobs/view/{external_id}/",
    )


def _long(text: str) -> str:
    return text + " " + "x" * 300


def _content_rows(db, vacancy_id):
    return list(
        db.scalars(
            select(VacancyContent).where(VacancyContent.vacancy_id == vacancy_id)
        )
    )


# --- upsert_current_vacancy_content -----------------------------------------


def test_first_upsert_creates_row_version_1(session) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    desc = _description("1", _long("About the job\n\nDescription."))

    result = service.upsert_current_vacancy_content(session, vacancy, desc)

    assert result.created is True
    assert result.updated is False and result.unchanged is False
    rows = _content_rows(session, vacancy.id)
    assert len(rows) == 1
    assert rows[0].version == 1
    assert rows[0].raw_text == normalize_job_description(desc.raw_text)
    assert rows[0].content_hash == calculate_content_hash(desc.raw_text)


def test_identical_content_is_unchanged(session) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    desc = _description("1", _long("Same description"))
    service.upsert_current_vacancy_content(session, vacancy, desc)

    result = service.upsert_current_vacancy_content(session, vacancy, desc)

    assert result.unchanged is True
    assert result.created is False and result.updated is False
    assert len(_content_rows(session, vacancy.id)) == 1


def test_changed_content_updates_same_row(session) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    service.upsert_current_vacancy_content(
        session, vacancy, _description("1", _long("Old"))
    )

    result = service.upsert_current_vacancy_content(
        session, vacancy, _description("1", _long("New"))
    )

    assert result.updated is True
    rows = _content_rows(session, vacancy.id)
    assert len(rows) == 1  # same row, no history
    assert rows[0].version == 1
    assert rows[0].raw_text == normalize_job_description(_long("New"))


def test_fetched_at_advances_on_unchanged(session) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    desc = _description("1", _long("Same"))
    service.upsert_current_vacancy_content(session, vacancy, desc)
    first = _content_rows(session, vacancy.id)[0].fetched_at

    time.sleep(0.02)
    service.upsert_current_vacancy_content(session, vacancy, desc)
    second = _content_rows(session, vacancy.id)[0].fetched_at
    assert second > first


def test_raw_text_normalized_before_persistence(session) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    raw = "Line one  \r\nLine two\r\n\r\n\r\n\r\n"

    service.upsert_current_vacancy_content(session, vacancy, _description("1", raw))

    row = _content_rows(session, vacancy.id)[0]
    assert row.raw_text == normalize_job_description(raw)


def test_multiple_content_rows_raise(session) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    session.add(
        VacancyContent(vacancy_id=vacancy.id, version=1, content_hash="a" * 64, raw_text="one")
    )
    session.add(
        VacancyContent(vacancy_id=vacancy.id, version=2, content_hash="b" * 64, raw_text="two")
    )
    session.flush()

    with pytest.raises(RuntimeError):
        service.upsert_current_vacancy_content(
            session, vacancy, _description("1", _long("new"))
        )


# --- fetch_missing_vacancy_descriptions (selection + batch) -----------------


def _fake_fetch(external_id, storage_state_path, debug_pause=False):
    return _description(external_id, _long(f"description for {external_id}"))


def test_vacancy_without_content_is_selected(session, monkeypatch) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    monkeypatch.setattr(service, "fetch_linkedin_job_description", _fake_fetch)

    result = service.fetch_missing_vacancy_descriptions(
        session, storage_state_path=Path("/nonexistent"), limit=5
    )

    assert result.selected == 1
    assert result.fetched == 1
    assert result.created == 1
    assert len(_content_rows(session, vacancy.id)) == 1


def test_vacancy_with_content_not_selected(session, monkeypatch) -> None:
    source, search = _source_and_search(session)
    vacancy = _vacancy(session, "1", source, search)
    session.add(
        VacancyContent(vacancy_id=vacancy.id, version=1, content_hash="a" * 64, raw_text="exists")
    )
    session.flush()
    monkeypatch.setattr(service, "fetch_linkedin_job_description", _fake_fetch)

    result = service.fetch_missing_vacancy_descriptions(
        session, storage_state_path=Path("/nonexistent"), limit=5
    )

    assert result.selected == 0
    assert len(_content_rows(session, vacancy.id)) == 1


def test_ignored_vacancy_not_selected(session, monkeypatch) -> None:
    source, search = _source_and_search(session)
    _vacancy(session, "1", source, search, status="ignored")
    monkeypatch.setattr(service, "fetch_linkedin_job_description", _fake_fetch)

    result = service.fetch_missing_vacancy_descriptions(
        session, storage_state_path=Path("/nonexistent"), limit=5
    )

    assert result.selected == 0


def test_expired_vacancy_not_selected(session, monkeypatch) -> None:
    source, search = _source_and_search(session)
    _vacancy(session, "1", source, search, status="expired")
    monkeypatch.setattr(service, "fetch_linkedin_job_description", _fake_fetch)

    result = service.fetch_missing_vacancy_descriptions(
        session, storage_state_path=Path("/nonexistent"), limit=5
    )

    assert result.selected == 0


def test_batch_limit_respected(session, monkeypatch) -> None:
    source, search = _source_and_search(session)
    _vacancy(session, "1", source, search)
    _vacancy(session, "2", source, search)
    _vacancy(session, "3", source, search)
    monkeypatch.setattr(service, "fetch_linkedin_job_description", _fake_fetch)

    result = service.fetch_missing_vacancy_descriptions(
        session, storage_state_path=Path("/nonexistent"), limit=2
    )

    assert result.selected == 2
    assert result.fetched == 2
    assert result.created == 2
    assert session.scalar(select(func.count()).select_from(VacancyContent)) == 2


def test_failed_fetch_keeps_previous_successes(session, monkeypatch) -> None:
    source, search = _source_and_search(session)
    _vacancy(session, "1", source, search)
    _vacancy(session, "2", source, search)
    _vacancy(session, "3", source, search)

    def flaky_fetch(external_id, storage_state_path, debug_pause=False):
        if external_id == "2":
            raise RuntimeError("boom")
        return _description(external_id, _long(f"desc {external_id}"))

    monkeypatch.setattr(service, "fetch_linkedin_job_description", flaky_fetch)

    result = service.fetch_missing_vacancy_descriptions(
        session, storage_state_path=Path("/nonexistent"), limit=5
    )

    assert result.selected == 3
    assert result.failed == 1
    assert result.fetched == 2
    assert result.created == 2

    for external_id in ("1", "2", "3"):
        vacancy = session.scalar(
            select(Vacancy).where(Vacancy.external_id == external_id)
        )
        rows = _content_rows(session, vacancy.id)
        if external_id == "2":
            assert rows == []
        else:
            assert len(rows) == 1

    # The outer transaction still commits the successful vacancies.
    session.commit()
    assert session.scalar(select(func.count()).select_from(VacancyContent)) == 2
