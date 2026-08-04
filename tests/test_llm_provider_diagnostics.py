"""Tests for the shared provider-error sanitizer (safe diagnostics).

Verifies that provider exception messages contain only allowlisted scalar
fields and never leak keys, prompts, or raw response bodies.
"""

import httpx

from app.llm.providers.diagnostics import (
    as_optional_int,
    build_safe_provider_message,
    extract_safe_error_fields,
)
from app.llm.providers.openai import BadRequestError

_ENDPOINT = "https://api.deepseek.com/chat/completions"


def _http_response(status: int):
    return httpx.Response(
        status,
        request=httpx.Request("POST", _ENDPOINT),
        headers={"x-request-id": "req_123"},
    )


def test_build_message_includes_allowlisted_fields():
    message = build_safe_provider_message(
        provider="deepseek",
        model="deepseek-v4-flash",
        status=400,
        code="invalid_request_error",
        request_id="req_123",
        detail="bad params",
        fallback="DeepSeek provider rejected the request.",
    )

    assert "provider=deepseek" in message
    assert "model=deepseek-v4-flash" in message
    assert "http_status=400" in message
    assert "error_code=invalid_request_error" in message
    assert "request_id=req_123" in message
    assert "detail=bad params" in message


def test_extract_safe_fields_from_api_error():
    error = BadRequestError(
        "boom",
        response=_http_response(400),
        body={"error": {"code": "invalid_request_error", "message": "bad params"}},
    )

    fields = extract_safe_error_fields(error)

    assert fields["status"] == 400
    assert fields["code"] == "invalid_request_error"
    assert fields["detail"] == "bad params"
    assert fields["request_id"] == "req_123"
    assert set(fields) <= {"status", "code", "detail", "request_id"}


def test_detail_is_truncated():
    message = build_safe_provider_message(
        provider="deepseek",
        detail="x" * 500,
        fallback="fallback",
    )

    assert len(message) < 300


def test_as_optional_int_behavior():
    assert as_optional_int(None) is None
    assert as_optional_int(5) == 5
    assert as_optional_int("7") == 7
    assert as_optional_int("nope") is None


def test_message_never_contains_raw_body_or_key():
    error = BadRequestError(
        "boom",
        response=_http_response(400),
        body={
            "error": {"code": "invalid_request_error", "message": "ok"},
            "secret": "sk-topsecret",
        },
    )
    fields = extract_safe_error_fields(error)
    message = build_safe_provider_message(
        provider="deepseek", fallback="rejected", **fields
    )

    assert "sk-topsecret" not in str(fields)
    assert "sk-topsecret" not in message
    assert "secret" not in message
