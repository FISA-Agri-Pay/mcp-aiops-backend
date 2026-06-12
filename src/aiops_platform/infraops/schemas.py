from typing import Any, Literal

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


class MultiClusterQuerySourceResult(BaseModel):
    source: str
    status: Literal["SUCCESS", "FAILED"]
    data: dict[str, Any] | None = None
    error: str | None = None


class MultiClusterPrometheusQueryResult(BaseModel):
    query: str
    time: str | None = None
    partial: bool
    sources: list[MultiClusterQuerySourceResult]


class MultiClusterLokiQueryResult(BaseModel):
    query: str
    start: str | None = None
    end: str | None = None
    limit: int
    partial: bool
    sources: list[MultiClusterQuerySourceResult]


class TraceSearchRequest(BaseModel):
    traceql: str | None = Field(default=None, min_length=1)
    service_name: str | None = Field(default=None, max_length=253)
    operation_name: str | None = Field(default=None, max_length=253)
    start: str | None = None
    end: str | None = None
    min_duration: str | None = Field(default=None, max_length=40)
    max_duration: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=20, ge=1, le=100)


class TraceSearchResult(BaseModel):
    source: str = "tempo"
    query: dict[str, Any]
    traces: list[dict[str, Any]]
    raw: dict[str, Any]
    note: str | None = None


class TraceByIdRequest(BaseModel):
    trace_id: str = Field(min_length=1, max_length=128)


class TraceByIdResult(BaseModel):
    source: str = "tempo"
    trace_id: str
    trace: dict[str, Any]
    span_count: int
    error_span_count: int
    note: str | None = None


class TraceServiceSummaryResult(BaseModel):
    source: str = "tempo"
    service_name: str
    start: str | None = None
    end: str | None = None
    limit: int
    trace_count: int
    error_trace_count: int
    duration_ms_summary: dict[str, float | None]
    traces: list[dict[str, Any]]
    raw: dict[str, Any]
    note: str | None = None


class TraceErrorSpansResult(BaseModel):
    source: str = "tempo"
    trace_id: str
    span_count: int
    error_span_count: int
    error_spans: list[dict[str, Any]]
    note: str | None = None


class KubernetesResourceResult(BaseModel):
    source: str = "default"
    namespace: str
    items: list[dict[str, Any]]
    raw: dict[str, Any]


class PodLogsRequest(BaseModel):
    namespace: str | None = None
    pod_name: str = Field(min_length=1, max_length=253)
    container: str | None = Field(default=None, max_length=253)
    since_seconds: int | None = Field(default=None, ge=1, le=604800)
    tail_lines: int = Field(default=200, ge=1, le=5000)
    source: str | None = None


class PodLogsResult(BaseModel):
    source: str = "default"
    namespace: str
    pod_name: str
    container: str | None = None
    since_seconds: int | None = None
    tail_lines: int
    logs: str


class RolloutStatusRequest(BaseModel):
    namespace: str | None = None
    deployment_name: str = Field(min_length=1, max_length=253)
    source: str | None = None


class RolloutStatusResult(BaseModel):
    source: str = "default"
    namespace: str
    deployment_name: str
    rollout_status: Literal["HEALTHY", "PROGRESSING", "DEGRADED"]
    generation: int | None = None
    observed_generation: int | None = None
    desired_replicas: int | None = None
    updated_replicas: int | None = None
    ready_replicas: int | None = None
    available_replicas: int | None = None
    unavailable_replicas: int | None = None
    conditions: list[dict[str, Any]]
    raw: dict[str, Any]


class AlertmanagerAlertsRequest(BaseModel):
    active_only: bool = True
    receiver: str | None = Field(default=None, max_length=200)
    alertname: str | None = Field(default=None, max_length=200)
    severity: str | None = Field(default=None, max_length=80)
    limit: int = Field(default=100, ge=1, le=500)


class AlertmanagerAlertsResult(BaseModel):
    source: str = "alertmanager"
    active_only: bool
    receiver: str | None = None
    alertname: str | None = None
    severity: str | None = None
    limit: int
    items: list[dict[str, Any]]
    raw_count: int


class InfraOpsExternalReadResult(BaseModel):
    source: str
    resource: str
    request: dict[str, Any]
    response: Any
    note: str | None = None


class CurrentImageTagsRequest(BaseModel):
    namespace: str | None = None
    deployment_name: str | None = Field(default=None, min_length=1, max_length=253)
    source: str | None = None


class CurrentImageTagsResult(BaseModel):
    source: str = "default"
    namespace: str
    deployment_name: str | None = None
    items: list[dict[str, Any]]


class RecentDeploymentsRequest(BaseModel):
    namespace: str | None = None
    source: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class RecentDeploymentsResult(BaseModel):
    source: str = "default"
    namespace: str
    limit: int
    items: list[dict[str, Any]]


class ScaleDeploymentPreviewRequest(BaseModel):
    namespace: str | None = None
    deployment_name: str = Field(min_length=1, max_length=253)
    replicas: int = Field(ge=0, le=100)


class PodOperationPreviewRequest(BaseModel):
    namespace: str | None = None
    pod_name: str = Field(min_length=1, max_length=253)


class KubectlExecPreviewRequest(BaseModel):
    namespace: str | None = None
    pod_name: str = Field(min_length=1, max_length=253)
    command: list[str] = Field(min_length=1, max_length=20)


class InfraOpsChangePreviewResult(BaseModel):
    action: str
    namespace: str
    target_kind: str
    target_name: str
    request_payload: dict[str, Any]
    dry_run: bool = True
    safety_notes: list[str]


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


class InfraOpsSourceResult(BaseModel):
    source: str
    status: Literal["SUCCESS", "FAILED", "SKIPPED"]
    data: Any | None = None
    error: str | None = None


class RcaSnapshotRequest(BaseModel):
    incident_key: str | None = Field(default=None, max_length=120)
    namespace: str | None = None
    source: str | None = None
    index_pattern: str | None = None
    prometheus_query: str = Field(default="up", min_length=1)
    loki_query: str = Field(default='{job=~".+"}', min_length=1)
    loki_limit: int = Field(default=100, ge=1, le=1000)
    kafka_consumer_group: str | None = Field(default=None, max_length=253)
    kafka_topic: str | None = Field(default=None, max_length=253)
    batch_job_name: str | None = Field(default=None, max_length=253)
    context_bundle: dict[str, Any] | None = None


class RcaSnapshotResult(BaseModel):
    incident_key: str | None = None
    partial: bool
    sources: list[InfraOpsSourceResult]


class DailyOpsMetricsRequest(BaseModel):
    report_date: str | None = None
    namespace: str | None = None
    index_pattern: str | None = None
    prometheus_query: str = Field(default="up", min_length=1)
    loki_query: str = Field(default='{job=~".+"}', min_length=1)
    loki_limit: int = Field(default=100, ge=1, le=1000)
    kafka_consumer_group: str | None = Field(default=None, max_length=253)
    kafka_topic: str | None = Field(default=None, max_length=253)
    batch_job_name: str | None = Field(default=None, max_length=253)


class DailyOpsMetricsResult(BaseModel):
    report_date: str | None = None
    partial: bool
    metrics: dict[str, Any]
    sources: list[InfraOpsSourceResult]


class InfraOpsSearchResult(BaseModel):
    query: str | None = None
    limit: int
    items: list[dict[str, Any]]
    source: str
    note: str
