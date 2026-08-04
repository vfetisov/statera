"""Provider-neutral structured schemas for LLM results."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Recommendation(str, Enum):
    """Overall fit recommendation for a vacancy."""

    strong_match = "strong_match"
    consider = "consider"
    weak_match = "weak_match"
    reject = "reject"


class VacancyFitAnalysis(BaseModel):
    """Structured vacancy-fit result. Provider-neutral.

    All fields are the source of truth for the persisted ``analyses`` row.
    Extra fields are rejected so a provider cannot smuggle data into the row.
    """

    model_config = ConfigDict(extra="forbid")

    overall_score: int = Field(ge=0, le=100)
    technical_score: int = Field(ge=0, le=100)
    leadership_score: int = Field(ge=0, le=100)
    location_score: int = Field(ge=0, le=100)
    recommendation: Recommendation
    summary: str = Field(min_length=40, max_length=1200)
    strengths: list[str] = Field(default_factory=list, max_length=8)
    weaknesses: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("strengths", "weaknesses", "risks")
    @classmethod
    def _clean_list_items(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("list items must be strings")
            item = item.strip()
            if not item:
                raise ValueError("list items must not be empty")
            if len(item) > 500:
                raise ValueError("list items must be at most 500 characters")
            cleaned.append(item)
        return cleaned


def validate_score_independence(result: VacancyFitAnalysis) -> VacancyFitAnalysis:
    """Re-verify schema constraints and document the v3 scoring semantics.

    This helper does not detect geography from scores and does not rewrite any
    value. It only revalidates the model so a malformed analysis fails fast,
    and it documents the semantics: overall/technical/leadership scores are
    geographic-independent, while ``location_score`` and ``recommendation`` may
    reflect eligibility.
    """
    return VacancyFitAnalysis.model_validate(result.model_dump())
