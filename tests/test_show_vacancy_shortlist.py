"""Tests for the shortlist script (SQLite, no LLM, no live database).

The script module is loaded from disk; its ``settings`` and ``SessionLocal``
are replaced so the query runs against an in-memory SQLite database.
"""

import importlib.util
import json
import sys
import uuid
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

QUALIFIED = "deepseek:deepseek-v4-flash"
PROMPT = "vacancy-fit-v3"


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
def shortlist_env(monkeypatch):
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
    session_factory = sessionmaker(bind=engine, autoflush=True, autocommit=False)

    module = _load_script("show_vacancy_shortlist")
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
    strengths=None,
    weaknesses=None,
    risks=None,
    summary=None,
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
    db.add(
        Analysis(
            vacancy_id=vacancy.id,
            vacancy_content_id=uuid.uuid4(),
            model=QUALIFIED,
            prompt_version=PROMPT,
            overall_score=overall,
            technical_score=technical,
            leadership_score=leadership,
            location_score=location_score,
            summary=summary or f"Summary for {external_id} with clear evidence.",
            strengths=strengths or [f"strength-{external_id}-1"],
            weaknesses=weaknesses or [f"weakness-{external_id}-1"],
            risks=risks or [f"risk-{external_id}-1"],
            recommendation=recommendation,
        )
    )
    db.flush()


def _run(module, monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["show_vacancy_shortlist", *argv])
    code = module.main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_text_output_contains_separate_overall_and_location_scores(
    shortlist_env, monkeypatch, capsys
):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "1001", overall=82, location_score=20, recommendation="consider")
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys)

    assert code == 0
    assert "82 overall" in out
    assert "20 location" in out


def test_text_output_contains_direct_linkedin_url(shortlist_env, monkeypatch, capsys):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "1002")
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys)

    assert code == 0
    assert "https://www.linkedin.com/jobs/view/1002/" in out


def test_text_output_limits_strengths_weaknesses_risks_to_three(
    shortlist_env, monkeypatch, capsys
):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(
        db,
        "1003",
        strengths=[f"s{i}" for i in range(5)],
        weaknesses=[f"w{i}" for i in range(5)],
        risks=[f"r{i}" for i in range(5)],
    )
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys)

    assert code == 0
    for index in range(3):
        assert f"- s{index}" in out
        assert f"- w{index}" in out
        assert f"- r{index}" in out
    assert "- s3" not in out
    assert "- w3" not in out
    assert "- r3" not in out


def test_json_output_uses_iso_timestamps(shortlist_env, monkeypatch, capsys):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "1004")
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys, "--format", "json")

    assert code == 0
    record = json.loads(out.strip().splitlines()[0])
    assert record["category"] == "REVIEW"
    assert record["first_seen_at"].startswith("2026-01-01T")
    assert record["analysis_created_at"].startswith("2026-")
    assert record["external_id"] == "1004"
    assert "T" in record["first_seen_at"]


def test_category_filter(shortlist_env, monkeypatch, capsys):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "2001", overall=85, location_score=75, recommendation="strong_match")  # PRIORITY
    _seed(db, "2002", overall=82, location_score=20, recommendation="consider")  # REVIEW
    _seed(db, "2003", overall=62, location_score=15, recommendation="weak_match")  # LOW_PRIORITY
    _seed(db, "2004", overall=30, recommendation="reject")  # REJECT
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys, "--category", "REVIEW")

    assert code == 0
    assert "2002" in out
    assert "2001" not in out
    assert "2003" not in out
    assert "2004" not in out


def test_min_score_filter(shortlist_env, monkeypatch, capsys):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "2005", overall=80)
    _seed(db, "2006", overall=50)
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys, "--min-score", "60")

    assert code == 0
    assert "2005" in out
    assert "2006" not in out


def test_recommendation_filter(shortlist_env, monkeypatch, capsys):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "2007", recommendation="strong_match")
    _seed(db, "2008", recommendation="consider")
    _seed(db, "2009", recommendation="reject")
    db.commit()
    db.close()

    code, out, _ = _run(
        module,
        monkeypatch,
        capsys,
        "--recommendation",
        "strong_match",
        "--recommendation",
        "consider",
    )

    assert code == 0
    assert "2007" in out
    assert "2008" in out
    assert "2009" not in out


def test_limit_respected(shortlist_env, monkeypatch, capsys):
    module, session_factory = shortlist_env
    db = session_factory()
    for index in range(4):
        _seed(db, f"300{index}")
    db.commit()
    db.close()

    code, out, err = _run(module, monkeypatch, capsys, "--limit", "2")

    assert code == 0
    assert "2 shortlist items" in err


def test_invalid_limit_rejected(shortlist_env, monkeypatch, capsys):
    module, _ = shortlist_env
    code, _, err = _run(module, monkeypatch, capsys, "--limit", "0")
    assert code == 1
    assert "--limit" in err


def test_script_does_not_modify_data(shortlist_env, monkeypatch, capsys):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "3004")
    _seed(db, "3005")
    db.commit()

    before_vacancies = db.scalar(select(func.count()).select_from(Vacancy))
    before_analyses = db.scalar(select(func.count()).select_from(Analysis))
    db.close()

    code, _, _ = _run(module, monkeypatch, capsys)

    assert code == 0
    db = session_factory()
    assert db.scalar(select(func.count()).select_from(Vacancy)) == before_vacancies
    assert db.scalar(select(func.count()).select_from(Analysis)) == before_analyses
    db.close()


def test_text_output_does_not_duplicate_professional_fit_heading(
    shortlist_env, monkeypatch, capsys
):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(
        db,
        "4001",
        summary="Professional fit: Strong transferable match with clear evidence.",
    )
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys)

    assert code == 0
    assert out.count("Professional fit:") == 1
    assert "Strong transferable match with clear evidence." in out


def test_text_output_prints_external_id_without_markdown_hash(
    shortlist_env, monkeypatch, capsys
):
    module, session_factory = shortlist_env
    db = session_factory()
    _seed(db, "4002")
    db.commit()
    db.close()

    code, out, _ = _run(module, monkeypatch, capsys)

    assert code == 0
    assert "External ID: 4002" in out
    assert "## External ID" not in out
