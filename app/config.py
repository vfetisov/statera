"""Application configuration loaded from environment variables and .env file."""

from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed access to application settings.

    Values are read from the environment and from a local ``.env`` file
    (if present). ``DATABASE_URL`` is required and has no default.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Statera"
    APP_ENV: str = "development"
    DATABASE_URL: str

    # LinkedIn
    PLAYWRIGHT_HEADLESS: bool = False
    LINKEDIN_STORAGE_STATE: str = "var/playwright/linkedin-storage-state.json"
    LINKEDIN_SEARCH_URL: str | None = None
    LINKEDIN_DEBUG_PAUSE: bool = False
    LINKEDIN_DUMP_DOM: bool = False
    LINKEDIN_DESCRIPTION_FETCH_LIMIT: int = Field(default=5, ge=1, le=20)

    # LLM (provider-neutral)
    LLM_PROVIDER: str = "deepseek"
    LLM_MODEL: str = "deepseek-v4-flash"
    LLM_REASONING_EFFORT: str | None = "medium"
    LLM_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0)
    LLM_MAX_RETRIES: int = Field(default=2, ge=0, le=5)
    LLM_MAX_CONTEXT_CHARACTERS: int | None = None

    VACANCY_ANALYSIS_BATCH_LIMIT: int = Field(default=5, ge=1, le=20)
    VACANCY_ANALYSIS_PROMPT_VERSION: str = "vacancy-fit-v3"

    # Career assets (private documents, never committed)
    MASTER_CAREER_BRIEF_PATH: str | None = None
    MASTER_RESUME_PATH: str | None = None
    RESUME_TEMPLATE_PATH: str | None = None
    APPLICATION_RULES_PATH: str | None = None
    SCORING_RULES_PATH: str | None = None

    # DeepSeek adapter credentials (only required when LLM_PROVIDER=deepseek)
    DEEPSEEK_API_KEY: str | None = None
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"

    # OpenAI adapter credentials (only required when LLM_PROVIDER=openai)
    OPENAI_API_KEY: str | None = None

    @field_validator("LLM_PROVIDER", mode="before")
    @classmethod
    def _normalize_provider(cls, value):
        if value is None:
            return value
        return str(value).strip().lower()

    @field_validator("LLM_MODEL", mode="before")
    @classmethod
    def _reject_empty_model(cls, value):
        if value is None:
            return value
        text = str(value).strip()
        if not text:
            raise ValueError("LLM_MODEL must not be empty.")
        return text

    @field_validator("DEEPSEEK_BASE_URL", mode="before")
    @classmethod
    def _validate_deepseek_base_url(cls, value):
        raw = value if value is not None else "https://api.deepseek.com"
        normalized = str(raw).strip().rstrip("/")
        if not normalized:
            normalized = "https://api.deepseek.com"
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("DEEPSEEK_BASE_URL must be an HTTPS URL.")
        return normalized

    @field_validator("LLM_MAX_CONTEXT_CHARACTERS", mode="before")
    @classmethod
    def _empty_context_limit_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
