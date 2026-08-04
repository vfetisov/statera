"""Show detailed vacancy-fit analysis for one vacancy.

Read-only. Never calls an LLM and never modifies data. Prints all stored
analysis fields for the configured prompt version and qualified model. The full
job description is hidden unless ``--show-description`` is passed.

Usage:

    python scripts/show_vacancy_details.py 4429016090
    python scripts/show_vacancy_details.py 4429016090 --show-description
"""

import argparse
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.models.analysis import Analysis  # noqa: E402
from app.db.models.company import Company  # noqa: E402
from app.db.models.vacancy import Vacancy  # noqa: E402
from app.db.models.vacancy_content import VacancyContent  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.vacancy_analysis import qualified_model_name  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show stored vacancy-fit analysis for one vacancy."
    )
    parser.add_argument("external_id", help="numeric LinkedIn job ID")
    parser.add_argument(
        "--show-description",
        action="store_true",
        dest="show_description",
        help="also print the full normalized job description",
    )
    return parser.parse_args(argv)


def _print_details(vacancy, company_name, analysis, content, *, show_description: bool) -> None:
    jd_text = ""
    if content is not None:
        jd_text = content.raw_text or content.markdown or ""

    print(f"Title: {vacancy.title}")
    print(f"Company: {company_name or 'Not specified'}")
    print(f"Location: {vacancy.location or 'Not specified'}")
    print(f"LinkedIn: {vacancy.url}")
    print(f"Status: {vacancy.status}")
    print("")
    print("Scores:")
    print(f"  overall: {analysis.overall_score}")
    print(f"  technical: {analysis.technical_score}")
    print(f"  leadership: {analysis.leadership_score}")
    print(f"  location: {analysis.location_score}")
    print(f"Recommendation: {analysis.recommendation}")
    print(f"Summary: {analysis.summary}")
    print("Strengths:")
    for strength in analysis.strengths or []:
        print(f"- {strength}")
    print("Weaknesses:")
    for weakness in analysis.weaknesses or []:
        print(f"- {weakness}")
    print("Risks:")
    for risk in analysis.risks or []:
        print(f"- {risk}")
    print(f"Model: {analysis.model}")
    print(f"Prompt version: {analysis.prompt_version}")
    print(f"Analysis time: {analysis.created_at.isoformat()}")
    print(f"JD character count: {len(jd_text)}")

    if show_description:
        print("")
        print("JOB DESCRIPTION")
        print(jd_text)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    external_id = args.external_id.strip()
    if not external_id.isdigit():
        print(
            f"Invalid external ID: {external_id!r} "
            "(expected a numeric LinkedIn job ID).",
            file=sys.stderr,
        )
        return 1

    qualified = qualified_model_name(settings.LLM_PROVIDER, settings.LLM_MODEL)
    prompt_version = settings.VACANCY_ANALYSIS_PROMPT_VERSION

    db = SessionLocal()
    try:
        row = db.execute(
            select(Vacancy, Company.name.label("company_name"))
            .outerjoin(Company, Company.id == Vacancy.company_id)
            .where(Vacancy.external_id == external_id)
        ).first()
        if row is None:
            print(f"Vacancy not found: {external_id}", file=sys.stderr)
            return 1
        vacancy = row[0]
        company_name = row.company_name

        analysis = db.scalar(
            select(Analysis)
            .where(
                Analysis.vacancy_id == vacancy.id,
                Analysis.prompt_version == prompt_version,
                Analysis.model == qualified,
            )
            .order_by(Analysis.created_at.desc())
            .limit(1)
        )
        if analysis is None:
            print(
                f"No analysis for vacancy {external_id} with prompt "
                f"{prompt_version} and model {qualified}.",
                file=sys.stderr,
            )
            return 1

        content = db.scalar(
            select(VacancyContent)
            .where(VacancyContent.vacancy_id == vacancy.id)
            .order_by(
                VacancyContent.version.desc(), VacancyContent.created_at.desc()
            )
            .limit(1)
        )
    except Exception as exc:
        print(f"Could not load vacancy details: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        db.close()

    _print_details(
        vacancy,
        company_name,
        analysis,
        content,
        show_description=args.show_description,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
