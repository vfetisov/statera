"""Tests for the OpenAI provider adapter at a narrow mocked SDK boundary.

The SDK ``OpenAI`` class is replaced with a fake so no network is touched. The
fake can return a prepared parsed response or raise a real SDK exception that
the adapter must map into common Statera exceptions.
"""

from types import SimpleNamespace

import httpx
import pytest

import app.llm.providers.openai as openai_mod
from app.llm.errors import (
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)
from app.llm.providers.base import LLMMessage, LLMRequest
from app.llm.schemas import Recommendation, VacancyFitAnalysis

_API = "https://api.openai.com/v1/responses"


def _http_response(status: int) -> httpx.Response:
    return httpx.Response(
        status, request=httpx.Request("POST", _API)
    )


def _request(model="gpt-5-mini", effort="medium"):
    return LLMRequest(
        messages=(
            LLMMessage(role="system", content="system instructions"),
            LLMMessage(role="user", content="user context block"),
        ),
        response_model=VacancyFitAnalysis,
        model=model,
        reasoning_effort=effort,
        metadata={"task": "vacancy_fit_analysis"},
    )


def _valid_fit():
    return VacancyFitAnalysis(
        overall_score=80,
        technical_score=70,
        leadership_score=60,
        location_score=90,
        recommendation=Recommendation.strong_match,
        summary="Strong match with clear evidence in the career brief.",
        strengths=["Direct people leadership"],
        weaknesses=[],
        risks=["Unspecified work authorization"],
    )


class _Usage:
    input_tokens = 10
    output_tokens = 5


class _Parsed:
    def __init__(self, output_parsed=None, output=None, incomplete_details=None,
                 usage=None, rid="req_123"):
        self.output_parsed = output_parsed
        self.output = output if output is not None else []
        self.incomplete_details = incomplete_details
        self.usage = usage
        self.id = rid


def _install(monkeypatch, parsed=None, error=None):
    """Install a fake SDK client and return the provider plus captured kwargs."""
    captured = {}

    class FakeResponses:
        def parse(self, **kwargs):
            captured["kwargs"] = kwargs
            if error is not None:
                raise error
            return parsed

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = FakeResponses()

    monkeypatch.setattr(openai_mod, "OpenAI", FakeClient)
    provider = openai_mod.OpenAIProvider(api_key="sk-test")
    return provider, captured


def test_generic_request_maps_to_structured_responses_call(monkeypatch):
    provider, captured = _install(
        monkeypatch, parsed=_Parsed(output_parsed=_valid_fit())
    )

    provider.generate_structured(_request())

    kwargs = captured["kwargs"]
    assert kwargs["model"] == "gpt-5-mini"
    assert kwargs["text_format"] is VacancyFitAnalysis
    assert kwargs["store"] is False
    assert kwargs["stream"] is False
    assert kwargs["reasoning"] == {"effort": "medium"}
    assert kwargs["input"] == [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "user context block"},
    ]


def test_no_reasoning_when_effort_is_none(monkeypatch):
    provider, captured = _install(
        monkeypatch, parsed=_Parsed(output_parsed=_valid_fit())
    )

    provider.generate_structured(_request(effort=None))

    assert "reasoning" not in captured["kwargs"]


def test_parsed_response_maps_to_requested_pydantic_model(monkeypatch):
    provider, _ = _install(monkeypatch, parsed=_Parsed(output_parsed=_valid_fit()))

    result = provider.generate_structured(_request())

    assert isinstance(result.value, VacancyFitAnalysis)
    assert result.value.overall_score == 80
    assert result.value.recommendation == Recommendation.strong_match


def test_usage_and_request_id_are_mapped(monkeypatch):
    parsed = _Parsed(output_parsed=_valid_fit(), usage=_Usage(), rid="req_abc")
    provider, _ = _install(monkeypatch, parsed=parsed)

    result = provider.generate_structured(_request())

    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.provider_request_id == "req_abc"
    assert result.provider == "openai"
    assert result.model == "gpt-5-mini"


def test_authentication_error_maps_to_llm_authentication_error(monkeypatch):
    error = openai_mod.AuthenticationError(
        "bad key", response=_http_response(401), body={}
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMAuthenticationError) as exc_info:
        provider.generate_structured(_request())
    message = str(exc_info.value)
    assert "sk-test" not in message
    assert "system instructions" not in message
    assert "user context block" not in message


def test_rate_limit_maps_to_llm_rate_limit_error(monkeypatch):
    error = openai_mod.RateLimitError(
        "rate limited", response=_http_response(429), body={}
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMRateLimitError):
        provider.generate_structured(_request())


def test_timeout_maps_to_llm_timeout_error(monkeypatch):
    error = openai_mod.APITimeoutError(request=httpx.Request("POST", _API))
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMTimeoutError):
        provider.generate_structured(_request())


def test_refusal_in_response_maps_to_llm_refusal_error(monkeypatch):
    parsed = _Parsed(
        output_parsed=None,
        output=[
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="refusal", text="I cannot do that")],
            )
        ],
    )
    provider, _ = _install(monkeypatch, parsed=parsed)

    with pytest.raises(LLMRefusalError):
        provider.generate_structured(_request())


def test_refusal_bad_request_maps_to_llm_refusal_error(monkeypatch):
    error = openai_mod.BadRequestError(
        "refused due to policy", response=_http_response(400), body={}
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMRefusalError):
        provider.generate_structured(_request())


def test_incomplete_output_maps_to_structured_output_error(monkeypatch):
    parsed = _Parsed(
        output_parsed=None,
        output=[],
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
    )
    provider, _ = _install(monkeypatch, parsed=parsed)

    with pytest.raises(LLMStructuredOutputError):
        provider.generate_structured(_request())


def test_missing_structured_result_maps_to_structured_output_error(monkeypatch):
    parsed = _Parsed(output_parsed=None, output=[], incomplete_details=None)
    provider, _ = _install(monkeypatch, parsed=parsed)

    with pytest.raises(LLMStructuredOutputError):
        provider.generate_structured(_request())


def test_generic_api_error_maps_to_provider_error(monkeypatch):
    error = openai_mod.APIError(
        "boom", request=httpx.Request("POST", _API), body=None
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMProviderError):
        provider.generate_structured(_request())


def test_empty_api_key_is_rejected():
    with pytest.raises(Exception):
        openai_mod.OpenAIProvider(api_key="   ")
