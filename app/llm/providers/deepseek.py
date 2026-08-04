"""DeepSeek provider adapter.

DeepSeek exposes an OpenAI-compatible Chat Completions API. The official
``openai`` Python SDK is used as the HTTP client only: this adapter never calls
``client.responses`` and never involves OpenAI billing or API keys. Structured
JSON output is validated locally with the existing Pydantic response model.
"""

import json
from typing import Any, TypeVar
from urllib.parse import urlparse

from openai import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.llm.errors import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMStructuredOutputError,
    LLMTimeoutError,
)
from app.llm.providers.base import LLMRequest, LLMResult, LLMUsage
from app.llm.providers.diagnostics import (
    as_optional_int,
    build_safe_provider_message,
    extract_safe_error_fields,
)

_T = TypeVar("_T", bound=BaseModel)

DEFAULT_BASE_URL = "https://api.deepseek.com"
MAX_OUTPUT_TOKENS = 4000


def build_deepseek_extra_body(reasoning_effort: str | None) -> dict[str, object]:
    """Map generic reasoning effort to DeepSeek Chat Completions extra body.

    The DeepSeek OpenAI-compatible endpoint does not document an OpenAI-style
    ``reasoning={"effort": ...}`` parameter, so this first adapter does not
    invent one. Every effort value (including ``medium``) uses the model's
    default mode. Add a documented mapping here once DeepSeek documents a
    stable thinking-mode request parameter.
    """
    return {}


def parse_deepseek_structured_response(
    content: str | None,
    response_model: type[_T],
) -> _T:
    """Parse and locally validate a DeepSeek JSON-output payload.

    Rejects empty content, Markdown fences, non-object JSON, and any trailing
    text. JSON is never scraped out of arbitrary prose.
    """
    if content is None or not content.strip():
        raise LLMStructuredOutputError(
            "DeepSeek provider returned empty content.",
            reason="empty_response",
        )
    stripped = content.strip()
    if "```" in stripped:
        raise LLMStructuredOutputError(
            "DeepSeek provider returned JSON wrapped in Markdown fences.",
            reason="fenced_json",
        )
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMStructuredOutputError(
            "DeepSeek provider returned malformed JSON.",
            reason="invalid_json",
        ) from exc
    if not isinstance(parsed, dict):
        raise LLMStructuredOutputError(
            "DeepSeek provider returned JSON that is not a single object.",
            reason="non_object_json",
        )
    try:
        return response_model.model_validate(parsed)
    except ValidationError as exc:
        raise LLMStructuredOutputError(
            "DeepSeek provider returned JSON that failed local schema validation.",
            reason="schema_validation_failed",
        ) from exc


class DeepSeekProvider:
    """DeepSeek-backed LLM provider using OpenAI-compatible Chat Completions."""

    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key or not api_key.strip():
            raise LLMConfigurationError(
                "DeepSeek API key is empty. Set DEEPSEEK_API_KEY in .env."
            )
        normalized = str(base_url).strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc:
            raise LLMConfigurationError("DEEPSEEK_BASE_URL must be an HTTPS URL.")
        self._base_url = normalized
        self._client = OpenAI(
            api_key=api_key,
            base_url=normalized,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    def _safe_message(self, prefix: str, exc: BaseException, model: str) -> str:
        return build_safe_provider_message(
            provider=self.name,
            model=model,
            fallback=prefix,
            **extract_safe_error_fields(exc),
        )

    def generate_structured(self, request: LLMRequest[_T]) -> LLMResult[_T]:
        model = request.response_model
        chat_messages = [
            {"role": message.role, "content": message.content}
            for message in request.messages
        ]

        try:
            completion = self._client.chat.completions.create(
                model=request.model,
                messages=chat_messages,
                response_format={"type": "json_object"},
                max_tokens=MAX_OUTPUT_TOKENS,
                stream=False,
                **build_deepseek_extra_body(request.reasoning_effort),
            )
        except AuthenticationError as exc:
            raise LLMAuthenticationError(
                self._safe_message(
                    "DeepSeek provider authentication failed.", exc, request.model
                )
            ) from exc
        except PermissionDeniedError as exc:
            raise LLMAuthenticationError(
                self._safe_message("DeepSeek provider denied access.", exc, request.model)
            ) from exc
        except RateLimitError as exc:
            raise LLMRateLimitError(
                self._safe_message(
                    "DeepSeek provider rate limit exceeded.", exc, request.model
                )
            ) from exc
        except APITimeoutError as exc:
            raise LLMTimeoutError(
                self._safe_message(
                    "DeepSeek provider request timed out.", exc, request.model
                )
            ) from exc
        except APIConnectionError as exc:
            raise LLMProviderError(
                self._safe_message(
                    "DeepSeek provider connection error.", exc, request.model
                )
            ) from exc
        except BadRequestError as exc:
            raise LLMProviderError(
                self._safe_message(
                    "DeepSeek provider rejected the request.", exc, request.model
                )
            ) from exc
        except NotFoundError as exc:
            raise LLMProviderError(
                self._safe_message(
                    "DeepSeek provider resource not found.", exc, request.model
                )
            ) from exc
        except APIStatusError as exc:
            raise LLMProviderError(
                self._safe_message("DeepSeek provider API error.", exc, request.model)
            ) from exc

        choices = getattr(completion, "choices", None) or []
        content = choices[0].message.content if choices else None
        value = parse_deepseek_structured_response(content, model)

        usage = getattr(completion, "usage", None)
        llm_usage = LLMUsage(
            input_tokens=as_optional_int(getattr(usage, "prompt_tokens", None)),
            output_tokens=as_optional_int(getattr(usage, "completion_tokens", None)),
        )
        return LLMResult(
            value=value,
            provider=self.name,
            model=getattr(completion, "model", None) or request.model,
            usage=llm_usage,
            provider_request_id=getattr(completion, "id", None),
        )
