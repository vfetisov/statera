"""Context builder for vacancy-fit analysis.

This module has no provider imports. It selects only the assets that fit
analysis actually needs: the full Master Career Brief (required) and the
optional SCORING_RULES. Master Resume, Resume Template, and Application Rules
are intentionally not included.
"""

from app.career.assets import CareerAssetType
from app.career.registry import CareerAssetRegistry
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.llm.context.models import (
    TaskAssetReference,
    VacancyAnalysisContext,
    VacancyMetadata,
)
from app.llm.errors import ContextSizeExceededError


def build_vacancy_analysis_context(
    registry: CareerAssetRegistry,
    vacancy: Vacancy,
    vacancy_content: VacancyContent,
    prompt_version: str,
) -> VacancyAnalysisContext:
    """Assemble the provider-neutral fit-analysis context for one vacancy.

    Sources are never summarized or truncated here.
    """
    if not prompt_version or not prompt_version.strip():
        raise ValueError("prompt_version must not be empty")

    brief = registry.get_required(CareerAssetType.MASTER_CAREER_BRIEF)
    scoring = registry.get_optional(CareerAssetType.SCORING_RULES)

    description = vacancy_content.raw_text or vacancy_content.markdown or ""
    if not description.strip():
        raise ValueError(f"vacancy {vacancy.external_id} has an empty description")

    metadata = VacancyMetadata(
        external_id=vacancy.external_id,
        title=vacancy.title,
        company=vacancy.company.name if vacancy.company is not None else None,
        location=vacancy.location,
        source_url=vacancy.url,
    )

    references = [
        TaskAssetReference(
            asset_type=brief.asset_type.value,
            content_hash=brief.content_hash,
            character_count=brief.character_count,
        )
    ]
    if scoring is not None:
        references.append(
            TaskAssetReference(
                asset_type=scoring.asset_type.value,
                content_hash=scoring.content_hash,
                character_count=scoring.character_count,
            )
        )

    return VacancyAnalysisContext(
        candidate_profile=brief.text,
        vacancy=metadata,
        vacancy_description=description,
        scoring_rules=scoring.text if scoring is not None else None,
        prompt_version=prompt_version.strip(),
        asset_references=tuple(references),
    )


def _context_character_count(context: VacancyAnalysisContext) -> int:
    blocks = [
        context.candidate_profile,
        context.vacancy_description,
        context.vacancy.external_id,
        context.vacancy.title,
        context.vacancy.company or "",
        context.vacancy.location or "",
        context.vacancy.source_url,
    ]
    if context.scoring_rules is not None:
        blocks.append(context.scoring_rules)
    return sum(len(block) for block in blocks)


def validate_context_character_limits(
    context: VacancyAnalysisContext,
    maximum_characters: int | None,
) -> None:
    """Conservative provider-neutral context-size safety check.

    ``None`` disables the check. When the package exceeds the limit, an error
    is raised with actual and allowed counts. The context is never truncated
    and never silently swapped for a compact profile.
    """
    if maximum_characters is None:
        return
    actual = _context_character_count(context)
    if actual > maximum_characters:
        raise ContextSizeExceededError(
            f"vacancy analysis context is {actual} characters, which exceeds "
            f"the configured maximum of {maximum_characters}."
        )
