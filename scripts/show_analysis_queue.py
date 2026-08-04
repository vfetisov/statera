"""Show vacancies waiting for fit analysis without calling any LLM.

Read-only. Lists up to 50 vacancies that have a current description but no
analysis for the configured provider/model and prompt version, one compact
JSON object per vacancy, plus a final count on stderr.
"""

import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models.analysis import Analysis  # noqa: E402
from app.db.models.company import Company  # noqa: E402
from app.db.models.vacancy import Vacancy  # noqa: E402
from app.db.models.vacancy_content import VacancyContent  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.vacancy_analysis import qualified_model_name  # noqa: E402

QUEUE_LIMIT = 50
EXCLUDED_STATUSES = ("ignored", "expired")


def main() -> int:
    qualified = qualified_model_name(settings.LLM_PROVIDER, settings.LLM_MODEL)
    prompt_version = settings.VACANCY_ANALYSIS_PROMPT_VERSION

    already_analyzed = select(Analysis.vacancy_id).where(
        Analysis.model == qualified,
        Analysis.prompt_version == prompt_version,
    )

    stmt = (
        select(
            Vacancy.external_id,
            Vacancy.title,
            Company.name.label("company"),
            Vacancy.location,
            func.length(
                func.coalesce(VacancyContent.raw_text, VacancyContent.markdown, "")
            ).label("description_length"),
            Vacancy.first_seen_at,
        )
        .join(VacancyContent, VacancyContent.vacancy_id == Vacancy.id)
        .outerjoin(Company, Company.id == Vacancy.company_id)
        .where(
            ~Vacancy.status.in_(EXCLUDED_STATUSES),
            ~Vacancy.id.in_(already_analyzed),
        )
        .order_by(Vacancy.first_seen_at.asc(), Vacancy.external_id.asc())
        .limit(QUEUE_LIMIT)
    )

    db = SessionLocal()
    try:
        rows = db.execute(stmt).all()
    except Exception as exc:
        print(
            f"Could not inspect analysis queue: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()

    count = 0
    for row in rows:
        print(
            json.dumps(
                {
                    "external_id": row.external_id,
                    "title": row.title,
                    "company": row.company,
                    "location": row.location,
                    "description_length": row.description_length,
                    "first_seen_at": (
                        row.first_seen_at.isoformat()
                        if row.first_seen_at is not None
                        else None
                    ),
                },
                ensure_ascii=False,
            )
        )
        count += 1

    print(f"{count} vacancies awaiting analysis", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
