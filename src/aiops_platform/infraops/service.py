from __future__ import annotations

from fnmatch import fnmatch

from aiops_platform.core.config import Settings, settings
from aiops_platform.infraops.clients import ElasticsearchClient, PrometheusClient
from aiops_platform.infraops.schemas import (
    ElasticsearchClusterHealthResult,
    ElasticsearchIndexHealthItem,
    ElasticsearchIndexHealthResult,
    PrometheusQueryResult,
)


class InfraOpsValidationError(ValueError):
    pass


class InfraOpsService:
    def __init__(
        self,
        *,
        prometheus_client: PrometheusClient,
        elasticsearch_client: ElasticsearchClient,
        elasticsearch_index_allowlist: tuple[str, ...],
    ) -> None:
        self._prometheus_client = prometheus_client
        self._elasticsearch_client = elasticsearch_client
        self._elasticsearch_index_allowlist = elasticsearch_index_allowlist

    @classmethod
    def from_settings(cls, app_settings: Settings = settings) -> InfraOpsService:
        return cls(
            prometheus_client=PrometheusClient(
                app_settings.prometheus_base_url,
                timeout_seconds=app_settings.prometheus_timeout_seconds,
            ),
            elasticsearch_client=ElasticsearchClient(
                app_settings.elasticsearch_base_url,
                username=app_settings.elasticsearch_username,
                password=app_settings.elasticsearch_password,
                timeout_seconds=app_settings.elasticsearch_timeout_seconds,
            ),
            elasticsearch_index_allowlist=parse_allowlist(
                app_settings.elasticsearch_index_allowlist,
            ),
        )

    def query_prometheus(self, query: str, time: str | None = None) -> PrometheusQueryResult:
        response = self._prometheus_client.query(query=query, time=time)
        return PrometheusQueryResult(status=response["status"], data=response["data"])

    def get_elasticsearch_cluster_health(self) -> ElasticsearchClusterHealthResult:
        response = self._elasticsearch_client.cluster_health()
        return ElasticsearchClusterHealthResult(
            status=response["status"],
            cluster_name=response.get("cluster_name"),
            number_of_nodes=response.get("number_of_nodes"),
            active_shards=response.get("active_shards"),
            relocating_shards=response.get("relocating_shards"),
            initializing_shards=response.get("initializing_shards"),
            unassigned_shards=response.get("unassigned_shards"),
            raw=response,
        )

    def get_elasticsearch_index_health(
        self,
        index_pattern: str | None = None,
    ) -> ElasticsearchIndexHealthResult:
        resolved_index_pattern = index_pattern or self._elasticsearch_index_allowlist[0]
        validate_index_pattern(
            resolved_index_pattern,
            allowlist=self._elasticsearch_index_allowlist,
        )
        response = self._elasticsearch_client.index_health(resolved_index_pattern)
        return ElasticsearchIndexHealthResult(
            indices=[
                ElasticsearchIndexHealthItem(
                    index=item["index"],
                    health=item.get("health"),
                    status=item.get("status"),
                    docs_count=item.get("docs.count"),
                    store_size=item.get("store.size"),
                )
                for item in response
            ]
        )


def parse_allowlist(value: str) -> tuple[str, ...]:
    allowlist = tuple(item.strip() for item in value.split(",") if item.strip())
    if not allowlist:
        raise InfraOpsValidationError("Elasticsearch index allowlist must not be empty.")
    return allowlist


def validate_index_pattern(index_pattern: str, *, allowlist: tuple[str, ...]) -> None:
    if any(fnmatch(index_pattern, allowed) for allowed in allowlist):
        return
    raise InfraOpsValidationError("Elasticsearch index pattern is not allowlisted.")

