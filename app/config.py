from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import AnyUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_token: SecretStr = Field(SecretStr("TEST_TOKEN"), alias="TELEGRAM_TOKEN")
    openai_api_key: Optional[SecretStr] = Field(None, alias="OPENAI_API_KEY")
    timezone: str = Field("Europe/Moscow", alias="TIMEZONE")
    database_url: str = Field("sqlite+aiosqlite:///./storage/bot.db", alias="DATABASE_URL")
    webhook_url: Optional[AnyUrl] = Field(None, alias="WEBHOOK_URL")
    admin_chat_id: Optional[int] = Field(None, alias="ADMIN_CHAT_ID")
    scheduler_tick_seconds: int = Field(60, alias="SCHEDULER_TICK_SECONDS")
    sleep_goal_hours_default: float = 7.5
    locale: str = "ru"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

