"""Provider-neutral context models assembled before a prompt is built.

Each task gets its own context type. The vacancy-fit context deliberately
includes only the assets that fit analysis needs.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskAssetReference:
    """A reference to an asset actually used by a task context."""

    asset_type: str
    content_hash: str
    character_count: int


@dataclass(frozen=True)
class VacancyMetadata:
    """Provider-neutral metadata about a vacancy (no secrets)."""

    external_id: str
    title: str
    company: str | None
    location: str | None
    source_url: str


@dataclass(frozen=True)
class VacancyAnalysisContext:
    """Everything a fit-analysis prompt needs (provider-neutral)."""

    candidate_profile: str
    vacancy: VacancyMetadata
    vacancy_description: str
    scoring_rules: str | None
    prompt_version: str
    asset_references: tuple[TaskAssetReference, ...]
