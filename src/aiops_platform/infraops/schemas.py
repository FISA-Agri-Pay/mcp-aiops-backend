from typing import Any

from pydantic import BaseModel, Field


class PrometheusQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    time: str | None = None


class PrometheusQueryResult(BaseModel):
    status: str
    data: dict[str, Any]


class LokiQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    start: str | None = None
    end: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class LokiQueryResult(BaseModel):
    status: str
    data: dict[str, Any]


class KubernetesResourceResult(BaseModel):
    namespace: str
    items: list[dict[str, Any]]
    raw: dict[str, Any]


class KafkaConsumerLagResult(BaseModel):
    consumer_group: str
    topic: str | None = None
    response: dict[str, Any]


class BatchRunStatusResult(BaseModel):
    job_name: str | None = None
    response: dict[str, Any]


class ElasticsearchClusterHealthResult(BaseModel):
    status: str
    cluster_name: str | None = None
    number_of_nodes: int | None = None
    active_shards: int | None = None
    relocating_shards: int | None = None
    initializing_shards: int | None = None
    unassigned_shards: int | None = None
    raw: dict[str, Any]


class ElasticsearchIndexHealthRequest(BaseModel):
    index_pattern: str | None = None


class ElasticsearchIndexHealthItem(BaseModel):
    index: str
    health: str | None = None
    status: str | None = None
    docs_count: str | None = None
    store_size: str | None = None


class ElasticsearchIndexHealthResult(BaseModel):
    indices: list[ElasticsearchIndexHealthItem]


class ElasticsearchQueryRequest(BaseModel):
    index_pattern: str
    query: dict[str, Any]


class ElasticsearchQueryResult(BaseModel):
    index_pattern: str
    response: dict[str, Any]


class ElasticsearchLogSearchRequest(BaseModel):
    index_pattern: str | None = None
    query: str = Field(min_length=1)
    size: int = Field(default=10, ge=1, le=100)


class ElasticsearchLogSearchResult(BaseModel):
    index_pattern: str
    response: dict[str, Any]


class KibanaSavedObjectsResult(BaseModel):
    saved_object_type: str
    response: dict[str, Any]


class ElkSnapshotResult(BaseModel):
    cluster_health: ElasticsearchClusterHealthResult
    index_health: ElasticsearchIndexHealthResult
