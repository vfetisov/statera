"""Application configuration loaded from environment variables and .env file."""

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


settings = Settings()
