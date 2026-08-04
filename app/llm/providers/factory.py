"""Provider factory: maps configuration to a concrete LLMProvider.

Adding a provider later means: add provider settings, add one adapter module,
add one branch here. No business service changes.
"""

from app.llm.errors import LLMConfigurationError
from app.llm.providers.base import LLMProvider
from app.llm.providers.deepseek import DEFAULT_BASE_URL, DeepSeekProvider
from app.llm.providers.openai import OpenAIProvider


def create_llm_provider(settings) -> LLMProvider:
    """Create the configured LLM provider.

    ``settings`` is duck-typed so tests can pass a lightweight object without
    importing the real configuration module.
    """
    provider_name = (getattr(settings, "LLM_PROVIDER", "") or "").strip().lower()

    if provider_name == "deepseek":
        api_key = getattr(settings, "DEEPSEEK_API_KEY", None)
        if not api_key or not str(api_key).strip():
            raise LLMConfigurationError(
                "DEEPSEEK_API_KEY is required when LLM_PROVIDER=deepseek."
            )
        return DeepSeekProvider(
            api_key=str(api_key),
            base_url=getattr(settings, "DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
            timeout_seconds=float(getattr(settings, "LLM_TIMEOUT_SECONDS", 120.0)),
            max_retries=int(getattr(settings, "LLM_MAX_RETRIES", 2)),
        )

    if provider_name == "openai":
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if not api_key or not str(api_key).strip():
            raise LLMConfigurationError(
                "OPENAI_API_KEY is required when LLM_PROVIDER=openai."
            )
        return OpenAIProvider(
            api_key=str(api_key),
            timeout_seconds=float(getattr(settings, "LLM_TIMEOUT_SECONDS", 120.0)),
            max_retries=int(getattr(settings, "LLM_MAX_RETRIES", 2)),
        )

    raise LLMConfigurationError(f"Unsupported LLM provider: {provider_name!r}")
