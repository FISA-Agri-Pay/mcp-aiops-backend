from typing import Any

from pydantic import BaseModel, Field


class PrometheusQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    time: str | None = None


class PrometheusQueryResult(BaseModel):
    status: str
    data: dict[str, Any]


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

