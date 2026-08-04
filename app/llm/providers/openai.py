"""OpenAI provider adapter (Responses API, strict structured output).

Only this module may import the OpenAI SDK. It maps the generic
``LLMRequest``/``LLMResult`` types to the Responses API with Pydantic-backed
strict structured output, and maps provider exceptions into common Statera
exceptions. The client is instantiated here, never globally at import time.
"""

from typing import Any, TypeVar

from openai import (
    APIConnectionError,
    APITimeoutError,
    APIError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel

from app.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)
from app.llm.providers.base import LLMRequest, LLMResult, LLMUsage

_T = TypeVar("_T", bound=BaseModel)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _looks_like_refusal(exc: BadRequestError) -> bool:
    message = getattr(exc, "message", "") or str(exc)
    body = getattr(exc, "body", None)
    body_text = str(body) if body is not None else ""
    return "refus" in f"{message} {body_text}".lower()


def _raise_for_refusal_or_incomplete(parsed: Any) -> None:
    """Raise LLMRefusalError / LLMStructuredOutputError from a parsed response.

    The Responses API reports refusals as message output items with a
    ``refusal`` content item; an incomplete response sets ``incomplete_details``.
    """
    for output in getattr(parsed, "output", []) or []:
        if getattr(output, "type", None) != "message":
            continue
        for content in getattr(output, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                text = getattr(content, "text", None) or getattr(
                    content, "refusal", None
                )
                if text:
                    raise LLMRefusalError(
                        "OpenAI provider refused to produce the analysis."
                    )
    if getattr(parsed, "incomplete_details", None) is not None:
        raise LLMStructuredOutputError(
            "OpenAI provider returned an incomplete structured response.",
            reason="incomplete_response",
        )


class OpenAIProvider:
    """OpenAI-backed LLM provider using the Responses API."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key or not api_key.strip():
            raise LLMConfigurationError(
                "OpenAI API key is empty. Set OPENAI_API_KEY in .env."
            )
        self._client = OpenAI(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    def generate_structured(self, request: LLMRequest[_T]) -> LLMResult[_T]:
        model = request.response_model
        input_messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]

        kwargs: dict[str, Any] = {
            "model": request.model,
            "input": input_messages,
            "text_format": model,
            "store": False,
            "stream": False,
        }
        if request.reasoning_effort:
            kwargs["reasoning"] = {"effort": request.reasoning_effort}

        try:
            parsed = self._client.responses.parse(**kwargs)
        except AuthenticationError as exc:
            raise LLMAuthenticationError(
                "OpenAI provider authentication failed (check OPENAI_API_KEY)."
            ) from exc
        except PermissionDeniedError as exc:
            raise LLMAuthenticationError(
                "OpenAI provider denied access (check account permissions)."
            ) from exc
        except RateLimitError as exc:
            raise LLMRateLimitError(
                "OpenAI provider rate limit exceeded; retry later."
            ) from exc
        except APITimeoutError as exc:
            raise LLMTimeoutError("OpenAI provider request timed out.") from exc
        except APIConnectionError as exc:
            raise LLMProviderError("OpenAI provider connection error.") from exc
        except BadRequestError as exc:
            if _looks_like_refusal(exc):
                raise LLMRefusalError(
                    "OpenAI provider refused the request."
                ) from exc
            raise LLMStructuredOutputError(
                "OpenAI provider rejected the structured-output request.",
                reason="unknown_structured_output_error",
            ) from exc
        except APIError as exc:
            raise LLMProviderError("OpenAI provider API error.") from exc

        value = getattr(parsed, "output_parsed", None)
        if value is None:
            _raise_for_refusal_or_incomplete(parsed)
            raise LLMStructuredOutputError(
                "OpenAI provider returned no structured result.",
                reason="empty_response",
            )

        if not isinstance(value, model):
            value = model.model_validate(value)

        usage = getattr(parsed, "usage", None)
        llm_usage = LLMUsage(
            input_tokens=_int_or_none(getattr(usage, "input_tokens", None)),
            output_tokens=_int_or_none(getattr(usage, "output_tokens", None)),
        )
        return LLMResult(
            value=value,
            provider=self.name,
            model=request.model,
            usage=llm_usage,
            provider_request_id=getattr(parsed, "id", None),
        )
