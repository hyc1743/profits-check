from __future__ import annotations

import os

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    app_encryption_key: str = Field(
        default="MDEyMzQ1Njc4OUFCQ0RFRjAxMjM0NTY3ODlBQkNERUY=",
        validation_alias=AliasChoices("PROFITS_CHECK_ENCRYPTION_KEY", "APP_ENCRYPTION_KEY"),
    )
    database_url: str = Field(
        default="sqlite:///./data/app.db",
        validation_alias=AliasChoices("PROFITS_CHECK_DATABASE_URL", "DATABASE_URL"),
    )
    scheduler_enabled: bool = True
    snapshot_schedule_times: str = "08:00"
    scheduler_legacy_interval_minutes: int = 60
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
        validation_alias=AliasChoices("OKX_DEX_API_PASSPHRASE", "PROFITS_CHECK_OKX_DEX_API_PASSPHRASE"),
    )


def get_settings() -> AppSettings:
    return AppSettings()


def get_database_url(settings: AppSettings) -> str:
    return os.getenv("PROFITS_CHECK_DATABASE_URL", os.getenv("DATABASE_URL", settings.database_url))
