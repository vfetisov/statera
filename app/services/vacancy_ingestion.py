"""Persist LinkedIn job previews into PostgreSQL.

Idempotent batch upsert: job sources, saved searches, companies and vacancies
are queried first and created only when missing. All writes happen inside a
single transaction that is owned and committed by the caller.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.company import Company
from app.db.models.job_source import JobSource
from app.db.models.search import Search
from app.db.models.vacancy import Vacancy
from app.sources.linkedin.smoke import LinkedInJobPreview

LINKEDIN_SOURCE_CODE = "linkedin"
LINKEDIN_SOURCE_NAME = "LinkedIn"
LINKEDIN_SEARCH_NAME = "LinkedIn saved search"


@dataclass
class VacancyIngestionResult:
    """Summary of one ingestion batch."""

    source_created: bool = False
    search_created: bool = False
    companies_created: int = 0
    vacancies_created: int = 0
    vacancies_updated: int = 0
    vacancies_unchanged: int = 0


def normalize_company_name(name: str) -> str:
    """Normalize a company name for stable matching.

    Trims whitespace, collapses repeated whitespace and lowercases. Punctuation
    is preserved; no fuzzy matching is performed.
    """
    return " ".join(name.split()).lower()


def _get_or_create_source(db: Session) -> tuple[JobSource, bool]:
    """Return the LinkedIn job source, creating it once if needed."""
    source = db.scalar(
        select(JobSource).where(JobSource.code == LINKEDIN_SOURCE_CODE)
    )
    if source is not None:
        return source, False
    source = JobSource(
        code=LINKEDIN_SOURCE_CODE,
        name=LINKEDIN_SOURCE_NAME,
        enabled=True,
    )
    db.add(source)
    db.flush()  # source.id is required by the search row
    return source, True


def _get_or_create_search(
    db: Session, source: JobSource, search_url: str
) -> tuple[Search, bool]:
    """Return the saved search for this source+url, creating it once if needed."""
    search = db.scalar(
        select(Search).where(
            Search.source_id == source.id,
            Search.url == search_url,
        )
    )
    if search is not None:
        return search, False
    search = Search(
        source_id=source.id,
        name=LINKEDIN_SEARCH_NAME,
        url=search_url,
        enabled=True,
    )
    db.add(search)
    db.flush()  # search.id is required by vacancy rows
    return search, True


def _get_or_create_company(
    db: Session, company_name: str
) -> tuple[Company | None, bool]:
    """Return the company matching the normalized name, creating it once.

    On creation the display name is the original trimmed name; on reuse the
    existing display name is never overwritten.
    """
    name = (company_name or "").strip()
    if not name:
        return None, False
    normalized = normalize_company_name(name)
    company = db.scalar(
        select(Company).where(Company.normalized_name == normalized)
    )
    if company is not None:
        return company, False
    company = Company(name=name, normalized_name=normalized)
    db.add(company)
    db.flush()  # company.id is required by vacancy rows
    return company, True


def _upsert_vacancy(
    db: Session,
    source: JobSource,
    search: Search,
    company_id: uuid.UUID | None,
    preview: LinkedInJobPreview,
    now: datetime,
) -> str:
    """Create or update one vacancy; returns created/updated/unchanged."""
    vacancy = db.scalar(
        select(Vacancy).where(
            Vacancy.source_id == source.id,
            Vacancy.external_id == preview.external_id,
        )
    )

    if vacancy is None:
        vacancy = Vacancy(
            source_id=source.id,
            search_id=search.id,
            company_id=company_id,
            external_id=preview.external_id,
            url=preview.url or "",
            title=preview.title,
            location=preview.location,
            status="new",
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(vacancy)
        return "created"

    changed = False

    # Always updated for a previously seen vacancy.
    if vacancy.search_id != search.id:
        vacancy.search_id = search.id
        changed = True
    vacancy.last_seen_at = now

    # Updated only when the incoming value is non-empty.
    for field in ("title", "url", "location"):
        incoming = getattr(preview, field)
        if incoming and getattr(vacancy, field) != incoming:
            setattr(vacancy, field, incoming)
            changed = True
    if company_id is not None and vacancy.company_id != company_id:
        vacancy.company_id = company_id
        changed = True

    # first_seen_at and status are never touched on update.
    return "updated" if changed else "unchanged"


def ingest_linkedin_previews(
    db: Session,
    search_url: str,
    previews: list[LinkedInJobPreview],
) -> VacancyIngestionResult:
    """Persist a batch of LinkedIn previews in a single transaction.

    The caller owns the transaction: this function never commits, rolls back,
    or closes the session. Previews without an external id or title are
    skipped, and the input is deduplicated by external id (first appearance
    wins).
    """
    result = VacancyIngestionResult()

    # Deduplicate by external id preserving first appearance, and drop
    # previews that cannot be persisted.
    seen: set[str] = set()
    unique: list[LinkedInJobPreview] = []
    for preview in previews:
        if not preview.external_id or not preview.title:
            continue
        if preview.external_id in seen:
            continue
        seen.add(preview.external_id)
        unique.append(preview)

    source, result.source_created = _get_or_create_source(db)
    search, result.search_created = _get_or_create_search(db, source, search_url)

    now = datetime.now(timezone.utc)

    for preview in unique:
        company_id = None
        if preview.company and preview.company.strip():
            company, company_created = _get_or_create_company(db, preview.company)
            company_id = company.id
            if company_created:
                result.companies_created += 1

        status = _upsert_vacancy(db, source, search, company_id, preview, now)
        if status == "created":
            result.vacancies_created += 1
        elif status == "updated":
            result.vacancies_updated += 1
        else:
            result.vacancies_unchanged += 1

    return result
