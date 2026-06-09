from functools import lru_cache
from uuid import UUID

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
    farmer_bnpl_required_documents: str = Field(
        default=(
            "identity_verification,farmer_registration,farmland_document,"
            "crop_plan,insurance_certificate"
        ),
        alias="FARMER_BNPL_REQUIRED_DOCUMENTS",
    )
    farm_advisory_default_bnpl_budget: int = Field(
        default=3_000_000,
        ge=0,
        alias="FARM_ADVISORY_DEFAULT_BNPL_BUDGET",
    )
    farm_advisory_max_area_hectare: float = Field(
        default=1000.0,
        gt=0,
        alias="FARM_ADVISORY_MAX_AREA_HECTARE",
    )
    farmer_bnpl_max_search_limit: int = Field(
        default=50,
        ge=1,
        alias="FARMER_BNPL_MAX_SEARCH_LIMIT",
    )
    farmer_bnpl_default_checkout_product_id: UUID = Field(
        default="10000000-0000-0000-0000-000000000002",
        alias="FARMER_BNPL_DEFAULT_CHECKOUT_PRODUCT_ID",
    )
    farmer_bnpl_default_checkout_quantity: int = Field(
        default=2,
        ge=1,
        alias="FARMER_BNPL_DEFAULT_CHECKOUT_QUANTITY",
    )
    admin_riskops_max_search_limit: int = Field(
        default=100,
        ge=1,
        alias="ADMIN_RISKOPS_MAX_SEARCH_LIMIT",
    )
    prediction_scaling_max_search_limit: int = Field(
        default=100,
        ge=1,
        alias="PREDICTION_SCALING_MAX_SEARCH_LIMIT",
    )
    llm_provider: str = Field(default="fake", alias="LLM_PROVIDER")
    llm_model: str = Field(default="fake-agentic-planner", alias="LLM_MODEL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_api_base_url: str = Field(default="https://api.openai.com/v1", alias="LLM_API_BASE_URL")
    llm_require_api_key: bool = Field(default=True, alias="LLM_REQUIRE_API_KEY")
    llm_max_tokens: int = Field(default=800, ge=1, le=8192, alias="LLM_MAX_TOKENS")
    llm_timeout_seconds: float = Field(default=60.0, gt=0, alias="LLM_TIMEOUT_SECONDS")
    llm_temperature: float = Field(default=0.1, ge=0, le=2, alias="LLM_TEMPERATURE")

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
    kubernetes_bearer_token_file: str = Field(
        default="",
        alias="KUBERNETES_BEARER_TOKEN_FILE",
    )
    kubernetes_ca_cert_file: str = Field(default="", alias="KUBERNETES_CA_CERT_FILE")
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
    infraops_elk_enabled: bool = Field(default=True, alias="INFRAOPS_ELK_ENABLED")
    rca_default_before_minutes: int = Field(
        default=10,
        ge=0,
        alias="RCA_DEFAULT_BEFORE_MINUTES",
    )
    rca_default_after_minutes: int = Field(
        default=5,
        ge=0,
        alias="RCA_DEFAULT_AFTER_MINUTES",
    )
    email_provider: str = Field(default="smtp", alias="EMAIL_PROVIDER")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, ge=1, le=65535, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="aiops@example.com", alias="SMTP_FROM")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    ops_report_email_recipients: str = Field(
        default="",
        alias="OPS_REPORT_EMAIL_RECIPIENTS",
    )
    rca_email_recipients: str = Field(default="", alias="RCA_EMAIL_RECIPIENTS")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
