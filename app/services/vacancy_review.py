"""Human-review web service for analyzed vacancies.

Read-only list/detail queries plus status-mutation helpers for the review
interface. Uses explicit scalar-column SQLAlchemy queries so rendering never
lazy-loads ORM relationships after the session closes. Never commits; the HTTP
route owns commit and rollback. No LLM calls and no LinkedIn data collection
happen here.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models.analysis import Analysis
from app.db.models.company import Company
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.services.vacancy_shortlist import classify_scores

VALID_STATUSES = ("new", "selected", "ignored", "applied")
VALID_SORTS = ("overall", "leadership", "technical", "location", "newest")
VALID_CATEGORIES = ("PRIORITY", "REVIEW", "LOW_PRIORITY", "REJECT")
VALID_RECOMMENDATIONS = ("strong_match", "consider", "weak_match", "reject")

ALLOWED_TRANSITIONS = {
    "new": ("selected", "ignored"),
    "selected": ("new", "ignored", "applied"),
    "ignored": ("new", "selected"),
    "applied": ("selected",),
}


class VacancyNotFoundError(Exception):
    """The vacancy does not exist or has no matching current analysis."""


class InvalidVacancyStatusTransition(Exception):
    """A status change is not allowed for the vacancy's current status."""

    def __init__(self, current_status: str, requested_status: str) -> None:
        self.current_status = current_status
        self.requested_status = requested_status
        super().__init__(
            f"invalid status transition {current_status} -> {requested_status}"
        )


@dataclass(frozen=True)
class VacancyListItem:
    """One display-ready row for the review list."""

    external_id: str
    title: str
    company: str | None
    location: str | None
    source_url: str
    status: str
    overall_score: int
    technical_score: int
    leadership_score: int
    location_score: int
    recommendation: str
    category: str
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    risks: list[str]
    first_seen_at: datetime
    analysis_created_at: datetime


@dataclass(frozen=True)
class VacancyDetail:
    """Everything the detail page needs, including the full job description."""

    external_id: str
    title: str
    company: str | None
    location: str | None
    source_url: str
    status: str
    overall_score: int
    technical_score: int
    leadership_score: int
    location_score: int
    recommendation: str
    category: str
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    risks: list[str]
    first_seen_at: datetime
    analysis_created_at: datetime
    jd_text: str
    description_length: int
    model: str
    prompt_version: str


@dataclass(frozen=True)
class VacancyReviewPage:
    """One page of the review list plus pagination metadata."""

    items: list[VacancyListItem]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def _recommendation_priority_expr():
    return case(
        (Analysis.recommendation == "strong_match", 1),
        (Analysis.recommendation == "consider", 2),
        (Analysis.recommendation == "weak_match", 3),
        else_=4,
    ).label("recommendation_priority")


def _fetch_review_rows(
    db: Session,
    *,
    prompt_version: str,
    qualified_model: str,
    status: str | None,
    recommendation: str | None,
    minimum_score: int | None,
    sort: str,
):
    stmt = select(
        Vacancy.external_id,
        Vacancy.title,
        Company.name.label("company"),
        Vacancy.location,
        Vacancy.url.label("source_url"),
        Vacancy.status,
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
    ).join(Analysis, Analysis.vacancy_id == Vacancy.id).outerjoin(
        Company, Company.id == Vacancy.company_id
    ).where(
        Analysis.prompt_version == prompt_version,
        Analysis.model == qualified_model,
    )

    if status is not None:
        stmt = stmt.where(Vacancy.status == status)
    if recommendation is not None:
        stmt = stmt.where(Analysis.recommendation == recommendation)
    if minimum_score is not None:
        stmt = stmt.where(Analysis.overall_score >= minimum_score)

    if sort == "newest":
        stmt = stmt.order_by(Vacancy.first_seen_at.desc())
    elif sort in ("leadership", "technical", "location"):
        score_column = {
            "leadership": Analysis.leadership_score,
            "technical": Analysis.technical_score,
            "location": Analysis.location_score,
        }[sort]
        stmt = stmt.order_by(
            score_column.desc(),
            Analysis.overall_score.desc(),
            Vacancy.first_seen_at.desc(),
        )
    else:  # overall
        stmt = stmt.order_by(
            Analysis.overall_score.desc(),
            _recommendation_priority_expr(),
            Analysis.location_score.desc(),
            Vacancy.first_seen_at.desc(),
        )

    return list(db.execute(stmt).all())


def get_review_vacancies(
    db: Session,
    *,
    prompt_version: str,
    qualified_model: str,
    status: str | None = None,
    category: str | None = None,
    recommendation: str | None = None,
    minimum_score: int | None = None,
    sort: str = "overall",
    page: int = 1,
    page_size: int = 20,
) -> VacancyReviewPage:
    """Return one page of review-list rows matching the filters.

    Category is derived from scores, so it is applied after the SQL query and
    before pagination, which keeps ``total_items`` correct.
    """
    if sort not in VALID_SORTS:
        raise ValueError(f"invalid sort: {sort}")
    if page < 1:
        raise ValueError("page must be at least 1")
    if not (1 <= page_size <= 200):
        raise ValueError("page_size must be from 1 through 200")
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if category is not None and category not in VALID_CATEGORIES:
        raise ValueError(f"invalid category: {category}")
    if recommendation is not None and recommendation not in VALID_RECOMMENDATIONS:
        raise ValueError(f"invalid recommendation: {recommendation}")
    if minimum_score is not None and not (0 <= minimum_score <= 100):
        raise ValueError("minimum_score must be from 0 through 100")

    rows = _fetch_review_rows(
        db,
        prompt_version=prompt_version,
        qualified_model=qualified_model,
        status=status,
        recommendation=recommendation,
        minimum_score=minimum_score,
        sort=sort,
    )
    items = [
        VacancyListItem(
            external_id=row.external_id,
            title=row.title,
            company=row.company,
            location=row.location,
            source_url=row.source_url,
            status=row.status,
            overall_score=row.overall_score,
            technical_score=row.technical_score,
            leadership_score=row.leadership_score,
            location_score=row.location_score,
            recommendation=row.recommendation,
            category=classify_scores(row.recommendation, row.overall_score, row.location_score),
            summary=row.summary,
            strengths=list(row.strengths or []),
            weaknesses=list(row.weaknesses or []),
            risks=list(row.risks or []),
            first_seen_at=row.first_seen_at,
            analysis_created_at=row.analysis_created_at,
        )
        for row in rows
    ]
    if category is not None:
        items = [item for item in items if item.category == category]

    total_items = len(items)
    total_pages = max(1, math.ceil(total_items / page_size)) if total_items else 1
    start = (page - 1) * page_size
    paged = items[start : start + page_size]
    return VacancyReviewPage(
        items=paged,
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=total_pages,
    )


def get_review_vacancy(
    db: Session,
    *,
    external_id: str,
    prompt_version: str,
    qualified_model: str,
) -> VacancyDetail | None:
    """Return one vacancy detail (matching current analysis) or None."""
    row = db.execute(
        select(
            Vacancy.external_id,
            Vacancy.title,
            Company.name.label("company"),
            Vacancy.location,
            Vacancy.url.label("source_url"),
            Vacancy.status,
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
            func.coalesce(
                VacancyContent.raw_text, VacancyContent.markdown, ""
            ).label("jd_text"),
        )
        .join(
            Analysis,
            (Analysis.vacancy_id == Vacancy.id)
            & (Analysis.prompt_version == prompt_version)
            & (Analysis.model == qualified_model),
        )
        .outerjoin(Company, Company.id == Vacancy.company_id)
        .outerjoin(VacancyContent, VacancyContent.vacancy_id == Vacancy.id)
        .where(Vacancy.external_id == external_id)
    ).first()
    if row is None:
        return None

    jd_text = row.jd_text or ""
    return VacancyDetail(
        external_id=row.external_id,
        title=row.title,
        company=row.company,
        location=row.location,
        source_url=row.source_url,
        status=row.status,
        overall_score=row.overall_score,
        technical_score=row.technical_score,
        leadership_score=row.leadership_score,
        location_score=row.location_score,
        recommendation=row.recommendation,
        category=classify_scores(row.recommendation, row.overall_score, row.location_score),
        summary=row.summary,
        strengths=list(row.strengths or []),
        weaknesses=list(row.weaknesses or []),
        risks=list(row.risks or []),
        first_seen_at=row.first_seen_at,
        analysis_created_at=row.analysis_created_at,
        jd_text=jd_text,
        description_length=len(jd_text),
        model=row.model,
        prompt_version=row.prompt_version,
    )


def count_vacancies_by_status(
    db: Session,
    *,
    prompt_version: str,
    qualified_model: str,
) -> dict[str, int]:
    """Count review-status vacancies that have a matching current analysis."""
    rows = db.execute(
        select(
            Vacancy.status,
            func.count(func.distinct(Vacancy.id)).label("cnt"),
        )
        .join(Analysis, Analysis.vacancy_id == Vacancy.id)
        .where(
            Analysis.prompt_version == prompt_version,
            Analysis.model == qualified_model,
        )
        .group_by(Vacancy.status)
    ).all()
    counts = {"new": 0, "selected": 0, "ignored": 0, "applied": 0}
    for row in rows:
        if row.status in counts:
            counts[row.status] = row.cnt
    return counts


def set_vacancy_review_status(
    db: Session,
    *,
    external_id: str,
    status: str,
) -> None:
    """Set a vacancy's review status. Never commits.

    Validates the external ID, the target status, and the transition from the
    vacancy's current status. Unknown vacancies raise ``VacancyNotFoundError``;
    forbidden transitions raise ``InvalidVacancyStatusTransition``.
    """
    if not external_id.isdigit():
        raise ValueError("external_id must be numeric")
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")

    vacancy = db.scalar(select(Vacancy).where(Vacancy.external_id == external_id))
    if vacancy is None:
        raise VacancyNotFoundError(external_id)

    current = vacancy.status
    if current != status and status not in ALLOWED_TRANSITIONS.get(current, ()):
        raise InvalidVacancyStatusTransition(
            current_status=current, requested_status=status
        )
    vacancy.status = status
