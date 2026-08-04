"""Tests for the analysis-queue script (SQLite, no LLM, no live database).

The script module is loaded from disk; its ``settings`` and ``SessionLocal``
are replaced so the queue query runs against an in-memory SQLite database. The
query returns display-ready scalar rows, so serialization must never require a
lazy relationship load after the session closes.
"""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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
from app.db.models.vacancy_content import VacancyContent


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(element, compiler, **kw):
    """Render PostgreSQL JSONB as plain JSON on the in-memory SQLite schema."""
    return "JSON"


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
DESCRIPTION = "A reasonably long full job description used to compute length."


def _load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_settings(**overrides):
    base = {
        "LLM_PROVIDER": "openai",
        "LLM_MODEL": "gpt-5-mini",
        "VACANCY_ANALYSIS_PROMPT_VERSION": "vacancy-fit-v1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def queue_env(monkeypatch):
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
            VacancyContent.__table__,
            Analysis.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=True, autocommit=False)

    module = _load_script("show_analysis_queue")
    monkeypatch.setattr(module, "SessionLocal", session_factory)
    monkeypatch.setattr(module, "settings", _fake_settings())
    yield module, session_factory
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


def _seed_vacancy(
    db,
    external_id,
    *,
    status="new",
    company="Acme",
    location="Remote",
    raw_text=DESCRIPTION,
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
        first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(vacancy)
    db.flush()
    content = VacancyContent(
        vacancy_id=vacancy.id,
        version=1,
        content_hash=raw_text,
        raw_text=raw_text,
        markdown=raw_text,
    )
    db.add(content)
    db.flush()
    return vacancy


def _seed_analysis(
    db,
    vacancy,
    qualified="openai:gpt-5-mini",
    prompt_version="vacancy-fit-v1",
):
    content = db.scalar(
        select(VacancyContent).where(VacancyContent.vacancy_id == vacancy.id)
    )
    db.add(
        Analysis(
            vacancy_id=vacancy.id,
            vacancy_content_id=content.id,
            model=qualified,
            prompt_version=prompt_version,
            overall_score=50,
            technical_score=50,
            leadership_score=50,
            location_score=50,
            summary="existing analysis",
            strengths=["old"],
            weaknesses=["old"],
            risks=["old"],
            recommendation="consider",
        )
    )
    db.flush()


def _run(module, capsys):
    code = module.main()
    captured = capsys.readouterr()
    records = [
        json.loads(line)
        for line in captured.out.strip().splitlines()
        if line.strip()
    ]
    return code, records, captured.err


def test_queue_rows_serialize_without_lazy_loading(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    _seed_vacancy(db, "1001")
    db.commit()
    db.close()

    code, records, _ = _run(module, capsys)

    assert code == 0
    assert len(records) == 1
    assert set(records[0]) == {
        "external_id",
        "title",
        "company",
        "location",
        "description_length",
        "first_seen_at",
    }


def test_company_name_returned_when_present(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    _seed_vacancy(db, "1002", company="Acme")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert records[0]["company"] == "Acme"


def test_null_company_and_location_are_handled(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    _seed_vacancy(db, "1003", company=None, location=None)
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert records[0]["company"] is None
    assert records[0]["location"] is None


def test_description_length_is_returned(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    _seed_vacancy(db, "1004", raw_text=DESCRIPTION)
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert records[0]["description_length"] == len(DESCRIPTION)


def test_first_seen_at_is_json_serializable(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    _seed_vacancy(db, "1005")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert records[0]["first_seen_at"].startswith("2026-01-01")


def test_existing_analysis_for_qualified_model_and_prompt_is_excluded(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    vacancy = _seed_vacancy(db, "1006")
    _seed_analysis(db, vacancy, "openai:gpt-5-mini", "vacancy-fit-v1")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert records == []


def test_different_model_is_not_excluded(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    vacancy = _seed_vacancy(db, "1007")
    _seed_analysis(db, vacancy, "openai:other-model", "vacancy-fit-v1")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert len(records) == 1
    assert records[0]["external_id"] == "1007"


def test_different_prompt_version_is_not_excluded(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    vacancy = _seed_vacancy(db, "1008")
    _seed_analysis(db, vacancy, "openai:gpt-5-mini", "vacancy-fit-v0")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert len(records) == 1


def test_ignored_and_expired_vacancies_are_excluded(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    _seed_vacancy(db, "2001", status="new")
    _seed_vacancy(db, "2002", status="ignored")
    _seed_vacancy(db, "2003", status="expired")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert [record["external_id"] for record in records] == ["2001"]


def test_queue_limit_is_respected(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    for index in range(1, 56):
        _seed_vacancy(db, str(index))
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert len(records) == 50


def test_script_does_not_modify_data(queue_env, capsys):
    module, session_factory = queue_env
    db = session_factory()
    _seed_vacancy(db, "3001")
    _seed_vacancy(db, "3002")
    db.commit()

    before_vacancies = db.scalar(select(func.count()).select_from(Vacancy))
    before_analyses = db.scalar(select(func.count()).select_from(Analysis))
    db.close()

    _, records, _ = _run(module, capsys)

    assert len(records) == 2

    db = session_factory()
    assert db.scalar(select(func.count()).select_from(Vacancy)) == before_vacancies
    assert db.scalar(select(func.count()).select_from(Analysis)) == before_analyses
    db.close()


def _set_deepseek_config(module):
    module.settings = _fake_settings(
        LLM_PROVIDER="deepseek", LLM_MODEL="deepseek-v4-flash"
    )


def test_qualified_deepseek_model_is_used(queue_env, capsys):
    module, session_factory = queue_env
    _set_deepseek_config(module)
    db = session_factory()
    vacancy = _seed_vacancy(db, "4001")
    _seed_analysis(db, vacancy, "openai:gpt-5-mini", "vacancy-fit-v1")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    # An OpenAI analysis must not hide the vacancy from the DeepSeek queue.
    assert len(records) == 1
    assert records[0]["external_id"] == "4001"


def test_deepseek_matching_analysis_is_excluded(queue_env, capsys):
    module, session_factory = queue_env
    _set_deepseek_config(module)
    db = session_factory()
    vacancy = _seed_vacancy(db, "4002")
    _seed_analysis(db, vacancy, "deepseek:deepseek-v4-flash", "vacancy-fit-v1")
    db.commit()
    db.close()

    _, records, _ = _run(module, capsys)

    assert records == []
