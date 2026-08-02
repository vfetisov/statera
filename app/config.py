"""Application configuration loaded from environment variables and .env file."""

from pydantic import Field
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
    LINKEDIN_STORAGE_STATE: str = "var/playwright/linkedin-storage-state.json"
    LINKEDIN_SEARCH_URL: str | None = None
    LINKEDIN_DEBUG_PAUSE: bool = False
    LINKEDIN_DUMP_DOM: bool = False
    LINKEDIN_DESCRIPTION_FETCH_LIMIT: int = Field(default=5, ge=1, le=20)


settings = Settings()
