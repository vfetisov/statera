"""Provider-neutral vacancy-fit analysis batch service.

Selects vacancies that have a current full description but no analysis for the
configured provider/model and prompt version, runs fit analysis through the
``LLMProvider`` protocol, and persists one ``Analysis`` row per success.

The caller owns the session and the commit. Each vacancy runs inside its own
savepoint so one failure does not roll back previous successes. Data-integrity
problems (a vacancy with more than one content row) raise instead of guessing.
"""

import sys
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.career.registry import CareerAssetRegistry
from app.db.models.analysis import Analysis
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.llm.context.vacancy_analysis import (
    build_vacancy_analysis_context,
    validate_context_character_limits,
)
from app.llm.errors import LLMError, LLMStructuredOutputError
from app.llm.providers.base import LLMProvider, LLMRequest
from app.llm.prompts.vacancy_analysis import build_vacancy_analysis_request
from app.llm.retry import build_structured_output_retry_request
from app.llm.schemas import VacancyFitAnalysis

EXCLUDED_STATUSES = ("ignored", "expired")


@dataclass
class VacancyAnalysisBatchResult:
    """Summary of one analysis batch.

    ``retried`` counts vacancies for which the corrective structured-output
    retry request was made; ``recovered_after_retry`` counts those successfully
    analyzed on that second attempt.
    """

    selected: int = 0
    analyzed: int = 0
    created: int = 0
    skipped: int = 0
    failed: int = 0
    retried: int = 0
    recovered_after_retry: int = 0


def qualified_model_name(provider_name: str, model: str) -> str:
    """Provider-qualified model identifier stored in ``analyses.model``.

    The existing schema has only a ``model`` column, so provider identity is
    preserved as ``provider:model`` (for example ``openai:gpt-5-mini``).
    """
    return f"{provider_name}:{model}"


def _current_content_rows(db: Session, vacancy_id) -> list[VacancyContent]:
    return list(
        db.scalars(
            select(VacancyContent)
            .where(VacancyContent.vacancy_id == vacancy_id)
            .order_by(VacancyContent.version.asc(), VacancyContent.created_at.asc())
        )
    )


def _select_pending_vacancies(
    db: Session, qualified_model: str, prompt_version: str, limit: int
) -> list[Vacancy]:
    has_content = select(VacancyContent.vacancy_id)
    already_analyzed = select(Analysis.vacancy_id).where(
        Analysis.model == qualified_model,
        Analysis.prompt_version == prompt_version,
    )
    return list(
        db.scalars(
            select(Vacancy)
            .where(
                Vacancy.id.in_(has_content),
                ~Vacancy.status.in_(EXCLUDED_STATUSES),
                ~Vacancy.id.in_(already_analyzed),
            )
            .order_by(Vacancy.first_seen_at.asc(), Vacancy.external_id.asc())
            .limit(limit)
        )
    )


def _generate_with_structured_retry(
    provider: LLMProvider,
    request: LLMRequest,
    external_id: str,
    result: VacancyAnalysisBatchResult,
) -> Any:
    """Send one request, retrying exactly once on structured-output failure.

    Only ``LLMStructuredOutputError`` triggers the corrective retry. A
    successful retry is counted in ``recovered_after_retry``; a second failure
    is logged and re-raised so the caller counts the vacancy as failed. No
    analysis row is created here and nothing is committed.
    """
    try:
        return provider.generate_structured(request)
    except LLMStructuredOutputError as first_error:
        reason = getattr(first_error, "reason", "unknown_structured_output_error")
        print(
            f"structured output retry for vacancy {external_id}: "
            f"reason={reason} attempt=2/2",
            file=sys.stderr,
        )
        result.retried += 1
        retry_request = build_structured_output_retry_request(request, first_error)
        try:
            generated = provider.generate_structured(retry_request)
        except LLMStructuredOutputError as second_error:
            second_reason = getattr(
                second_error, "reason", "unknown_structured_output_error"
            )
            print(
                f"failed to analyze vacancy {external_id} after structured output "
                f"retry: LLMStructuredOutputError reason={second_reason}",
                file=sys.stderr,
            )
            raise
        print(
            f"structured output retry succeeded for vacancy {external_id}",
            file=sys.stderr,
        )
        result.recovered_after_retry += 1
        return generated


def analyze_pending_vacancies(
    db: Session,
    provider: LLMProvider,
    registry: CareerAssetRegistry,
    model: str,
    reasoning_effort: str | None,
    prompt_version: str,
    limit: int = 5,
    maximum_context_characters: int | None = None,
) -> VacancyAnalysisBatchResult:
    """Analyze the next batch of pending vacancies. Never commits."""
    qualified = qualified_model_name(provider.name, model)
    vacancies = _select_pending_vacancies(db, qualified, prompt_version, limit)
    result = VacancyAnalysisBatchResult(selected=len(vacancies))

    for vacancy in vacancies:
        rows = _current_content_rows(db, vacancy.id)
        if len(rows) > 1:
            raise RuntimeError(
                f"vacancy {vacancy.external_id} has {len(rows)} vacancy_contents "
                "rows; expected exactly one current row. Refusing to guess."
            )
        if not rows:
            result.skipped += 1
            continue
        content = rows[0]

        existing = db.scalar(
            select(Analysis.id).where(
                Analysis.vacancy_content_id == content.id,
                Analysis.model == qualified,
                Analysis.prompt_version == prompt_version,
            )
        )
        if existing is not None:
            result.skipped += 1
            continue

        try:
            with db.begin_nested():
                context = build_vacancy_analysis_context(
                    registry, vacancy, content, prompt_version
                )
                validate_context_character_limits(
                    context, maximum_context_characters
                )
                request = build_vacancy_analysis_request(
                    context, model=model, reasoning_effort=reasoning_effort
                )
                generated = _generate_with_structured_retry(
                    provider, request, vacancy.external_id, result
                )
                fit = generated.value
                if not isinstance(fit, VacancyFitAnalysis):
                    raise LLMError(
                        f"provider {provider.name} returned an unexpected type "
                        f"for vacancy {vacancy.external_id}"
                    )
                db.add(
                    Analysis(
                        vacancy_id=vacancy.id,
                        vacancy_content_id=content.id,
                        model=qualified,
                        prompt_version=prompt_version,
                        overall_score=fit.overall_score,
                        technical_score=fit.technical_score,
                        leadership_score=fit.leadership_score,
                        location_score=fit.location_score,
                        summary=fit.summary,
                        strengths=list(fit.strengths),
                        weaknesses=list(fit.weaknesses),
                        risks=list(fit.risks),
                        recommendation=fit.recommendation.value,
                    )
                )
                db.flush()
        except (LLMError, ValueError) as exc:
            result.failed += 1
            # A second structured-output failure was already logged with its
            # retry context by ``_generate_with_structured_retry``.
            if not isinstance(exc, LLMStructuredOutputError):
                print(
                    f"failed to analyze vacancy {vacancy.external_id}: "
                    f"{type(exc).__name__}",
                    file=sys.stderr,
                )
            continue

        result.analyzed += 1
        result.created += 1

    return result
