"""Current-only vacancy-content persistence and description-fetch batch.

Statera keeps one ``vacancy_contents`` row per vacancy (version always 1).
Description changes update that row in place instead of creating history.
"""

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.job_source import JobSource
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.sources.linkedin.description import (
    LinkedInJobDescription,
    calculate_content_hash,
    fetch_linkedin_job_description,
    normalize_job_description,
)

LINKEDIN_SOURCE_CODE = "linkedin"
EXCLUDED_STATUSES = ("ignored", "expired")


@dataclass
class VacancyContentUpsertResult:
    """Outcome of storing the current description for one vacancy."""

    created: bool = False
    updated: bool = False
    unchanged: bool = False


@dataclass
class VacancyDescriptionBatchResult:
    """Summary of one description-fetch batch."""

    selected: int = 0
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0


def _current_content_rows(db: Session, vacancy_id) -> list[VacancyContent]:
    """Content rows for a vacancy ordered by version, then created_at."""
    return list(
        db.scalars(
            select(VacancyContent)
            .where(VacancyContent.vacancy_id == vacancy_id)
            .order_by(VacancyContent.version.asc(), VacancyContent.created_at.asc())
        )
    )


def upsert_current_vacancy_content(
    db: Session,
    vacancy: Vacancy,
    description: LinkedInJobDescription,
) -> VacancyContentUpsertResult:
    """Store the current description for a vacancy, one row per vacancy.

    ``version`` stays 1; a changed description updates the existing row in
    place. Never commits. If more than one content row already exists, raises
    an explicit error instead of guessing or deleting data.
    """
    normalized_text = normalize_job_description(description.raw_text)
    content_hash = calculate_content_hash(normalized_text)
    now = datetime.now(timezone.utc)

    rows = _current_content_rows(db, vacancy.id)
    if len(rows) > 1:
        raise RuntimeError(
            f"vacancy {vacancy.external_id} has {len(rows)} vacancy_contents "
            "rows; expected at most one. Refusing to guess which is current."
        )

    if not rows:
        db.add(
            VacancyContent(
                vacancy_id=vacancy.id,
                version=1,
                content_hash=content_hash,
                raw_text=normalized_text,
                markdown=description.markdown,
                html_artifact_key=None,
                fetched_at=now,
            )
        )
        return VacancyContentUpsertResult(created=True)

    current = rows[0]
    if current.content_hash == content_hash:
        # No content change; only refresh when it was fetched.
        current.fetched_at = now
        return VacancyContentUpsertResult(unchanged=True)

    current.version = 1
    current.content_hash = content_hash
    current.raw_text = normalized_text
    current.markdown = description.markdown
    current.fetched_at = now
    current.updated_at = now
    return VacancyContentUpsertResult(updated=True)


def _select_vacancies_for_description_fetch(
    db: Session, limit: int
) -> list[Vacancy]:
    """LinkedIn vacancies with no content row, oldest first."""
    content_vacancy_ids = select(VacancyContent.vacancy_id)
    return list(
        db.scalars(
            select(Vacancy)
            .join(JobSource, Vacancy.source_id == JobSource.id)
            .where(
                JobSource.code == LINKEDIN_SOURCE_CODE,
                ~Vacancy.id.in_(content_vacancy_ids),
                ~Vacancy.status.in_(EXCLUDED_STATUSES),
            )
            .order_by(Vacancy.first_seen_at.asc(), Vacancy.external_id.asc())
            .limit(limit)
        )
    )


def fetch_missing_vacancy_descriptions(
    db: Session,
    storage_state_path: Path,
    limit: int = 5,
    debug_pause: bool = False,
) -> VacancyDescriptionBatchResult:
    """Fetch descriptions for LinkedIn vacancies missing content.

    Each vacancy is processed in its own savepoint so a single failure does
    not roll back successful vacancies. The caller owns the outer transaction
    and commit; this function never commits or closes the session.
    """
    vacancies = _select_vacancies_for_description_fetch(db, limit)
    result = VacancyDescriptionBatchResult(selected=len(vacancies))

    for vacancy in vacancies:
        try:
            with db.begin_nested():
                description = fetch_linkedin_job_description(
                    external_id=vacancy.external_id,
                    storage_state_path=storage_state_path,
                    debug_pause=debug_pause,
                )
                upsert = upsert_current_vacancy_content(db, vacancy, description)
        except Exception as exc:
            result.failed += 1
            print(
                f"failed to fetch description for vacancy {vacancy.external_id}: "
                f"{type(exc).__name__}",
                file=sys.stderr,
            )
            continue

        result.fetched += 1
        if upsert.created:
            result.created += 1
        elif upsert.updated:
            result.updated += 1
        elif upsert.unchanged:
            result.unchanged += 1

    return result
