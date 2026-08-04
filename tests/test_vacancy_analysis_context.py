"""Tests for the vacancy-analysis context builder and size policy."""

from pathlib import Path

import pytest

from app.career.assets import CareerAsset, CareerAssetType
from app.career.registry import CareerAssetRegistry
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.llm.context.vacancy_analysis import (
    build_vacancy_analysis_context,
    validate_context_character_limits,
)
from app.llm.errors import ContextSizeExceededError

BRIEF = CareerAssetType.MASTER_CAREER_BRIEF
SCORING = CareerAssetType.SCORING_RULES
RESUME = CareerAssetType.MASTER_RESUME
TEMPLATE = CareerAssetType.RESUME_TEMPLATE
APPLICATION = CareerAssetType.APPLICATION_RULES

BRIEF_TEXT = (
    "Master career brief with a complete factual history of the candidate. "
    "It includes many paragraphs about leadership, support operations, and "
    "technical accomplishments."
)
SCORING_TEXT = (
    "Scoring rules: overall score reflects practical fit; hard location or "
    "authorization blockers may justify rejection."
)
RESUME_TEXT = (
    "Resume content that must never appear in the fit-analysis context because "
    "the context builder intentionally excludes the master resume."
)
TEMPLATE_TEXT = (
    "Resume template content that must never appear in the fit-analysis "
    "context because the resume template is reserved for tailoring tasks."
)
APPLICATION_TEXT = (
    "Application rules content that must never appear in the fit-analysis "
    "context because application rules are reserved for application tasks."
)
DESCRIPTION = (
    "Full job description for a support engineering lead role. It describes "
    "people leadership, SLA ownership, incident management, and SaaS support "
    "operations in detail."
)


def _asset(asset_type, text, source_format="docx"):
    return CareerAsset(
        asset_type=asset_type,
        source_path=Path(f"/x/{asset_type.value}.{source_format}"),
        source_format=source_format,
        text=text,
        content_hash=f"{asset_type.value}-hash",
        character_count=len(text),
    )


def _full_registry():
    assets = {
        BRIEF: _asset(BRIEF, BRIEF_TEXT),
        SCORING: _asset(SCORING, SCORING_TEXT, "md"),
        RESUME: _asset(RESUME, RESUME_TEXT),
        TEMPLATE: _asset(TEMPLATE, TEMPLATE_TEXT, "md"),
        APPLICATION: _asset(APPLICATION, APPLICATION_TEXT, "md"),
    }
    return CareerAssetRegistry(assets=assets)


def _brief_only_registry():
    return CareerAssetRegistry(assets={BRIEF: _asset(BRIEF, BRIEF_TEXT)})


def _vacancy():
    return Vacancy(
        external_id="12345",
        title="Support Engineering Lead",
        url="https://www.linkedin.com/jobs/view/12345/",
        location="Remote",
    )


def _content():
    return VacancyContent(vacancy_id=None, raw_text=DESCRIPTION, markdown=DESCRIPTION)


def test_full_master_career_brief_is_included():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert context.candidate_profile == BRIEF_TEXT


def test_full_vacancy_description_is_included():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert context.vacancy_description == DESCRIPTION


def test_scoring_rules_included_when_configured():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert context.scoring_rules == SCORING_TEXT


def test_scoring_rules_none_when_absent():
    context = build_vacancy_analysis_context(
        _brief_only_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert context.scoring_rules is None


def test_master_resume_is_not_included():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert RESUME_TEXT not in context.candidate_profile
    types = {ref.asset_type for ref in context.asset_references}
    assert RESUME.value not in types


def test_resume_template_is_not_included():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert TEMPLATE_TEXT not in context.candidate_profile
    types = {ref.asset_type for ref in context.asset_references}
    assert TEMPLATE.value not in types


def test_application_rules_are_not_included():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert APPLICATION_TEXT not in context.candidate_profile
    types = {ref.asset_type for ref in context.asset_references}
    assert APPLICATION.value not in types


def test_asset_references_contain_hashes():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    refs = {ref.asset_type: ref for ref in context.asset_references}
    assert refs[BRIEF.value].content_hash == "master_career_brief-hash"
    assert refs[BRIEF.value].character_count == len(BRIEF_TEXT)
    assert refs[SCORING.value].content_hash == "scoring_rules-hash"


def test_vacancy_metadata_is_populated():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    assert context.vacancy.external_id == "12345"
    assert context.vacancy.title == "Support Engineering Lead"
    assert context.vacancy.location == "Remote"
    assert context.vacancy.source_url == "https://www.linkedin.com/jobs/view/12345/"


def test_context_size_overflow_raises_instead_of_truncating():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )

    with pytest.raises(ContextSizeExceededError) as exc_info:
        validate_context_character_limits(context, maximum_characters=1)

    message = str(exc_info.value)
    assert "characters" in message
    assert "exceeds the configured maximum of 1" in message
    assert context.candidate_profile == BRIEF_TEXT


def test_context_size_check_disabled_when_none():
    context = build_vacancy_analysis_context(
        _full_registry(), _vacancy(), _content(), "vacancy-fit-v1"
    )
    validate_context_character_limits(context, maximum_characters=None)


def test_empty_prompt_version_rejected():
    with pytest.raises(ValueError):
        build_vacancy_analysis_context(_full_registry(), _vacancy(), _content(), "  ")


def test_empty_description_rejected():
    content = VacancyContent(raw_text="   ", markdown="   ")
    with pytest.raises(ValueError):
        build_vacancy_analysis_context(_full_registry(), _vacancy(), content, "vacancy-fit-v1")
