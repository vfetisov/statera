"""Ingest LinkedIn job previews into PostgreSQL.

Reads up to 10 currently available LinkedIn cards with the existing smoke
reader, then upserts source/search/company/vacancy rows in a single
transaction. Safe to run repeatedly.

Never prints cookies, storage state, the database password, or DATABASE_URL.
"""

import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.vacancy_ingestion import ingest_linkedin_previews  # noqa: E402
from app.sources.linkedin.smoke import read_saved_search  # noqa: E402

DEFAULT_LIMIT = 10


def _resolve_storage_state(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    search_url = settings.LINKEDIN_SEARCH_URL
    if not search_url:
        print(
            "LINKEDIN_SEARCH_URL is not set. "
            "Add it to .env (see .env.example).",
            file=sys.stderr,
        )
        return 1

    storage_state = _resolve_storage_state(settings.LINKEDIN_STORAGE_STATE)

    try:
        previews = read_saved_search(
            search_url=search_url,
            storage_state_path=storage_state,
            limit=DEFAULT_LIMIT,
            debug_pause=settings.LINKEDIN_DEBUG_PAUSE,
            dump_dom=settings.LINKEDIN_DUMP_DOM,
            headless=settings.PLAYWRIGHT_HEADLESS,
        )
    except Exception as exc:
        print(
            f"LinkedIn ingestion FAILED while reading: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    db = SessionLocal()
    try:
        result = ingest_linkedin_previews(
            db, search_url=search_url, previews=previews
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        print(
            f"LinkedIn ingestion FAILED while persisting: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()

    print(
        json.dumps(
            {
                "source_created": result.source_created,
                "search_created": result.search_created,
                "companies_created": result.companies_created,
                "vacancies_created": result.vacancies_created,
                "vacancies_updated": result.vacancies_updated,
                "vacancies_unchanged": result.vacancies_unchanged,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
