"""Tests for the vacancy shortlist service.

Pure helper tests plus SQLite-backed query tests. No live Yandex PostgreSQL,
no LinkedIn, and no LLM calls.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.analysis import Analysis
from app.db.models.company import Company
from app.db.models.job_source import JobSource
from app.db.models.search import Search
from app.db.models.vacancy import Vacancy
from app.services.vacancy_shortlist import (
    LOW_PRIORITY,
    PRIORITY,
    REJECT,
    REVIEW,
    VacancyShortlistItem,
    classify_shortlist_item,
    compact_summary,
    get_vacancy_shortlist,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(element, compiler, **kw):
    """Render PostgreSQL JSONB as plain JSON on the in-memory SQLite schema."""
    return "JSON"


QUALIFIED = "deepseek:deepseek-v4-flash"
PROMPT = "vacancy-fit-v3"


def _item(**overrides):
    base = dict(
        external_id="1001",
        title="Support Lead",
        company="Acme",
        location="Remote",
        source_url="https://www.linkedin.com/jobs/view/1001/",
        overall_score=80,
        technical_score=75,
        leadership_score=70,
        location_score=60,
        recommendation="consider",
        summary="Strong professional fit with clear evidence in the brief.",
        strengths=["Direct people leadership"],
        weaknesses=["No billing analytics"],
        risks=["Eligibility unresolved"],
        first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        analysis_created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        model=QUALIFIED,
        prompt_version=PROMPT,
    )
    base.update(overrides)
    return VacancyShortlistItem(**base)


# --- classify_shortlist_item ---


def test_category_priority():
    item = _item(overall_score=85, location_score=75, recommendation="strong_match")
    assert classify_shortlist_item(item) == PRIORITY


def test_category_review_for_high_fit_low_location():
    item = _item(overall_score=82, location_score=20, recommendation="consider")
    assert classify_shortlist_item(item) == REVIEW


def test_category_review_for_strong_high_fit_low_location():
    item = _item(overall_score=85, location_score=15, recommendation="strong_match")
    assert classify_shortlist_item(item) == REVIEW


def test_category_low_priority_for_weak_match():
    item = _item(overall_score=62, location_score=15, recommendation="weak_match")
    assert classify_shortlist_item(item) == LOW_PRIORITY


def test_category_low_priority_for_low_overall():
    item = _item(overall_score=45, recommendation="consider")
    assert classify_shortlist_item(item) == LOW_PRIORITY


def test_category_reject_for_reject_recommendation():
    item = _item(overall_score=30, recommendation="reject")
    assert classify_shortlist_item(item) == REJECT


def test_category_reject_for_very_low_overall():
    item = _item(overall_score=30, recommendation="strong_match")
    assert classify_shortlist_item(item) == REJECT


def test_classify_is_deterministic():
    item = _item(overall_score=82, location_score=20, recommendation="consider")
    assert classify_shortlist_item(item) == classify_shortlist_item(item)


# --- compact_summary ---


def test_compact_summary_collapses_whitespace_without_truncation():
    text = "  Strong   match.\n  Clear   evidence.  "
    result = compact_summary(text, maximum_characters=500)
    assert result == "Strong match. Clear evidence."


def test_compact_summary_truncates_with_ellipsis():
    long_text = "word " * 200  # ~1000 chars
    result = compact_summary(long_text, maximum_characters=500)
    assert len(result) <= 503
    assert result.endswith("...")


def test_compact_summary_preserves_sentence_boundary_when_practical():
    text = "First sentence ends here. " + ("x" * 400)
    result = compact_summary(text, maximum_characters=300)
    assert result.startswith("First sentence ends here.")
    assert result.endswith("...")


def test_compact_summary_never_modifies_input():
    original = "  A  B  "
    compact_summary(original, maximum_characters=500)
    assert original == "  A  B  "


# --- get_vacancy_shortlist (SQLite) ---


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
            Analysis.__table__,
        ],
    )
    db = sessionmaker(bind=engine, autoflush=True, autocommit=False)()
    yield db
    db.close()
    engine.dispose()


def _make_source(db):
    source = db.scalar(select(JobSource).where(JobSource.code == "linkedin"))
    if source is not None:
        return source
    source = JobSource(code="linkedin", name="LinkedIn", enabled=True)
    db.add(source)
    db.flush()
    return source


def _make_company(db, name):
    company = db.scalar(
        select(Company).where(Company.normalized_name == name.lower())
    )
    if company is not None:
        return company
    company = Company(name=name, normalized_name=name.lower())
    db.add(company)
    db.flush()
    return company


def _seed(
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
    model=QUALIFIED,
    prompt_version=PROMPT,
    first_seen=None,
):
    source = _make_source(db)
    company_id = None
    if company is not None:
        company_id = _make_company(db, company).id
    vacancy = Vacancy(
        source_id=source.id,
        external_id=external_id,
        url=f"https://www.linkedin.com/jobs/view/{external_id}/",
        title=f"Job {external_id}",
        location=location,
        status=status,
        company_id=company_id,
        first_seen_at=first_seen or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(vacancy)
    db.flush()
    db.add(
        Analysis(
            vacancy_id=vacancy.id,
            vacancy_content_id=uuid.uuid4(),
            model=model,
            prompt_version=prompt_version,
            overall_score=overall,
            technical_score=technical,
            leadership_score=leadership,
            location_score=location_score,
            summary=f"Summary for {external_id} with clear evidence.",
            strengths=[f"strength-{external_id}"],
            weaknesses=[f"weakness-{external_id}"],
            risks=[f"risk-{external_id}"],
            recommendation=recommendation,
        )
    )
    db.flush()
    return vacancy


def _ids(items):
    return [item.external_id for item in items]


def test_matching_prompt_version_only(session):
    _seed(session, "2001", prompt_version=PROMPT)
    _seed(session, "2002", prompt_version="vacancy-fit-v2")

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    assert _ids(items) == ["2001"]


def test_matching_qualified_model_only(session):
    _seed(session, "2003", model=QUALIFIED)
    _seed(session, "2004", model="openai:gpt-5-mini")

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    assert _ids(items) == ["2003"]


def test_ignored_and_expired_vacancies_excluded(session):
    _seed(session, "2005", status="new")
    _seed(session, "2006", status="ignored")
    _seed(session, "2007", status="expired")

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    assert _ids(items) == ["2005"]


def test_recommendation_ordering(session):
    _seed(session, "3001", overall=70, recommendation="strong_match")
    _seed(session, "3002", overall=70, recommendation="reject")
    _seed(session, "3003", overall=70, recommendation="consider")
    _seed(session, "3004", overall=70, recommendation="weak_match")

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    assert _ids(items) == ["3001", "3003", "3004", "3002"]


def test_overall_score_ordering(session):
    _seed(session, "3005", overall=90, recommendation="consider")
    _seed(session, "3006", overall=70, recommendation="consider")

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    assert _ids(items) == ["3005", "3006"]


def test_location_score_is_not_primary_ranking_field(session):
    _seed(session, "3007", overall=90, location_score=10)
    _seed(session, "3008", overall=80, location_score=90)

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    # Higher overall ranks first even though its location score is lower.
    assert _ids(items) == ["3007", "3008"]


def test_null_company_and_location_handled(session):
    _seed(session, "3009", company=None, location=None)

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    assert items[0].company is None
    assert items[0].location is None


def test_limit_respected(session):
    for index in range(5):
        _seed(session, f"400{index}")

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED, limit=2)

    assert len(items) == 2


def test_limit_validation(session):
    with pytest.raises(ValueError):
        get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED, limit=0)
    with pytest.raises(ValueError):
        get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED, limit=201)


def test_minimum_overall_score_filter(session):
    _seed(session, "5001", overall=80)
    _seed(session, "5002", overall=50)

    items = get_vacancy_shortlist(
        session, prompt_version=PROMPT, qualified_model=QUALIFIED, minimum_overall_score=60
    )

    assert _ids(items) == ["5001"]


def test_recommendation_filter(session):
    _seed(session, "5003", recommendation="strong_match")
    _seed(session, "5004", recommendation="consider")
    _seed(session, "5005", recommendation="reject")

    items = get_vacancy_shortlist(
        session,
        prompt_version=PROMPT,
        qualified_model=QUALIFIED,
        recommendations={"strong_match", "consider"},
    )

    assert _ids(items) == ["5003", "5004"]


def test_invalid_recommendation_rejected(session):
    with pytest.raises(ValueError):
        get_vacancy_shortlist(
            session,
            prompt_version=PROMPT,
            qualified_model=QUALIFIED,
            recommendations={"nonsense"},
        )


def test_no_lazy_loading_after_session_closes(session):
    _seed(session, "6001", company="Acme")
    session.commit()

    items = get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)
    session.close()

    item = items[0]
    assert item.company == "Acme"
    assert item.strengths == ["strength-6001"]
    assert item.source_url == "https://www.linkedin.com/jobs/view/6001/"
    assert item.overall_score == 80
    assert item.analysis_created_at is not None


def test_shortlist_is_read_only(session):
    _seed(session, "6002")
    session.commit()
    before = session.scalar(select(func.count()).select_from(Analysis))

    get_vacancy_shortlist(session, prompt_version=PROMPT, qualified_model=QUALIFIED)

    assert session.scalar(select(func.count()).select_from(Analysis)) == before
