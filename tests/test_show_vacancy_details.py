"""Tests for the vacancy-detail script (SQLite, no LLM, no live database).

The script module is loaded from disk; its ``settings`` and ``SessionLocal``
are replaced so the query runs against an in-memory SQLite database.
"""

import importlib.util
import sys
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

QUALIFIED = "deepseek:deepseek-v4-flash"
PROMPT = "vacancy-fit-v3"
DESCRIPTION = (
    "A full normalized job description for a support engineering lead role. "
    "It describes people leadership, SLA ownership, incident management, and "
    "SaaS support operations in detail and would never be printed by default."
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(element, compiler, **kw):
    return "JSON"


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_settings(**overrides):
    base = {
        "LLM_PROVIDER": "deepseek",
        "LLM_MODEL": "deepseek-v4-flash",
        "VACANCY_ANALYSIS_PROMPT_VERSION": PROMPT,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture()
def detail_env(monkeypatch):
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

    module = _load_script("show_vacancy_details")
    monkeypatch.setattr(module, "SessionLocal", session_factory)
    monkeypatch.setattr(module, "settings", _fake_settings())
    yield module, session_factory
    engine.dispose()


def _seed(db, external_id, *, status="new", company="Acme", location="Remote",
          with_analysis=True):
    source = db.scalar(select(JobSource).where(JobSource.code == "linkedin"))
    if source is None:
        source = JobSource(code="linkedin", name="LinkedIn", enabled=True)
        db.add(source)
        db.flush()
    company_obj = None
    if company is not None:
        company_obj = db.scalar(
            select(Company).where(Company.normalized_name == company.lower())
        )
        if company_obj is None:
            company_obj = Company(name=company, normalized_name=company.lower())
            db.add(company_obj)
            db.flush()
    vacancy = Vacancy(
        source_id=source.id,
        external_id=external_id,
        url=f"https://www.linkedin.com/jobs/view/{external_id}/",
        title=f"Job {external_id}",
        location=location,
        status=status,
        company_id=company_obj.id if company_obj else None,
        first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(vacancy)
    db.flush()
    content = VacancyContent(
        vacancy_id=vacancy.id,
        version=1,
        content_hash=DESCRIPTION,
        raw_text=DESCRIPTION,
        markdown=DESCRIPTION,
    )
    db.add(content)
    db.flush()
    if with_analysis:
        db.add(
            Analysis(
                vacancy_id=vacancy.id,
                vacancy_content_id=content.id,
                model=QUALIFIED,
                prompt_version=PROMPT,
                overall_score=86,
                technical_score=82,
                leadership_score=93,
                location_score=15,
                summary="Strong professional match; likely geographic restriction.",
                strengths=["People leadership", "SLA ownership"],
                weaknesses=["No CDN expertise"],
                risks=["Likely regional restriction"],
                recommendation="consider",
            )
        )
        db.flush()
    return vacancy


def _run(module, monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["show_vacancy_details", *argv])
    code = module.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_detail_returns_all_analysis_fields(detail_env, monkeypatch, capsys):
    module, session_factory = detail_env
    db = session_factory()
    _seed(db, "1001")
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys, "1001")

    assert code == 0
    assert "Title: Job 1001" in out
    assert "Company: Acme" in out
    assert "Location: Remote" in out
    assert "https://www.linkedin.com/jobs/view/1001/" in out
    assert "Status: new" in out
    assert "overall: 86" in out
    assert "technical: 82" in out
    assert "leadership: 93" in out
    assert "location: 15" in out
    assert "Recommendation: consider" in out
    assert "Strong professional match" in out
    assert "- People leadership" in out
    assert "- SLA ownership" in out
    assert "- No CDN expertise" in out
    assert "- Likely regional restriction" in out
    assert QUALIFIED in out
    assert PROMPT in out
    assert "JD character count:" in out


def test_detail_does_not_show_job_description_by_default(detail_env, monkeypatch, capsys):
    module, session_factory = detail_env
    db = session_factory()
    _seed(db, "1002")
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys, "1002")

    assert code == 0
    assert "JOB DESCRIPTION" not in out
    assert DESCRIPTION not in out


def test_detail_shows_job_description_with_flag(detail_env, monkeypatch, capsys):
    module, session_factory = detail_env
    db = session_factory()
    _seed(db, "1003")
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys, "1003", "--show-description")

    assert code == 0
    assert "JOB DESCRIPTION" in out
    assert DESCRIPTION in out


def test_missing_vacancy_exits_nonzero(detail_env, monkeypatch, capsys):
    module, session_factory = detail_env
    db = session_factory()
    _seed(db, "1004")
    db.commit()
    db.close()

    code, _, err = _run(module, monkeypatch, capsys, "999999")

    assert code != 0
    assert "not found" in err


def test_missing_analysis_exits_nonzero(detail_env, monkeypatch, capsys):
    module, session_factory = detail_env
    db = session_factory()
    _seed(db, "1005", with_analysis=False)
    db.commit()
    db.close()

    code, _, err = _run(module, monkeypatch, capsys, "1005")

    assert code != 0
    assert "No analysis" in err


def test_invalid_external_id_rejected(detail_env, monkeypatch, capsys):
    module, session_factory = detail_env
    db = session_factory()
    _seed(db, "1006")
    db.commit()
    db.close()

    code, _, err = _run(module, monkeypatch, capsys, "abc")

    assert code != 0
    assert "Invalid external ID" in err


def test_script_does_not_modify_data(detail_env, monkeypatch, capsys):
    module, session_factory = detail_env
    db = session_factory()
    _seed(db, "1007")
    db.commit()

    before_vacancies = db.scalar(select(func.count()).select_from(Vacancy))
    before_analyses = db.scalar(select(func.count()).select_from(Analysis))
    before_contents = db.scalar(select(func.count()).select_from(VacancyContent))
    db.close()

    code, _, _ = _run(module, monkeypatch, capsys, "1007", "--show-description")

    assert code == 0
    db = session_factory()
    assert db.scalar(select(func.count()).select_from(Vacancy)) == before_vacancies
    assert db.scalar(select(func.count()).select_from(Analysis)) == before_analyses
    assert db.scalar(select(func.count()).select_from(VacancyContent)) == before_contents
    db.close()
