from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    app_name: str = Field(default="aiops-platform", alias="APP_NAME")
    app_version: str = Field(default="0.1.0", alias="APP_VERSION")
    app_timezone: str = Field(default="Asia/Seoul", alias="APP_TIMEZONE")

    database_url: str = Field(
        default="postgresql+psycopg://aiops:aiops@localhost:5432/aiops",
        alias="DATABASE_URL",
    )

    prometheus_base_url: str = Field(default="http://localhost:9090", alias="PROMETHEUS_BASE_URL")
    loki_base_url: str = Field(default="http://localhost:3100", alias="LOKI_BASE_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
