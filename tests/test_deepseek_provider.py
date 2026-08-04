"""Tests for the DeepSeek provider adapter at a narrow mocked SDK boundary.

The ``openai`` SDK client is replaced with a fake, so no network and no real
DeepSeek request ever happens. The fake can return a prepared completion or
raise a real OpenAI SDK exception that the adapter must map into common Statera
errors.
"""

import httpx
import pytest
from pydantic import BaseModel

import app.llm.providers.deepseek as deepseek_mod
from app.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)
from app.llm.providers.base import LLMMessage, LLMRequest

_ENDPOINT = "https://api.deepseek.com/chat/completions"


class _Status(BaseModel):
    status: str


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Usage:
    prompt_tokens = 11
    completion_tokens = 4


class _Completion:
    def __init__(self, content, model="deepseek-v4-flash", rid="chatcmpl_9"):
        self.id = rid
        self.model = model
        self.choices = [_Choice(content)] if content is not None else []
        self.usage = _Usage()


def _http_response(status: int, *, code=None, message=None, request_id="req_xyz"):
    body = {}
    if code is not None or message is not None:
        body["error"] = {}
        if code is not None:
            body["error"]["code"] = code
        if message is not None:
            body["error"]["message"] = message
    return httpx.Response(
        status,
        request=httpx.Request("POST", _ENDPOINT),
        headers={"x-request-id": request_id},
        json=body,
    )


def _request(model="deepseek-v4-flash", effort="medium"):
    return LLMRequest(
        messages=(
            LLMMessage(role="system", content="Return JSON with status."),
            LLMMessage(role="user", content="private context block"),
        ),
        response_model=_Status,
        model=model,
        reasoning_effort=effort,
        metadata={"task": "provider_check"},
    )


def _install(monkeypatch, completion=None, error=None, base_url="https://api.deepseek.com"):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs
            if error is not None:
                raise error
            return completion

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            captured["client"] = self
            self.chat = FakeChat()

    monkeypatch.setattr(deepseek_mod, "OpenAI", FakeClient)
    provider = deepseek_mod.DeepSeekProvider(
        api_key="sk-deepseek-test",
        base_url=base_url,
        timeout_seconds=120.0,
        max_retries=2,
    )
    return provider, captured


def test_provider_name_is_deepseek():
    assert deepseek_mod.DeepSeekProvider.name == "deepseek"


def test_default_base_url_is_accepted(monkeypatch):
    provider, captured = _install(
        monkeypatch, completion=_Completion('{"status": "ok"}'),
        base_url=deepseek_mod.DEFAULT_BASE_URL,
    )
    assert captured["client_kwargs"]["base_url"] == "https://api.deepseek.com"


def test_trailing_slash_is_normalized(monkeypatch):
    _, captured = _install(
        monkeypatch, completion=_Completion('{"status": "ok"}'),
        base_url="https://api.deepseek.com/",
    )
    assert captured["client_kwargs"]["base_url"] == "https://api.deepseek.com"


def test_non_https_base_url_is_rejected():
    with pytest.raises(LLMConfigurationError):
        deepseek_mod.DeepSeekProvider(
            api_key="sk", base_url="http://api.deepseek.com"
        )


def test_empty_api_key_fails_safely():
    with pytest.raises(LLMConfigurationError):
        deepseek_mod.DeepSeekProvider(api_key="   ")


def test_generic_messages_map_to_chat_completions(monkeypatch):
    provider, captured = _install(
        monkeypatch, completion=_Completion('{"status": "ok"}')
    )
    provider.generate_structured(_request())

    kwargs = captured["kwargs"]
    assert kwargs["model"] == "deepseek-v4-flash"
    assert kwargs["messages"] == [
        {"role": "system", "content": "Return JSON with status."},
        {"role": "user", "content": "private context block"},
    ]


def test_responses_api_is_not_called(monkeypatch):
    provider, captured = _install(
        monkeypatch, completion=_Completion('{"status": "ok"}')
    )
    result = provider.generate_structured(_request())

    assert result.value.status == "ok"
    assert not hasattr(captured["client"], "responses")


def test_json_response_format_is_requested(monkeypatch):
    provider, captured = _install(
        monkeypatch, completion=_Completion('{"status": "ok"}')
    )
    provider.generate_structured(_request())

    assert captured["kwargs"]["response_format"] == {"type": "json_object"}
    assert captured["kwargs"]["stream"] is False


def test_valid_json_is_parsed_into_requested_model(monkeypatch):
    provider, _ = _install(monkeypatch, completion=_Completion('{"status": "ok"}'))
    result = provider.generate_structured(_request())

    assert isinstance(result.value, _Status)
    assert result.value.status == "ok"


def test_malformed_json_raises(monkeypatch):
    provider, _ = _install(monkeypatch, completion=_Completion('{"status": '))
    with pytest.raises(LLMStructuredOutputError):
        provider.generate_structured(_request())


def test_empty_content_raises(monkeypatch):
    provider, _ = _install(monkeypatch, completion=_Completion(None))
    with pytest.raises(LLMStructuredOutputError):
        provider.generate_structured(_request())


def test_fenced_json_raises(monkeypatch):
    provider, _ = _install(
        monkeypatch, completion=_Completion('```json\n{"status": "ok"}\n```')
    )
    with pytest.raises(LLMStructuredOutputError):
        provider.generate_structured(_request())


@pytest.mark.parametrize(
    "content",
    [
        'Sure! Here is the result: {"status": "ok"}',
        '{"status": "ok"} and that is all',
    ],
)
def test_extra_prose_raises(monkeypatch, content):
    provider, _ = _install(monkeypatch, completion=_Completion(content))
    with pytest.raises(LLMStructuredOutputError):
        provider.generate_structured(_request())


def test_schema_invalid_json_raises(monkeypatch):
    provider, _ = _install(monkeypatch, completion=_Completion('{"wrong": 1}'))
    with pytest.raises(LLMStructuredOutputError):
        provider.generate_structured(_request())


def test_usage_fields_are_mapped(monkeypatch):
    provider, _ = _install(monkeypatch, completion=_Completion('{"status": "ok"}'))
    result = provider.generate_structured(_request())

    assert result.usage.input_tokens == 11
    assert result.usage.output_tokens == 4


def test_response_id_and_model_are_mapped(monkeypatch):
    provider, _ = _install(monkeypatch, completion=_Completion('{"status": "ok"}'))
    result = provider.generate_structured(_request())

    assert result.provider_request_id == "chatcmpl_9"
    assert result.model == "deepseek-v4-flash"
    assert result.provider == "deepseek"


def test_authentication_failure_is_mapped(monkeypatch):
    error = deepseek_mod.AuthenticationError(
        "bad key",
        response=_http_response(401, code="invalid_api_key", message="bad"),
        body={},
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMAuthenticationError) as exc_info:
        provider.generate_structured(_request())
    message = str(exc_info.value)
    assert "provider=deepseek" in message
    assert "sk-deepseek-test" not in message
    assert "private context block" not in message


def test_rate_limit_is_mapped(monkeypatch):
    error = deepseek_mod.RateLimitError(
        "limited", response=_http_response(429), body={}
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMRateLimitError):
        provider.generate_structured(_request())


def test_timeout_is_mapped(monkeypatch):
    error = deepseek_mod.APITimeoutError(
        request=httpx.Request("POST", _ENDPOINT)
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMTimeoutError):
        provider.generate_structured(_request())


def test_bad_request_exposes_safe_diagnostics(monkeypatch):
    error = deepseek_mod.BadRequestError(
        "boom",
        response=_http_response(400, code="invalid_request_error", message="bad params"),
        body={"error": {"code": "invalid_request_error", "message": "bad params"}},
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate_structured(_request())

    message = str(exc_info.value)
    assert "provider=deepseek" in message
    assert "model=deepseek-v4-flash" in message
    assert "http_status=400" in message
    assert "error_code=invalid_request_error" in message
    assert "request_id=req_xyz" in message
    assert "sk-deepseek-test" not in message


def test_api_key_is_redacted_and_prompt_never_included(monkeypatch):
    error = deepseek_mod.AuthenticationError(
        "bad key",
        response=_http_response(401, code="invalid_api_key", message="bad"),
        body={"error": {"code": "invalid_api_key", "message": "bad"}},
    )
    provider, _ = _install(monkeypatch, error=error)

    with pytest.raises(LLMAuthenticationError) as exc_info:
        provider.generate_structured(_request())

    message = str(exc_info.value)
    assert "sk-deepseek-test" not in message
    assert "Return JSON with status." not in message
    assert "private context block" not in message
