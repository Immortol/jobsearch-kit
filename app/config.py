"""Application settings, read from environment variables (Railway variables in production)."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "prod"  # "prod" or "dev"; "dev" prints emails to the console
    app_base_url: str = "http://localhost:8000"
    database_url: str = "postgresql+psycopg://jsk:jsk@localhost:5432/jsk_dev"

    # Fernet key(s), comma-separated. The first one encrypts; all of them decrypt (rotation).
    app_encryption_key: str = ""

    owner_email: str = ""

    resend_api_key: str = ""
    email_from: str = "Jobsearch Kit <login@mail.almoti.com>"

    ui_locale: str = "ru"

    login_token_ttl_minutes: int = 15
    login_links_per_hour: int = 5
    session_days: int = 30

    anthropic_api_url: str = "https://api.anthropic.com"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Railway provides postgres:// or postgresql:// URLs; SQLAlchemy needs the driver name.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("owner_email")
    @classmethod
    def _normalize_owner(cls, v: str) -> str:
        return v.strip().lower()

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @property
    def secure_cookies(self) -> bool:
        return self.app_base_url.startswith("https://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
