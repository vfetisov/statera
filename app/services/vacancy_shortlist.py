"""Read-only vacancy shortlist built from existing vacancy-fit analyses.

Provides an immutable shortlist item, a scalar-column query that returns only
display-ready values (no lazy-loaded relationships), a deterministic
human-review category, and a display-safe summary truncation helper. Nothing in
this module modifies data or calls an LLM.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.models.analysis import Analysis
from app.db.models.company import Company
from app.db.models.vacancy import Vacancy

EXCLUDED_STATUSES = ("ignored", "expired")
RECOMMENDATION_VALUES = ("strong_match", "consider", "weak_match", "reject")
RECOMMENDATION_PRIORITY = {
    "strong_match": 1,
    "consider": 2,
    "weak_match": 3,
    "reject": 4,
}
SHORTLIST_DEFAULT_LIMIT = 50
SHORTLIST_MAX_LIMIT = 200

PRIORITY = "PRIORITY"
REVIEW = "REVIEW"
LOW_PRIORITY = "LOW_PRIORITY"
REJECT = "REJECT"
CATEGORIES = (PRIORITY, REVIEW, LOW_PRIORITY, REJECT)


@dataclass(frozen=True)
class VacancyShortlistItem:
    """A display-ready shortlist row. Never exposes raw ORM objects."""

    external_id: str
    title: str
    company: str | None
    location: str | None
    source_url: str
    overall_score: int
    technical_score: int
    leadership_score: int
    location_score: int
    recommendation: str
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    risks: list[str]
    first_seen_at: datetime
    analysis_created_at: datetime
    model: str
    prompt_version: str


def _recommendation_priority_expr():
    """SQL expression ordering recommendations by the defined priority."""
    return case(
        (Analysis.recommendation == "strong_match", 1),
        (Analysis.recommendation == "consider", 2),
        (Analysis.recommendation == "weak_match", 3),
        else_=4,
    ).label("recommendation_priority")


def get_vacancy_shortlist(
    db: Session,
    *,
    prompt_version: str,
    qualified_model: str,
    minimum_overall_score: int | None = None,
    recommendations: set[str] | None = None,
    limit: int = SHORTLIST_DEFAULT_LIMIT,
) -> list[VacancyShortlistItem]:
    """Return display-ready shortlist rows from existing analyses.

    Read-only. Uses explicit scalar-column selection with an outer join to
    companies; no ORM relationships are loaded, so rendering after the session
    closes is safe. Ordered by overall score (desc), recommendation priority,
    location score (desc), then first-seen time (desc).
    """
    if not (1 <= limit <= SHORTLIST_MAX_LIMIT):
        raise ValueError(f"limit must be from 1 through {SHORTLIST_MAX_LIMIT}")
    if recommendations is not None:
        unknown = set(recommendations) - set(RECOMMENDATION_VALUES)
        if unknown:
            raise ValueError(f"unknown recommendation values: {sorted(unknown)}")

    stmt = select(
        Vacancy.external_id,
        Vacancy.title,
        Company.name.label("company"),
        Vacancy.location,
        Vacancy.url.label("source_url"),
        Analysis.overall_score,
        Analysis.technical_score,
        Analysis.leadership_score,
        Analysis.location_score,
        Analysis.recommendation,
        Analysis.summary,
        Analysis.strengths,
        Analysis.weaknesses,
        Analysis.risks,
        Vacancy.first_seen_at,
        Analysis.created_at.label("analysis_created_at"),
        Analysis.model,
        Analysis.prompt_version,
    ).join(Analysis, Analysis.vacancy_id == Vacancy.id).outerjoin(
        Company, Company.id == Vacancy.company_id
    ).where(
        Analysis.prompt_version == prompt_version,
        Analysis.model == qualified_model,
        ~Vacancy.status.in_(EXCLUDED_STATUSES),
    )

    if minimum_overall_score is not None:
        stmt = stmt.where(Analysis.overall_score >= minimum_overall_score)
    if recommendations:
        stmt = stmt.where(Analysis.recommendation.in_(recommendations))

    stmt = stmt.order_by(
        Analysis.overall_score.desc(),
        _recommendation_priority_expr(),
        Analysis.location_score.desc(),
        Vacancy.first_seen_at.desc(),
    ).limit(limit)

    rows = db.execute(stmt).all()
    return [
        VacancyShortlistItem(
            external_id=row.external_id,
            title=row.title,
            company=row.company,
            location=row.location,
            source_url=row.source_url,
            overall_score=row.overall_score,
            technical_score=row.technical_score,
            leadership_score=row.leadership_score,
            location_score=row.location_score,
            recommendation=row.recommendation,
            summary=row.summary,
            strengths=list(row.strengths or []),
            weaknesses=list(row.weaknesses or []),
            risks=list(row.risks or []),
            first_seen_at=row.first_seen_at,
            analysis_created_at=row.analysis_created_at,
            model=row.model,
            prompt_version=row.prompt_version,
        )
        for row in rows
    ]


def classify_shortlist_item(item: VacancyShortlistItem) -> str:
    """Return a deterministic human-review category for a shortlist item.

    Rules:
    - PRIORITY: strong_match, overall >= 75, and location >= 40.
    - REVIEW: strong/consider with overall >= 60, or overall >= 75 with a low
      location score (a high professional score with low location fit is
      REVIEW, not REJECT).
    - LOW_PRIORITY: weak_match, or overall from 40 through 59.
    - REJECT: recommendation reject, or overall < 40.
    """
    recommendation = item.recommendation
    overall = item.overall_score
    location = item.location_score

    if recommendation == "reject" or overall < 40:
        return REJECT

    if recommendation == "strong_match" and overall >= 75 and location >= 40:
        return PRIORITY

    if (
        recommendation in ("strong_match", "consider") and overall >= 60
    ) or (overall >= 75 and location < 40):
        return REVIEW

    if recommendation == "weak_match" or 40 <= overall <= 59:
        return LOW_PRIORITY

    # Fallback for unexpected recommendation values / edge combinations.
    if overall >= 60:
        return REVIEW
    return LOW_PRIORITY


def compact_summary(summary: str, maximum_characters: int = 500) -> str:
    """Collapse whitespace and truncate a summary for display only.

    Never modifies stored data. Preserves a sentence boundary where practical
    and appends an ellipsis when truncated.
    """
    compact = " ".join(summary.split())
    if len(compact) <= maximum_characters:
        return compact
    truncated = compact[:maximum_characters]
    if "." in truncated:
        cut = truncated.rfind(".")
        if cut > maximum_characters // 2:
            truncated = truncated[: cut + 1]
    return truncated.rstrip() + "..."
