"""Tests for the provider-neutral structured-output retry helper.

No real LLM calls; the helper is pure and operates on an in-memory request.
"""

from app.llm.context.models import (
    TaskAssetReference,
    VacancyAnalysisContext,
    VacancyMetadata,
)
from app.llm.errors import LLMStructuredOutputError
from app.llm.prompts.vacancy_analysis import build_vacancy_analysis_request
from app.llm.providers.base import LLMMessage
from app.llm.retry import build_structured_output_retry_request
from app.llm.schemas import VacancyFitAnalysis

BRIEF_TEXT = (
    "Master career brief with a complete factual history of the candidate. "
    "It includes many paragraphs about leadership, support operations, and "
    "technical accomplishments and service delivery."
)
DESCRIPTION = (
    "Full job description for a support engineering lead role. It describes "
    "people leadership, SLA ownership, incident management, and SaaS support "
    "operations in detail and must never be truncated by the retry builder."
)
MODEL = "deepseek-v4-flash"
EFFORT = "medium"


def _context():
    return VacancyAnalysisContext(
        candidate_profile=BRIEF_TEXT,
        vacancy=VacancyMetadata(
            external_id="777",
            title="Support Engineering Lead",
            company="Acme",
            location="Remote",
            source_url="https://www.linkedin.com/jobs/view/777/",
        ),
        vacancy_description=DESCRIPTION,
        scoring_rules=None,
        prompt_version="vacancy-fit-v3",
        asset_references=(
            TaskAssetReference(
                asset_type="master_career_brief",
                content_hash="h" * 64,
                character_count=len(BRIEF_TEXT),
            ),
        ),
    )


def _original_request():
    return build_vacancy_analysis_request(_context(), MODEL, EFFORT)


def _error(reason="schema_validation_failed"):
    return LLMStructuredOutputError("provider returned invalid JSON", reason=reason)


def test_retry_preserves_model_and_response_model():
    retry = build_structured_output_retry_request(_original_request(), _error())
    assert retry.model == MODEL
    assert retry.response_model is VacancyFitAnalysis


def test_retry_preserves_reasoning_effort():
    retry = build_structured_output_retry_request(_original_request(), _error())
    assert retry.reasoning_effort == EFFORT


def test_retry_preserves_task_metadata():
    original = _original_request()
    retry = build_structured_output_retry_request(original, _error())
    assert retry.metadata == dict(original.metadata)
    assert retry.metadata["task"] == "vacancy_fit_analysis"
    assert retry.metadata["vacancy_external_id"] == "777"


def test_retry_preserves_original_messages():
    original = _original_request()
    retry = build_structured_output_retry_request(original, _error())
    assert len(retry.messages) == len(original.messages) + 1
    assert retry.messages[: len(original.messages)] == original.messages


def test_corrective_instruction_is_appended_as_user_message():
    original = _original_request()
    retry = build_structured_output_retry_request(original, _error())
    assert retry.messages[-1].role == "user"


def test_corrective_requires_exactly_one_json_object():
    retry = build_structured_output_retry_request(_original_request(), _error())
    content = retry.messages[-1].content
    assert "exactly one valid JSON object" in content


def test_corrective_forbids_markdown_fences():
    retry = build_structured_output_retry_request(_original_request(), _error())
    content = retry.messages[-1].content
    assert "Do not use Markdown fences" in content


def test_corrective_forbids_commentary():
    retry = build_structured_output_retry_request(_original_request(), _error())
    content = retry.messages[-1].content
    assert "Do not include commentary" in content


def test_corrective_includes_safe_reason():
    retry = build_structured_output_retry_request(_original_request(), _error())
    assert "reason: schema_validation_failed" in retry.messages[-1].content


def test_corrective_uses_unknown_reason_by_default():
    retry = build_structured_output_retry_request(
        _original_request(), LLMStructuredOutputError("boom")
    )
    assert "reason: unknown_structured_output_error" in retry.messages[-1].content


def test_corrective_requires_no_extra_or_missing_fields():
    content = build_structured_output_retry_request(
        _original_request(), _error()
    ).messages[-1].content
    assert "Do not omit fields" in content
    assert "Do not add extra fields" in content


def test_invalid_provider_response_is_not_copied_into_retry():
    retry = build_structured_output_retry_request(_original_request(), _error())
    combined = "\n".join(message.content for message in retry.messages)
    assert '{"overall_score": ' not in combined
    assert "traceback" not in combined


def test_api_key_is_not_present_in_retry_messages():
    retry = build_structured_output_retry_request(_original_request(), _error())
    combined = "\n".join(message.content for message in retry.messages)
    assert "sk-" not in combined
    assert "api_key" not in combined.lower()


def test_full_mcb_and_jd_remain_present_and_untruncated():
    retry = build_structured_output_retry_request(_original_request(), _error())
    user_content = retry.messages[1].content
    assert BRIEF_TEXT in user_content
    assert DESCRIPTION in user_content


def test_original_request_is_not_mutated():
    original = _original_request()
    build_structured_output_retry_request(original, _error())
    assert len(original.messages) == 2
    assert original.messages[-1].role == "user"
