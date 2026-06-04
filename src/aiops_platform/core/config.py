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
        default="postgresql+psycopg://kkpp:kkpp@localhost:5432/kkpp",
        alias="DATABASE_URL",
    )

    prometheus_base_url: str = Field(default="http://localhost:9090", alias="PROMETHEUS_BASE_URL")
    prometheus_timeout_seconds: float = Field(default=10.0, alias="PROMETHEUS_TIMEOUT_SECONDS")
    loki_base_url: str = Field(default="http://localhost:3100", alias="LOKI_BASE_URL")
    elasticsearch_base_url: str = Field(
        default="http://localhost:9200",
        alias="ELASTICSEARCH_BASE_URL",
    )
    elasticsearch_username: str = Field(default="", alias="ELASTICSEARCH_USERNAME")
    elasticsearch_password: str = Field(default="", alias="ELASTICSEARCH_PASSWORD")
    elasticsearch_index_allowlist: str = Field(
        default="logs-*,filebeat-*,metricbeat-*",
        alias="ELASTICSEARCH_INDEX_ALLOWLIST",
    )
    elasticsearch_timeout_seconds: float = Field(
        default=10.0,
        alias="ELASTICSEARCH_TIMEOUT_SECONDS",
    )
    kibana_base_url: str = Field(default="http://localhost:5601", alias="KIBANA_BASE_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
