"""Tests for the LLM provider factory."""

from types import SimpleNamespace

import pytest

from app.llm.errors import LLMConfigurationError
from app.llm.providers.deepseek import DeepSeekProvider
from app.llm.providers.factory import create_llm_provider
from app.llm.providers.openai import OpenAIProvider


def _settings(**overrides):
    base = {
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-openai-test",
        "DEEPSEEK_API_KEY": "sk-deepseek-test",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "LLM_TIMEOUT_SECONDS": 120.0,
        "LLM_MAX_RETRIES": 2,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_openai_creates_openai_provider():
    provider = create_llm_provider(_settings())
    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"


def test_deepseek_creates_deepseek_provider():
    provider = create_llm_provider(_settings(LLM_PROVIDER="deepseek"))
    assert isinstance(provider, DeepSeekProvider)
    assert provider.name == "deepseek"


def test_unknown_provider_fails_clearly():
    with pytest.raises(LLMConfigurationError) as exc_info:
        create_llm_provider(_settings(LLM_PROVIDER="anthropic"))
    assert "Unsupported LLM provider" in str(exc_info.value)


def test_provider_name_is_normalized():
    provider = create_llm_provider(_settings(LLM_PROVIDER="  DeepSeek "))
    assert isinstance(provider, DeepSeekProvider)


def test_missing_openai_key_fails_clearly():
    with pytest.raises(LLMConfigurationError):
        create_llm_provider(_settings(OPENAI_API_KEY=None))
    with pytest.raises(LLMConfigurationError):
        create_llm_provider(_settings(OPENAI_API_KEY="   "))


def test_missing_deepseek_key_fails_clearly():
    with pytest.raises(LLMConfigurationError):
        create_llm_provider(_settings(LLM_PROVIDER="deepseek", DEEPSEEK_API_KEY=None))
    with pytest.raises(LLMConfigurationError):
        create_llm_provider(_settings(LLM_PROVIDER="deepseek", DEEPSEEK_API_KEY="   "))
