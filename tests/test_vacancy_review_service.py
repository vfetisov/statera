"""Service-layer tests for the review interface (SQLite, no LLM, no live DB)."""

import pytest
from sqlalchemy import select

from app.db.models.vacancy import Vacancy
from app.services.vacancy_review import (
    InvalidVacancyStatusTransition,
    VacancyNotFoundError,
    count_vacancies_by_status,
    get_review_vacancies,
    get_review_vacancy,
    set_vacancy_review_status,
)

QUALIFIED = "deepseek:deepseek-v4-flash"
PROMPT = "vacancy-fit-v3"


def _seed_many(seed, specs):
    """Seed several vacancies with (external_id, **kwargs) tuples."""
    for external_id, kwargs in specs:
        seed(external_id=external_id, **kwargs)


def test_list_sorted_by_overall_desc(service_env):
    db, seed = service_env
    _seed_many(seed, [
        ("1", {"overall": 50}),
        ("2", {"overall": 90}),
        ("3", {"overall": 70}),
    ])
    db.expire_all()

    page = get_review_vacancies(
        db, prompt_version=PROMPT, qualified_model=QUALIFIED, page_size=10
    )
    assert [item.external_id for item in page.items] == ["2", "3", "1"]
    assert page.total_items == 3


def test_list_filters_by_status(service_env):
    db, seed = service_env
    seed(external_id="1", status="new")
    seed(external_id="2", status="selected")
    db.expire_all()

    page = get_review_vacancies(
        db,
        prompt_version=PROMPT,
        qualified_model=QUALIFIED,
        status="selected",
        page_size=10,
    )
    assert [item.external_id for item in page.items] == ["2"]


def test_list_filters_by_category(service_env):
    db, seed = service_env
    seed(external_id="1", recommendation="strong_match", overall=85, location_score=70)
    seed(external_id="2", recommendation="reject", overall=90)
    db.expire_all()

    page = get_review_vacancies(
        db,
        prompt_version=PROMPT,
        qualified_model=QUALIFIED,
        category="PRIORITY",
        page_size=10,
    )
    assert [item.external_id for item in page.items] == ["1"]

    page = get_review_vacancies(
        db,
        prompt_version=PROMPT,
        qualified_model=QUALIFIED,
        category="REJECT",
        page_size=10,
    )
    assert [item.external_id for item in page.items] == ["2"]


def test_list_filters_by_recommendation(service_env):
    db, seed = service_env
    seed(external_id="1", recommendation="consider")
    seed(external_id="2", recommendation="weak_match")
    db.expire_all()

    page = get_review_vacancies(
        db,
        prompt_version=PROMPT,
        qualified_model=QUALIFIED,
        recommendation="weak_match",
        page_size=10,
    )
    assert [item.external_id for item in page.items] == ["2"]


def test_list_filters_by_minimum_score(service_env):
    db, seed = service_env
    seed(external_id="1", overall=45)
    seed(external_id="2", overall=80)
    db.expire_all()

    page = get_review_vacancies(
        db,
        prompt_version=PROMPT,
        qualified_model=QUALIFIED,
        minimum_score=60,
        page_size=10,
    )
    assert [item.external_id for item in page.items] == ["2"]


def test_list_pagination(service_env):
    db, seed = service_env
    for i in range(5):
        seed(external_id=str(i + 1), overall=100 - i)
    db.expire_all()

    page1 = get_review_vacancies(
        db, prompt_version=PROMPT, qualified_model=QUALIFIED, page=1, page_size=2
    )
    assert [item.external_id for item in page1.items] == ["1", "2"]
    assert page1.total_items == 5
    assert page1.total_pages == 3

    page3 = get_review_vacancies(
        db, prompt_version=PROMPT, qualified_model=QUALIFIED, page=3, page_size=2
    )
    assert [item.external_id for item in page3.items] == ["5"]


def test_list_item_fields(service_env):
    db, seed = service_env
    seed(
        external_id="42",
        recommendation="strong_match",
        overall=85,
        location_score=70,
        strengths=["A", "B", "C"],
    )
    db.expire_all()

    page = get_review_vacancies(
        db, prompt_version=PROMPT, qualified_model=QUALIFIED, page_size=10
    )
    item = page.items[0]
    assert item.category == "PRIORITY"
    assert item.external_id == "42"
    assert item.company == "Acme"
    assert item.source_url == "https://www.linkedin.com/jobs/view/42/"
    assert item.strengths == ["A", "B", "C"]


def test_list_rejects_bad_arguments(service_env):
    db, seed = service_env
    seed(external_id="1")
    db.expire_all()

    with pytest.raises(ValueError):
        get_review_vacancies(db, prompt_version=PROMPT, qualified_model=QUALIFIED, sort="bogus")
    with pytest.raises(ValueError):
        get_review_vacancies(db, prompt_version=PROMPT, qualified_model=QUALIFIED, page=0)
    with pytest.raises(ValueError):
        get_review_vacancies(db, prompt_version=PROMPT, qualified_model=QUALIFIED, page_size=0)
    with pytest.raises(ValueError):
        get_review_vacancies(db, prompt_version=PROMPT, qualified_model=QUALIFIED, status="bogus")
    with pytest.raises(ValueError):
        get_review_vacancies(db, prompt_version=PROMPT, qualified_model=QUALIFIED, category="bogus")
    with pytest.raises(ValueError):
        get_review_vacancies(db, prompt_version=PROMPT, qualified_model=QUALIFIED, minimum_score=101)


def test_detail_returns_full_payload(service_env):
    db, seed = service_env
    seed(external_id="7", jd_text="Full job description text here.", strengths=["A"])
    db.expire_all()

    detail = get_review_vacancy(
        db, external_id="7", prompt_version=PROMPT, qualified_model=QUALIFIED
    )
    assert detail is not None
    assert detail.title == "Job 7"
    assert detail.jd_text == "Full job description text here."
    assert detail.description_length == len("Full job description text here.")
    assert detail.model == QUALIFIED
    assert detail.prompt_version == PROMPT
    assert detail.strengths == ["A"]


def test_detail_returns_none_for_missing(service_env):
    db, seed = service_env
    seed(external_id="7")
    db.expire_all()

    assert get_review_vacancy(
        db, external_id="999", prompt_version=PROMPT, qualified_model=QUALIFIED
    ) is None
    # Non-numeric IDs never match.
    assert get_review_vacancy(
        db, external_id="abc", prompt_version=PROMPT, qualified_model=QUALIFIED
    ) is None


def test_set_status_valid_transition(service_env):
    db, seed = service_env
    seed(external_id="1", status="new")
    db.expire_all()

    # The mutation is applied to the ORM object without a commit.
    set_vacancy_review_status(db, external_id="1", status="selected")
    loaded = db.scalar(select(Vacancy).where(Vacancy.external_id == "1"))
    assert loaded is not None
    assert loaded.status == "selected"


def test_set_status_rejects_forbidden_transition(service_env):
    db, seed = service_env
    seed(external_id="1", status="new")
    db.expire_all()

    with pytest.raises(InvalidVacancyStatusTransition) as excinfo:
        set_vacancy_review_status(db, external_id="1", status="applied")
    assert excinfo.value.current_status == "new"
    assert excinfo.value.requested_status == "applied"


def test_set_status_missing_vacancy(service_env):
    db, seed = service_env
    with pytest.raises(VacancyNotFoundError):
        set_vacancy_review_status(db, external_id="999", status="selected")


def test_set_status_rejects_non_numeric_id(service_env):
    db, seed = service_env
    with pytest.raises(ValueError):
        set_vacancy_review_status(db, external_id="abc", status="selected")


def test_set_status_rejects_bad_status(service_env):
    db, seed = service_env
    seed(external_id="1")
    db.expire_all()
    with pytest.raises(ValueError):
        set_vacancy_review_status(db, external_id="1", status="bogus")


def test_count_vacancies_by_status(service_env):
    db, seed = service_env
    seed(external_id="1", status="new")
    seed(external_id="2", status="new")
    seed(external_id="3", status="selected")
    seed(external_id="4", status="ignored")
    db.expire_all()

    counts = count_vacancies_by_status(
        db, prompt_version=PROMPT, qualified_model=QUALIFIED
    )
    assert counts == {"new": 2, "selected": 1, "ignored": 1, "applied": 0}
