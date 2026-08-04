"""Provider-neutral request/result types and the LLMProvider protocol.

Business services depend only on this module (plus context and prompts), never
on a concrete provider SDK.
"""

from dataclasses import dataclass, field
from typing import Generic, Literal, Mapping, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class LLMMessage:
    """One logical message. Provider-neutral."""

    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True)
class LLMRequest(Generic[T]):
    """A generic request for a structured LLM result.

    No provider-specific parameters are allowed here; providers map these
    fields to their own API.
    """

    messages: tuple[LLMMessage, ...]
    response_model: type[T]
    model: str
    reasoning_effort: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMUsage:
    """Token usage reported by a provider, when available."""

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    """A validated structured result from a provider."""

    value: T
    provider: str
    model: str
    usage: LLMUsage
    provider_request_id: str | None = None


@runtime_checkable
class LLMProvider(Protocol[T]):
    """Common interface every provider adapter must implement."""

    @property
    def name(self) -> str:
        """Provider name, for example 'openai'."""
        ...

    def generate_structured(self, request: LLMRequest[T]) -> LLMResult[T]:
        """Return a validated structured result for ``request``."""
        ...
