from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="",
        extra="ignore",
        populate_by_name=True,
    )

    app_encryption_key: str = Field(
        default="",
        validation_alias=AliasChoices("PROFITS_CHECK_ENCRYPTION_KEY", "APP_ENCRYPTION_KEY"),
    )
    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias=AliasChoices("PROFITS_CHECK_DATABASE_URL", "DATABASE_URL"),
    )
    scheduler_enabled: bool = True
    snapshot_schedule_times: str = "08:00"
    scheduler_legacy_interval_minutes: int = 60
    bootstrap_password: str = Field(
        default="",
        validation_alias=AliasChoices("PROFITS_CHECK_BOOTSTRAP_PASSWORD", "APP_BOOTSTRAP_PASSWORD"),
    )
    cookie_secure: bool = Field(
        default=False,
        validation_alias=AliasChoices("PROFITS_CHECK_COOKIE_SECURE", "COOKIE_SECURE"),
    )
    session_ttl_days: int = Field(
        default=30,
        validation_alias=AliasChoices("PROFITS_CHECK_SESSION_TTL_DAYS", "SESSION_TTL_DAYS"),
    )
    allow_custom_provider_urls: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "PROFITS_CHECK_ALLOW_CUSTOM_PROVIDER_URLS",
            "ALLOW_CUSTOM_PROVIDER_URLS",
        ),
    )
    okx_dex_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OKX_DEX_API_KEY", "PROFITS_CHECK_OKX_DEX_API_KEY"),
    )
    okx_dex_api_secret: str = Field(
        default="",
        validation_alias=AliasChoices("OKX_DEX_API_SECRET", "PROFITS_CHECK_OKX_DEX_API_SECRET"),
    )
    okx_dex_api_passphrase: str = Field(
        default="",
        validation_alias=AliasChoices(
            "OKX_DEX_API_PASSPHRASE", "PROFITS_CHECK_OKX_DEX_API_PASSPHRASE"
        ),
    )


def get_settings() -> AppSettings:
    return AppSettings()


def get_database_url(settings: AppSettings) -> str:
    return settings.database_url
