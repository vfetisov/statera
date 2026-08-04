"""Safe diagnostics helpers shared by provider adapters.

These helpers build exception messages from allowlisted scalar fields only.
Never pass an API key, Authorization header, full prompt, career asset,
vacancy description, or raw response body into them.
"""

from typing import Any


def as_optional_int(value: Any) -> int | None:
    """Coerce to int or None, tolerating None and non-numeric values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truncate(text: str, limit: int = 200) -> str:
    """Collapse whitespace and cap length for a short safe detail message."""
    compact = " ".join(str(text).split())
    return compact[:limit]


def extract_safe_error_fields(exc: Any) -> dict[str, Any]:
    """Extract only allowlisted scalar fields from an OpenAI SDK exception.

    Returns ``status``, ``code``, ``detail``, and ``request_id`` when they are
    safely available. The raw response body is never returned.
    """
    fields: dict[str, Any] = {}

    status = getattr(exc, "status_code", None)
    if status is not None:
        fields["status"] = as_optional_int(status)

    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if code is not None:
                fields["code"] = str(code)
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                fields["detail"] = _truncate(message)
        elif isinstance(error, str) and error.strip():
            fields["detail"] = _truncate(error)

    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        request_id = headers.get("x-request-id")
        if request_id:
            fields["request_id"] = str(request_id)

    return fields


def build_safe_provider_message(
    *,
    provider: str,
    model: str | None = None,
    status: int | None = None,
    code: str | None = None,
    request_id: str | None = None,
    detail: str | None = None,
    fallback: str,
) -> str:
    """Build a short, safe exception message from allowlisted fields only."""
    parts = [fallback]
    if provider:
        parts.append(f"provider={provider}")
    if model:
        parts.append(f"model={model}")
    if status is not None:
        parts.append(f"http_status={status}")
    if code:
        parts.append(f"error_code={code}")
    if request_id:
        parts.append(f"request_id={request_id}")
    if detail:
        parts.append(f"detail={_truncate(detail)}")
    return "; ".join(parts)
