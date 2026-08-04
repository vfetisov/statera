"""Tests for the vacancy-analysis persistence service.

Uses an in-memory SQLite database with only the tables required by these
tests and a fake provider implementing the LLMProvider protocol. No real LLM,
LinkedIn, live database, or API key is involved.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _compile_jsonb_on_sqlite(element, compiler, **kw):
    """Render PostgreSQL JSONB as plain JSON on the in-memory SQLite schema."""
    return "JSON"

import app.services.vacancy_analysis as service
from app.career.assets import CareerAsset, CareerAssetType
from app.career.registry import CareerAssetRegistry
from app.db.base import Base
from app.db.models.analysis import Analysis
from app.db.models.company import Company
from app.db.models.job_source import JobSource
from app.db.models.search import Search
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.llm.errors import (
    ContextSizeExceededError,
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)
from app.llm.providers.base import LLMResult, LLMUsage
from app.llm.schemas import Recommendation, VacancyFitAnalysis

BRIEF = CareerAssetType.MASTER_CAREER_BRIEF
BRIEF_TEXT = (
    "Master career brief with a complete factual history of the candidate. "
    "It includes many paragraphs about leadership, support operations, and "
    "technical accomplishments and service delivery."
)
DESCRIPTION = (
    "Full job description for a support engineering lead role. It describes "
    "people leadership, SLA ownership, incident management, and SaaS support "
    "operations in detail."
)
MODEL = "gpt-5-mini"
PROMPT_VERSION = "vacancy-fit-v1"


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # JSONB columns render as JSON on SQLite via the @compiles registration
    # above, so the Analysis table can be created in-memory.
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
    db = sessionmaker(bind=engine, autoflush=True, autocommit=False)()
    yield db
    db.close()
    engine.dispose()


def _brief_registry():
    asset = CareerAsset(
        asset_type=BRIEF,
        source_path=Path("/x/brief.docx"),
        source_format="docx",
        text=BRIEF_TEXT,
        content_hash="brief-hash",
        character_count=len(BRIEF_TEXT),
    )
    return CareerAssetRegistry(assets={BRIEF: asset})


def _make_source(db):
    existing = db.scalar(select(JobSource).where(JobSource.code == "linkedin"))
    if existing is not None:
        return existing
    source = JobSource(code="linkedin", name="LinkedIn", enabled=True)
    db.add(source)
    db.flush()
    return source


def _make_vacancy(db, external_id, status="new", first_seen_at=None):
    source = _make_source(db)
    vacancy = Vacancy(
        source_id=source.id,
        external_id=external_id,
        url=f"https://www.linkedin.com/jobs/view/{external_id}/",
        title=f"Job {external_id}",
        location="Remote",
        status=status,
        first_seen_at=first_seen_at or datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    db.add(vacancy)
    db.flush()
    return vacancy


def _make_content(db, vacancy, raw_text=DESCRIPTION):
    content = VacancyContent(
        vacancy_id=vacancy.id,
        version=1,
        content_hash=raw_text,
        raw_text=raw_text,
        markdown=raw_text,
    )
    db.add(content)
    db.flush()
    return content


def _make_analysis(db, vacancy, content, qualified, prompt_version=PROMPT_VERSION):
    analysis = Analysis(
        vacancy_id=vacancy.id,
        vacancy_content_id=content.id,
        model=qualified,
        prompt_version=prompt_version,
        overall_score=50,
        technical_score=50,
        leadership_score=50,
        location_score=50,
        summary="Previously recorded analysis for the same content and version.",
        strengths=["old"],
        weaknesses=["old"],
        risks=["old"],
        recommendation="consider",
    )
    db.add(analysis)
    db.flush()
    return analysis


def _fit(external_id):
    return VacancyFitAnalysis(
        overall_score=90,
        technical_score=85,
        leadership_score=80,
        location_score=70,
        recommendation=Recommendation.strong_match,
        summary=f"Strong fit for vacancy {external_id} with clear evidence.",
        strengths=["People leadership", "SLA ownership"],
        weaknesses=["No billing analytics"],
        risks=["Unspecified work authorization"],
    )


class FakeProvider:
    def __init__(self, name="fake", failures=None):
        self.name = name
        self.failures = set(failures or [])
        self.calls = []

    def generate_structured(self, request):
        self.calls.append(request)
        external_id = request.metadata["vacancy_external_id"]
        if external_id in self.failures:
            raise LLMRefusalError(f"refused {external_id}")
        return LLMResult(
            value=_fit(external_id),
            provider=self.name,
            model=request.model,
            usage=LLMUsage(input_tokens=10, output_tokens=5),
            provider_request_id=f"req-{external_id}",
        )


def _run(db, provider=None, model=MODEL, prompt_version=PROMPT_VERSION, limit=5,
         maximum_context_characters=None):
    provider = provider or FakeProvider()
    return service.analyze_pending_vacancies(
        db,
        provider=provider,
        registry=_brief_registry(),
        model=model,
        reasoning_effort="medium",
        prompt_version=prompt_version,
        limit=limit,
        maximum_context_characters=maximum_context_characters,
    ), provider


def _analysis_count(db):
    return db.scalar(select(func.count()).select_from(Analysis))


def test_only_vacancies_with_content_are_selected(session):
    with_content = _make_vacancy(session, "1001")
    _make_content(session, with_content)
    _make_vacancy(session, "1002")  # no content

    result, _ = _run(session)

    assert result.selected == 1
    assert result.created == 1
    assert result.analyzed == 1


def test_ignored_and_expired_vacancies_are_excluded(session):
    new_vacancy = _make_vacancy(session, "2001", status="new")
    _make_content(session, new_vacancy)
    ignored = _make_vacancy(session, "2002", status="ignored")
    _make_content(session, ignored)
    expired = _make_vacancy(session, "2003", status="expired")
    _make_content(session, expired)

    result, _ = _run(session)

    assert result.selected == 1
    assert result.created == 1


def test_existing_same_analysis_is_skipped(session):
    vacancy = _make_vacancy(session, "3001")
    content = _make_content(session, vacancy)
    _make_analysis(session, vacancy, content, service.qualified_model_name("fake", MODEL))

    result, _ = _run(session)
    session.commit()

    assert result.selected == 0
    assert result.created == 0
    assert _analysis_count(session) == 1


def test_different_model_permits_new_analysis(session):
    vacancy = _make_vacancy(session, "4001")
    content = _make_content(session, vacancy)
    _make_analysis(session, vacancy, content, "fake:old-model")

    result, _ = _run(session, model=MODEL)
    session.commit()

    assert result.created == 1
    assert _analysis_count(session) == 2


def test_different_provider_qualified_model_permits_new_analysis(session):
    vacancy = _make_vacancy(session, "4002")
    content = _make_content(session, vacancy)
    _make_analysis(session, vacancy, content, "other:gpt-5-mini")

    result, _ = _run(session)
    session.commit()

    assert result.created == 1
    assert _analysis_count(session) == 2


def test_different_prompt_version_permits_new_analysis(session):
    vacancy = _make_vacancy(session, "5001")
    content = _make_content(session, vacancy)
    _make_analysis(session, vacancy, content, "fake:gpt-5-mini", prompt_version="vacancy-fit-v0")

    result, _ = _run(session)
    session.commit()

    assert result.created == 1
    assert _analysis_count(session) == 2


def test_batch_limit_is_respected(session):
    for index in range(7):
        vacancy = _make_vacancy(session, f"600{index}")
        _make_content(session, vacancy)

    result, _ = _run(session, limit=3)

    assert result.selected == 3
    assert result.created == 3


def test_one_failure_does_not_discard_previous_successes(session, capsys):
    for index in range(3):
        vacancy = _make_vacancy(session, f"700{index}")
        _make_content(session, vacancy)

    provider = FakeProvider(failures={"7001"})
    result, _ = _run(session, provider=provider)
    session.commit()

    assert result.selected == 3
    assert result.analyzed == 2
    assert result.created == 2
    assert result.failed == 1
    assert _analysis_count(session) == 2
    captured = capsys.readouterr()
    assert "7001" in captured.err


def test_saved_analysis_fields_match_validated_output(session):
    vacancy = _make_vacancy(session, "8001")
    content = _make_content(session, vacancy)

    result, _ = _run(session)
    session.commit()

    assert result.created == 1
    analysis = db_first_analysis(session)
    expected = _fit("8001")
    assert analysis.vacancy_id == vacancy.id
    assert analysis.vacancy_content_id == content.id
    assert analysis.overall_score == expected.overall_score
    assert analysis.technical_score == expected.technical_score
    assert analysis.leadership_score == expected.leadership_score
    assert analysis.location_score == expected.location_score
    assert analysis.summary == expected.summary
    assert analysis.strengths == list(expected.strengths)
    assert analysis.weaknesses == list(expected.weaknesses)
    assert analysis.risks == list(expected.risks)
    assert analysis.recommendation == expected.recommendation.value


def test_qualified_model_is_stored_in_analyses_model(session):
    vacancy = _make_vacancy(session, "8101")
    _make_content(session, vacancy)

    _run(session)
    session.commit()

    analysis = db_first_analysis(session)
    assert analysis.model == "fake:gpt-5-mini"


def test_vacancy_status_is_unchanged(session):
    vacancy = _make_vacancy(session, "8201", status="new")
    _make_content(session, vacancy)

    _run(session)
    session.commit()

    session.refresh(vacancy)
    assert vacancy.status == "new"


def test_multiple_content_rows_raise_integrity_error(session):
    vacancy = _make_vacancy(session, "8301")
    first = _make_content(session, vacancy)
    second = VacancyContent(
        vacancy_id=vacancy.id,
        version=2,
        content_hash="another-hash",
        raw_text=DESCRIPTION,
        markdown=DESCRIPTION,
    )
    session.add(second)
    session.flush()

    provider = FakeProvider()
    with pytest.raises(RuntimeError):
        service.analyze_pending_vacancies(
            session,
            provider=provider,
            registry=_brief_registry(),
            model=MODEL,
            reasoning_effort="medium",
            prompt_version=PROMPT_VERSION,
            limit=5,
        )
    assert provider.calls == []
    assert first is not None


def test_complete_service_with_fake_provider(session):
    for index in range(4):
        vacancy = _make_vacancy(session, f"900{index}")
        _make_content(session, vacancy)

    result, provider = _run(session)
    session.commit()

    assert result.selected == 4
    assert result.analyzed == 4
    assert result.created == 4
    assert result.skipped == 0
    assert result.failed == 0
    assert len(provider.calls) == 4
    assert _analysis_count(session) == 4


DEEPSEEK_MODEL = "deepseek-v4-flash"


def test_deepseek_compatible_fake_provider_works(session):
    vacancy = _make_vacancy(session, "9101")
    _make_content(session, vacancy)

    provider = FakeProvider(name="deepseek")
    result, _ = _run(session, provider=provider, model=DEEPSEEK_MODEL)
    session.commit()

    assert result.created == 1
    assert provider.name == "deepseek"


def test_qualified_model_stored_as_deepseek(session):
    vacancy = _make_vacancy(session, "9102")
    _make_content(session, vacancy)

    provider = FakeProvider(name="deepseek")
    _run(session, provider=provider, model=DEEPSEEK_MODEL)
    session.commit()

    analysis = db_first_analysis(session)
    assert analysis.model == "deepseek:deepseek-v4-flash"


def test_openai_analysis_does_not_block_deepseek(session):
    vacancy = _make_vacancy(session, "9103")
    content = _make_content(session, vacancy)
    _make_analysis(session, vacancy, content, "openai:gpt-5-mini")

    provider = FakeProvider(name="deepseek")
    result, _ = _run(session, provider=provider, model=DEEPSEEK_MODEL)
    session.commit()

    assert result.created == 1
    assert _analysis_count(session) == 2


def test_same_deepseek_model_and_prompt_is_idempotent(session):
    vacancy = _make_vacancy(session, "9104")
    content = _make_content(session, vacancy)
    _make_analysis(session, vacancy, content, "deepseek:deepseek-v4-flash")

    provider = FakeProvider(name="deepseek")
    result, _ = _run(session, provider=provider, model=DEEPSEEK_MODEL)
    session.commit()

    assert result.selected == 0
    assert result.created == 0
    assert _analysis_count(session) == 1


def test_different_deepseek_model_permits_new_analysis(session):
    vacancy = _make_vacancy(session, "9105")
    content = _make_content(session, vacancy)
    _make_analysis(session, vacancy, content, "deepseek:deepseek-v4-flash")

    provider = FakeProvider(name="deepseek")
    result, _ = _run(session, provider=provider, model="deepseek-v4-pro")
    session.commit()

    assert result.created == 1
    assert _analysis_count(session) == 2


def test_deepseek_failure_does_not_roll_back_successes(session, capsys):
    for index in range(2):
        vacancy = _make_vacancy(session, f"920{index}")
        _make_content(session, vacancy)

    provider = FakeProvider(name="deepseek", failures={"9200"})
    result, _ = _run(session, provider=provider, model=DEEPSEEK_MODEL)
    session.commit()

    assert result.created == 1
    assert result.failed == 1
    assert _analysis_count(session) == 1


def test_deepseek_vacancy_status_is_unchanged(session):
    vacancy = _make_vacancy(session, "9301", status="new")
    _make_content(session, vacancy)

    provider = FakeProvider(name="deepseek")
    _run(session, provider=provider, model=DEEPSEEK_MODEL)
    session.commit()

    session.refresh(vacancy)
    assert vacancy.status == "new"


def test_prompt_version_v3_permits_new_analyses_alongside_older_versions(session):
    v1 = _make_vacancy(session, "9601")
    c1 = _make_content(session, v1)
    _make_analysis(session, v1, c1, "fake:gpt-5-mini", prompt_version="vacancy-fit-v1")
    v2 = _make_vacancy(session, "9602")
    c2 = _make_content(session, v2)
    _make_analysis(session, v2, c2, "fake:gpt-5-mini", prompt_version="vacancy-fit-v2")

    result, _ = _run(session, prompt_version="vacancy-fit-v3")
    session.commit()

    assert result.created == 2
    assert _analysis_count(session) == 4


def test_old_analyses_remain_unchanged(session):
    v1 = _make_vacancy(session, "9603")
    c1 = _make_content(session, v1)
    _make_analysis(session, v1, c1, "fake:gpt-5-mini", prompt_version="vacancy-fit-v1")
    old = db_first_analysis(session)
    old_summary = old.summary

    result, _ = _run(session, prompt_version="vacancy-fit-v3")
    session.commit()

    assert result.created == 1
    loaded = session.get(Analysis, old.id)
    assert loaded.prompt_version == "vacancy-fit-v1"
    assert loaded.summary == old_summary


def test_same_v3_analysis_is_idempotent(session):
    v1 = _make_vacancy(session, "9604")
    c1 = _make_content(session, v1)
    _make_analysis(session, v1, c1, "fake:gpt-5-mini", prompt_version="vacancy-fit-v3")

    result, _ = _run(session, prompt_version="vacancy-fit-v3")
    session.commit()

    assert result.selected == 0
    assert result.created == 0
    assert _analysis_count(session) == 1


def test_service_does_not_branch_on_provider(session):
    import inspect

    source = inspect.getsource(service)
    assert "from app.llm.providers.deepseek" not in source
    assert "from app.llm.providers.openai" not in source
    assert "provider.name ==" not in source


# --- structured-output corrective retry ---


class RetryFakeProvider:
    """Deterministic provider driven by per-vacancy outcome plans.

    Each outcome string (in order of attempts) controls what that call does:
    ``ok`` succeeds; ``structured_error`` raises LLMStructuredOutputError;
    ``schema_error`` raises it with a schema reason; other values raise the
    matching non-structured provider error.
    """

    def __init__(self, behavior=None, name="fake"):
        self.name = name
        self.behavior = dict(behavior or {})
        self.call_counts = {}
        self.retry_requests = []

    def generate_structured(self, request):
        external_id = request.metadata["vacancy_external_id"]
        attempt = self.call_counts.get(external_id, 0) + 1
        self.call_counts[external_id] = attempt
        if attempt > 1:
            self.retry_requests.append(request)

        plan = self.behavior.get(external_id, ["ok"])
        outcome = plan[min(attempt, len(plan)) - 1]
        if outcome == "structured_error":
            raise LLMStructuredOutputError("malformed json", reason="invalid_json")
        if outcome == "schema_error":
            raise LLMStructuredOutputError(
                "schema invalid", reason="schema_validation_failed"
            )
        if outcome == "auth":
            raise LLMAuthenticationError("auth failed")
        if outcome == "rate_limit":
            raise LLMRateLimitError("rate limited")
        if outcome == "timeout":
            raise LLMTimeoutError("timed out")
        if outcome == "provider":
            raise LLMProviderError("provider error")
        if outcome == "refusal":
            raise LLMRefusalError("refused")
        return LLMResult(
            value=_fit(external_id),
            provider=self.name,
            model=request.model,
            usage=LLMUsage(input_tokens=1, output_tokens=1),
            provider_request_id=f"req-{external_id}-{attempt}",
        )


def _retry_run(db, behavior, **kwargs):
    provider = RetryFakeProvider(behavior=behavior)
    result, _ = _run(db, provider=provider, **kwargs)
    return result, provider


def test_successful_first_attempt_does_not_retry(session):
    vacancy = _make_vacancy(session, "9701")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9701": ["ok"]})
    session.commit()

    assert result.retried == 0
    assert result.recovered_after_retry == 0
    assert result.created == 1
    assert result.failed == 0
    assert provider.call_counts["9701"] == 1


def test_structured_output_error_triggers_exactly_one_retry(session):
    vacancy = _make_vacancy(session, "9702")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9702": ["structured_error", "ok"]})
    session.commit()

    assert result.retried == 1
    assert result.recovered_after_retry == 1
    assert result.created == 1
    assert result.failed == 0
    assert provider.call_counts["9702"] == 2
    assert _analysis_count(session) == 1


def test_successful_retry_creates_exactly_one_analysis_row(session):
    vacancy = _make_vacancy(session, "9703")
    _make_content(session, vacancy)

    result, _ = _retry_run(session, {"9703": ["structured_error", "ok"]})
    session.commit()

    assert result.created == 1
    assert _analysis_count(session) == 1


def test_retry_failure_creates_no_analysis_row(session, capsys):
    vacancy = _make_vacancy(session, "9704")
    _make_content(session, vacancy)

    result, provider = _retry_run(
        session, {"9704": ["structured_error", "structured_error"]}
    )
    session.commit()

    assert result.failed == 1
    assert result.retried == 1
    assert result.recovered_after_retry == 0
    assert result.created == 0
    assert provider.call_counts["9704"] == 2
    assert _analysis_count(session) == 0
    assert "after structured output retry" in capsys.readouterr().err


def test_retry_failure_increments_failed_once_not_twice(session):
    vacancy = _make_vacancy(session, "9705")
    _make_content(session, vacancy)

    result, _ = _retry_run(session, {"9705": ["schema_error", "schema_error"]})

    assert result.failed == 1


def test_retry_request_contains_corrective_instruction(session):
    vacancy = _make_vacancy(session, "9706")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9706": ["structured_error", "ok"]})

    assert result.recovered_after_retry == 1
    assert len(provider.retry_requests) == 1
    retry_request = provider.retry_requests[0]
    assert retry_request.messages[-1].role == "user"
    assert "exactly one valid JSON object" in retry_request.messages[-1].content
    assert "reason: invalid_json" in retry_request.messages[-1].content


def test_no_duplicate_analysis_after_retry(session):
    vacancy = _make_vacancy(session, "9707")
    _make_content(session, vacancy)

    result, _ = _retry_run(session, {"9707": ["structured_error", "ok"]})
    session.commit()

    assert result.created == 1
    assert _analysis_count(session) == 1


def test_rerun_remains_idempotent_after_retry_success(session):
    vacancy = _make_vacancy(session, "9708")
    _make_content(session, vacancy)

    result, _ = _retry_run(session, {"9708": ["structured_error", "ok"]})
    session.commit()
    assert result.created == 1

    # A fresh provider on a rerun must skip the already-analyzed vacancy.
    second, _ = _retry_run(session, {"9708": ["ok"]})
    session.commit()
    assert second.selected == 0
    assert second.created == 0
    assert _analysis_count(session) == 1


def test_authentication_error_does_not_retry(session):
    vacancy = _make_vacancy(session, "9709")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9709": ["auth"]})

    assert result.retried == 0
    assert result.failed == 1
    assert provider.call_counts["9709"] == 1


def test_rate_limit_error_does_not_retry(session):
    vacancy = _make_vacancy(session, "9710")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9710": ["rate_limit"]})

    assert result.retried == 0
    assert result.failed == 1
    assert provider.call_counts["9710"] == 1


def test_timeout_error_does_not_retry(session):
    vacancy = _make_vacancy(session, "9711")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9711": ["timeout"]})

    assert result.retried == 0
    assert result.failed == 1
    assert provider.call_counts["9711"] == 1


def test_generic_provider_error_does_not_retry(session):
    vacancy = _make_vacancy(session, "9712")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9712": ["provider"]})

    assert result.retried == 0
    assert result.failed == 1
    assert provider.call_counts["9712"] == 1


def test_refusal_does_not_retry(session):
    vacancy = _make_vacancy(session, "9713")
    _make_content(session, vacancy)

    result, provider = _retry_run(session, {"9713": ["refusal"]})

    assert result.retried == 0
    assert result.failed == 1
    assert provider.call_counts["9713"] == 1


def test_context_size_error_does_not_retry(session):
    vacancy = _make_vacancy(session, "9714")
    _make_content(session, vacancy)

    provider = RetryFakeProvider(behavior={"9714": ["ok"]})
    result, _ = _run(
        session, provider=provider, maximum_context_characters=1
    )

    assert result.retried == 0
    assert result.failed == 1
    assert provider.call_counts == {}


def test_batch_continues_after_permanent_structured_failure(session):
    v1 = _make_vacancy(session, "9715")
    _make_content(session, v1)
    v2 = _make_vacancy(session, "9716")
    _make_content(session, v2)

    result, _ = _retry_run(
        session,
        {"9715": ["structured_error", "structured_error"], "9716": ["ok"]},
    )
    session.commit()

    assert result.created == 1
    assert result.failed == 1
    assert result.retried == 1
    assert _analysis_count(session) == 1


def test_first_failed_attempt_does_not_persist_partial_data(session):
    vacancy = _make_vacancy(session, "9717")
    _make_content(session, vacancy)

    _retry_run(session, {"9717": ["structured_error", "ok"]})
    session.commit()

    assert _analysis_count(session) == 1


def test_retry_logs_concise_messages(session, capsys):
    vacancy = _make_vacancy(session, "9718")
    _make_content(session, vacancy)

    result, _ = _retry_run(session, {"9718": ["structured_error", "ok"]})

    err = capsys.readouterr().err
    assert "structured output retry for vacancy 9718: reason=invalid_json attempt=2/2" in err
    assert "structured output retry succeeded for vacancy 9718" in err
    assert result.recovered_after_retry == 1


def db_first_analysis(db) -> Analysis:
    return db.scalar(select(Analysis).order_by(Analysis.created_at))
