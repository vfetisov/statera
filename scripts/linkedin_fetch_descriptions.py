"""Fetch full LinkedIn job descriptions and persist the current one per vacancy.

Selects up to ``LINKEDIN_DESCRIPTION_FETCH_LIMIT`` LinkedIn vacancies that have
no ``vacancy_contents`` row, fetches each description, and upserts the current
content (version always 1). One failed vacancy does not abort the batch.

Never prints full descriptions, cookies, storage state, passwords, or
DATABASE_URL.
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
from app.services.vacancy_content import (  # noqa: E402
    fetch_missing_vacancy_descriptions,
)


def _resolve_storage_state(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    storage_state = _resolve_storage_state(settings.LINKEDIN_STORAGE_STATE)
    limit = settings.LINKEDIN_DESCRIPTION_FETCH_LIMIT

    db = SessionLocal()
    try:
        result = fetch_missing_vacancy_descriptions(
            db,
            storage_state_path=storage_state,
            limit=limit,
            debug_pause=settings.LINKEDIN_DEBUG_PAUSE,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        print(
            f"LinkedIn description fetch FAILED: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()

    print(
        json.dumps(
            {
                "selected": result.selected,
                "fetched": result.fetched,
                "created": result.created,
                "updated": result.updated,
                "unchanged": result.unchanged,
                "failed": result.failed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
