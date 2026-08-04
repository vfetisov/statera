"""Tests for the provider-neutral LLM provider interface boundaries.

Verifies that business logic depends only on the common protocol and that no
business module imports a provider SDK.
"""

import inspect
from pathlib import Path

from app.career.assets import CareerAsset, CareerAssetType
from app.career.registry import CareerAssetRegistry
from app.llm.context.models import (
    TaskAssetReference,
    VacancyAnalysisContext,
    VacancyMetadata,
)
from app.llm.providers.base import LLMMessage, LLMRequest, LLMResult, LLMUsage
from app.llm.prompts.vacancy_analysis import build_vacancy_analysis_request
from app.llm.schemas import Recommendation, VacancyFitAnalysis
from app.services.vacancy_analysis import qualified_model_name

BUSINESS_MODULES = [
    "app.services.vacancy_analysis",
    "app.llm.context.vacancy_analysis",
    "app.llm.prompts.vacancy_analysis",
    "app.llm.schemas",
    "app.career.registry",
    "app.career.loaders",
]


def test_no_business_module_imports_openai():
    import app.career.loaders  # noqa: F401
    import app.career.registry  # noqa: F401
    import app.llm.context.vacancy_analysis  # noqa: F401
    import app.llm.prompts.vacancy_analysis  # noqa: F401
    import app.llm.schemas  # noqa: F401
    import app.services.vacancy_analysis  # noqa: F401

    for module_name in BUSINESS_MODULES:
        module = __import__(module_name, fromlist=["*"])
        source = inspect.getsource(module)
        assert "from openai" not in source, f"{module_name} imports openai"
        assert "import openai" not in source, f"{module_name} imports openai"
        assert "from anthropic" not in source, f"{module_name} imports anthropic"
        assert "import anthropic" not in source, f"{module_name} imports anthropic"


def _context() -> VacancyAnalysisContext:
    return VacancyAnalysisContext(
        candidate_profile="profile" * 40,
        vacancy=VacancyMetadata(
            external_id="12345",
            title="Support Engineering Lead",
            company="Acme",
            location="Remote",
            source_url="https://www.linkedin.com/jobs/view/12345/",
        ),
        vacancy_description="description" * 40,
        scoring_rules=None,
        prompt_version="vacancy-fit-v1",
        asset_references=(
            TaskAssetReference(
                asset_type="master_career_brief",
                content_hash="a" * 64,
                character_count=160,
            ),
        ),
    )


def test_request_metadata_is_provider_neutral():
    request = build_vacancy_analysis_request(_context(), "gpt-5-mini", "medium")

    assert request.metadata["task"] == "vacancy_fit_analysis"
    assert request.metadata["prompt_version"] == "vacancy-fit-v1"
    assert request.metadata["vacancy_external_id"] == "12345"
    assert request.metadata["asset_master_career_brief"] == "a" * 64
    assert "api_key" not in request.metadata
    assert all(
        message.role in ("system", "user") for message in request.messages
    )


def test_qualified_model_name_is_deterministic():
    assert qualified_model_name("openai", "gpt-5-mini") == "openai:gpt-5-mini"
    assert qualified_model_name("anthropic", "future-model") == "anthropic:future-model"
    assert qualified_model_name("google", "future-model") == "google:future-model"
    assert qualified_model_name("ollama", "future-model") == "ollama:future-model"


def test_fake_provider_is_accepted_by_business_module():
    """A provider implementing the protocol works with the LLMRequest type."""
    import app.llm.providers.base as base

    assert "LLMProvider" in dir(base)


class _FakeProvider:
    name = "fake"

    def generate_structured(self, request):
        return LLMResult(
            value=VacancyFitAnalysis(
                overall_score=80,
                technical_score=70,
                leadership_score=60,
                location_score=90,
                recommendation=Recommendation.consider,
                summary="Considerable fit with clear evidence in the brief.",
                strengths=["Leadership"],
                weaknesses=[],
                risks=[],
            ),
            provider=self.name,
            model=request.model,
            usage=LLMUsage(input_tokens=10, output_tokens=5),
            provider_request_id="fake-1",
        )


def test_fake_provider_satisfies_protocol():
    from app.llm.providers.base import LLMProvider

    provider = _FakeProvider()
    assert isinstance(provider, LLMProvider)
    request = build_vacancy_analysis_request(_context(), "gpt-5-mini", None)
    result = provider.generate_structured(request)
    assert isinstance(result.value, VacancyFitAnalysis)
    assert result.provider == "fake"


def test_registry_and_assets_are_provider_neutral():
    asset = CareerAsset(
        asset_type=CareerAssetType.MASTER_CAREER_BRIEF,
        source_path=Path("/x/brief.docx"),
        source_format="docx",
        text="brief" * 30,
        content_hash="b" * 64,
        character_count=150,
    )
    registry = CareerAssetRegistry(assets={CareerAssetType.MASTER_CAREER_BRIEF: asset})
    assert registry.has(CareerAssetType.MASTER_CAREER_BRIEF)
    assert isinstance(LLMMessage(role="system", content="x"), LLMMessage)
