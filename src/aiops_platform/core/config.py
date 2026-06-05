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
    prometheus_source_urls: str = Field(default="", alias="PROMETHEUS_SOURCE_URLS")
    prometheus_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        alias="PROMETHEUS_TIMEOUT_SECONDS",
    )
    loki_base_url: str = Field(default="http://localhost:3100", alias="LOKI_BASE_URL")
    loki_source_urls: str = Field(default="", alias="LOKI_SOURCE_URLS")
    loki_timeout_seconds: float = Field(default=10.0, gt=0, alias="LOKI_TIMEOUT_SECONDS")
    kubernetes_api_base_url: str = Field(
        default="http://localhost:8001",
        alias="KUBERNETES_API_BASE_URL",
    )
    kubernetes_bearer_token: str = Field(default="", alias="KUBERNETES_BEARER_TOKEN")
    kubernetes_namespace_allowlist: str = Field(
        default="default,kube-system",
        alias="KUBERNETES_NAMESPACE_ALLOWLIST",
    )
    kubernetes_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        alias="KUBERNETES_TIMEOUT_SECONDS",
    )
    kafka_admin_base_url: str = Field(
        default="http://localhost:8080",
        alias="KAFKA_ADMIN_BASE_URL",
    )
    kafka_timeout_seconds: float = Field(default=10.0, gt=0, alias="KAFKA_TIMEOUT_SECONDS")
    batch_api_base_url: str = Field(
        default="http://localhost:8081",
        alias="BATCH_API_BASE_URL",
    )
    batch_timeout_seconds: float = Field(default=10.0, gt=0, alias="BATCH_TIMEOUT_SECONDS")
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
        gt=0,
        alias="ELASTICSEARCH_TIMEOUT_SECONDS",
    )
    kibana_base_url: str = Field(default="http://localhost:5601", alias="KIBANA_BASE_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
