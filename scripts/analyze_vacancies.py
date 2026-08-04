"""Analyze pending vacancies with the configured LLM provider.

Selects vacancies that have a current full description but no analysis for the
configured provider/model and prompt version, runs fit analysis through the
provider-neutral LLM layer, and persists results to ``analyses``.

Never prints prompts, full career assets, vacancy descriptions, complete
analysis bodies, API keys, or DATABASE_URL.
"""

import json
import sys
from pathlib import Path

# Make the project root importable when this file is run as a plain script.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.career.registry import (  # noqa: E402
    CareerAssetPaths,
    load_career_asset_registry,
)
from app.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.llm.providers.factory import create_llm_provider  # noqa: E402
from app.services.vacancy_analysis import analyze_pending_vacancies  # noqa: E402


def _resolve_asset_path(raw: str | None) -> Path | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def main() -> int:
    master_brief = _resolve_asset_path(settings.MASTER_CAREER_BRIEF_PATH)
    if master_brief is None:
        print(
            "MASTER_CAREER_BRIEF_PATH is not set. "
            "Add it to .env (see .env.example).",
            file=sys.stderr,
        )
        return 1

    paths = CareerAssetPaths(
        master_career_brief=master_brief,
        master_resume=_resolve_asset_path(settings.MASTER_RESUME_PATH),
        resume_template=_resolve_asset_path(settings.RESUME_TEMPLATE_PATH),
        application_rules=_resolve_asset_path(settings.APPLICATION_RULES_PATH),
        scoring_rules=_resolve_asset_path(settings.SCORING_RULES_PATH),
    )

    try:
        registry = load_career_asset_registry(paths)
        provider = create_llm_provider(settings)
    except Exception as exc:
        print(
            f"Vacancy analysis setup FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    db = SessionLocal()
    try:
        result = analyze_pending_vacancies(
            db,
            provider=provider,
            registry=registry,
            model=settings.LLM_MODEL,
            reasoning_effort=settings.LLM_REASONING_EFFORT,
            prompt_version=settings.VACANCY_ANALYSIS_PROMPT_VERSION,
            limit=settings.VACANCY_ANALYSIS_BATCH_LIMIT,
            maximum_context_characters=settings.LLM_MAX_CONTEXT_CHARACTERS,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        print(
            f"Vacancy analysis FAILED: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()

    print(
        json.dumps(
            {
                "provider": provider.name,
                "model": settings.LLM_MODEL,
                "selected": result.selected,
                "analyzed": result.analyzed,
                "created": result.created,
                "skipped": result.skipped,
                "failed": result.failed,
                "retried": result.retried,
                "recovered_after_retry": result.recovered_after_retry,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
