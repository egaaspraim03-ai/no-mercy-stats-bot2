from __future__ import annotations

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    chat_id: str = "-1004375644856"
    admin_ids: list[int] = Field(default_factory=list)

    club_slug: str = "utinoe-bratstvo"
    full_cookie: str = ""
    proxy: str = ""

    use_redis: bool = False
    redis_dsn: str = "redis://localhost:6379/0"

    tz: str = "Europe/Moscow"
    daily_hour: int = 23
    daily_minute: int = 55

    throttle_seconds: float = 0.8
    fetch_timeout: float = 25.0
    fetch_retries: int = 4
    log_dir: str = "logs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
