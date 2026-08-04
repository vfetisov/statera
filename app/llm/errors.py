"""Shared, provider-neutral exceptions for the LLM layer.

Messages may include a provider name, a model, a vacancy external ID, and safe
technical context. They must never include API keys, the full Career Brief,
the full vacancy description, or storage-state contents.
"""


class LLMError(Exception):
    """Base class for all Statera LLM errors."""


class LLMConfigurationError(LLMError):
    """Invalid or missing LLM configuration."""


class LLMProviderError(LLMError):
    """A provider reported an unexpected error."""


class LLMAuthenticationError(LLMProviderError):
    """Provider rejected the credentials."""


class LLMRateLimitError(LLMProviderError):
    """Provider rate limit was exceeded."""


class LLMTimeoutError(LLMProviderError):
    """Provider request timed out."""


class LLMStructuredOutputError(LLMProviderError):
    """Provider did not return a valid structured result.

    ``reason`` is a small safe category (for example ``invalid_json`` or
    ``schema_validation_failed``) used to build a corrective retry hint. It
    never contains API keys, prompts, or provider response bodies.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str = "unknown_structured_output_error",
    ) -> None:
        super().__init__(message)
        self.reason = reason


class LLMRefusalError(LLMProviderError):
    """Provider refused to produce the requested output."""


class ContextSizeExceededError(LLMError):
    """A context package exceeds the configured safety limit."""


class MissingCareerAssetError(LLMError):
    """A required career asset is not loaded or configured."""
