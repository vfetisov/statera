"""Tests for the provider-neutral vacancy-analysis prompt builder."""

from pathlib import Path

from app.career.assets import CareerAsset, CareerAssetType
from app.career.registry import CareerAssetRegistry
from app.db.models.vacancy import Vacancy
from app.db.models.vacancy_content import VacancyContent
from app.llm.context.vacancy_analysis import build_vacancy_analysis_context
from app.llm.prompts.vacancy_analysis import build_vacancy_analysis_request

BRIEF = CareerAssetType.MASTER_CAREER_BRIEF
SCORING = CareerAssetType.SCORING_RULES
RESUME = CareerAssetType.MASTER_RESUME

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
    "Resume content that must never be injected into the fit-analysis prompt."
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


def _registry(include_scoring=True, include_resume=True):
    assets = {BRIEF: _asset(BRIEF, BRIEF_TEXT)}
    if include_scoring:
        assets[SCORING] = _asset(SCORING, SCORING_TEXT, "md")
    if include_resume:
        assets[RESUME] = _asset(RESUME, RESUME_TEXT)
    return CareerAssetRegistry(assets=assets)


def _vacancy():
    return Vacancy(
        external_id="777",
        title="Support Engineering Lead",
        url="https://www.linkedin.com/jobs/view/777/",
        location="Remote",
    )


def _content():
    return VacancyContent(raw_text=DESCRIPTION, markdown=DESCRIPTION)


def _request(include_scoring=True):
    context = build_vacancy_analysis_context(
        _registry(include_scoring=include_scoring),
        _vacancy(),
        _content(),
        "vacancy-fit-v1",
    )
    return build_vacancy_analysis_request(context, "gpt-5-mini", "medium")


def test_stable_delimiters_are_present():
    request = _request()
    user = request.messages[1].content

    assert "<MASTER_CAREER_BRIEF>" in user
    assert "</MASTER_CAREER_BRIEF>" in user
    assert "<SCORING_RULES>" in user
    assert "</SCORING_RULES>" in user
    assert "<VACANCY_METADATA>" in user
    assert "</VACANCY_METADATA>" in user
    assert "<VACANCY_DESCRIPTION>" in user
    assert "</VACANCY_DESCRIPTION>" in user


def test_no_scoring_delimiter_when_scoring_absent():
    request = _request(include_scoring=False)
    user = request.messages[1].content

    assert "<SCORING_RULES>" not in user


def test_invention_is_explicitly_forbidden():
    system = _request().messages[0].content

    assert "Do not invent" in system
    assert "not invent candidate experience" in system


def test_location_and_authorization_risks_are_requested():
    system = _request().messages[0].content

    assert "work authorization" in system
    assert "residency" in system
    assert "timezone" in system


def test_prompt_does_not_request_resume_or_cover_letter():
    system = _request().messages[0].content

    assert "Do not create a resume" in system
    assert "Do not create a cover letter" in system


def test_prompt_contains_only_context_assets():
    request = _request()
    user = request.messages[1].content

    assert BRIEF_TEXT in user
    assert SCORING_TEXT in user
    assert RESUME_TEXT not in user


def test_full_master_career_brief_not_shortened():
    user = _request().messages[1].content
    assert BRIEF_TEXT in user


def test_full_vacancy_description_not_shortened():
    user = _request().messages[1].content
    assert DESCRIPTION in user


def test_exactly_two_messages_system_and_user():
    request = _request()

    assert len(request.messages) == 2
    assert request.messages[0].role == "system"
    assert request.messages[1].role == "user"


def test_request_response_model_and_metadata():
    request = _request()

    assert request.response_model.__name__ == "VacancyFitAnalysis"
    assert request.model == "gpt-5-mini"
    assert request.reasoning_effort == "medium"
    assert request.metadata["task"] == "vacancy_fit_analysis"
    assert request.metadata["prompt_version"] == "vacancy-fit-v1"
    assert request.metadata["vacancy_external_id"] == "777"
    assert request.metadata["asset_master_career_brief"] == "master_career_brief-hash"
    assert request.metadata["asset_scoring_rules"] == "scoring_rules-hash"


def test_system_message_explicitly_requests_json():
    system = _request().messages[0].content

    assert "JSON" in system
    assert "exactly one JSON object" in system


def test_system_message_contains_expected_field_names():
    system = _request().messages[0].content

    for field in (
        "overall_score",
        "technical_score",
        "leadership_score",
        "location_score",
        "recommendation",
        "summary",
        "strengths",
        "weaknesses",
        "risks",
    ):
        assert field in system


def test_system_message_contains_recommendation_values():
    system = _request().messages[0].content

    for value in ("strong_match", "consider", "weak_match", "reject"):
        assert value in system


def test_system_message_forbids_markdown_fences():
    system = _request().messages[0].content

    assert "Markdown fences" in system


def test_system_message_forbids_commentary_outside_json():
    system = _request().messages[0].content

    assert "commentary" in system
    assert "before or after" in system


def test_anti_invention_rules_remain_present_after_json_contract():
    system = _request().messages[0].content

    assert "Do not invent candidate experience" in system
    assert "Use only facts supported by the Master Career Brief" in system


def test_overall_score_defined_as_professional_fit_excluding_geography():
    system = _request().messages[0].content

    assert "Geography must never change overall_score." in system
    assert "overall_score means professional role fit before geographic eligibility" in system


def test_technical_score_excludes_geography():
    system = _request().messages[0].content

    assert "Geography must never change technical_score." in system


def test_leadership_score_excludes_geography():
    system = _request().messages[0].content

    assert "Geography must never change leadership_score." in system


def test_location_score_contains_eligibility_factors():
    system = _request().messages[0].content

    assert "residency" in system
    assert "work authorization" in system
    assert "hybrid" in system


def test_recommendation_combines_professional_fit_and_eligibility():
    system = _request().messages[0].content

    assert "may consider both professional fit and eligibility" in system
    assert "must not be derived mechanically from overall_score alone" in system


def test_missing_authorization_is_not_automatic_blocker():
    system = _request().messages[0].content

    assert "Missing work-authorization information is not proof of ineligibility" in system


def test_country_labelled_remote_is_likely_restriction_unless_explicit():
    system = _request().messages[0].content

    assert "LIKELY_RESTRICTION" in system
    assert "does not explicitly say whether international employment" in system


def test_confirmed_blocker_definition_present():
    system = _request().messages[0].content

    assert "CONFIRMED_BLOCKER" in system
    assert "existing work authorization" in system
    assert "mandatory hybrid or onsite attendance" in system


def test_unresolved_eligibility_definition_present():
    system = _request().messages[0].content

    assert "UNRESOLVED" in system
    assert "does not provide enough information to determine eligibility" in system


def test_direct_vs_transferable_experience_distinction_present():
    system = _request().messages[0].content

    assert "DIRECT EVIDENCE" in system
    assert "STRONG TRANSFERABLE EXPERIENCE" in system
    assert "PARTIAL EXPOSURE" in system
    assert "NO VERIFIED EVIDENCE" in system


def test_ic_vs_management_mismatch_instructions_present():
    system = _request().messages[0].content

    assert "INDIVIDUAL CONTRIBUTOR VERSUS MANAGEMENT FIT" in system
    assert "overqualification" in system
    assert "Do not reduce technical_score merely because a role is an IC role" in system


def test_score_calibration_ranges_present():
    system = _request().messages[0].content

    for band in ("90-100", "80-89", "70-79", "55-69", "40-54", "0-39",
                 "75-89", "60-74", "40-59", "10-39", "0-9"):
        assert band in system


def test_summary_separation_required():
    system = _request().messages[0].content

    assert "three separate parts" in system
    assert "Professional fit" in system
    assert "Main gaps" in system
    assert "Eligibility" in system


def test_identical_jd_consistency_rule_present():
    system = _request().messages[0].content

    assert "DUPLICATE-JD CONSISTENCY" in system
    assert "no more than 3 points" in system


def test_reject_forbidden_for_unresolved_eligibility_alone():
    system = _request().messages[0].content

    assert "Do not use reject merely because eligibility is unresolved" in system


def test_full_mcb_and_jd_remain_untruncated():
    request = _request()
    user = request.messages[1].content

    assert BRIEF_TEXT in user
    assert DESCRIPTION in user
