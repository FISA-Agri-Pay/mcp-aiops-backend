from __future__ import annotations

import re
from collections.abc import Callable
from fnmatch import fnmatch
from typing import Any
from urllib.parse import urlparse

from aiops_platform.core.config import Settings, settings
from aiops_platform.infraops.clients import (
    BatchClient,
    ElasticsearchClient,
    InfraOpsClientError,
    KafkaAdminClient,
    KibanaClient,
    KubernetesClient,
    LokiClient,
    PrometheusClient,
)
from aiops_platform.infraops.schemas import (
    BatchRunStatusResult,
    DailyOpsMetricsRequest,
    DailyOpsMetricsResult,
    ElasticsearchClusterHealthResult,
    ElasticsearchIndexHealthItem,
    ElasticsearchIndexHealthResult,
    ElasticsearchLogSearchRequest,
    ElasticsearchLogSearchResult,
    ElasticsearchQueryRequest,
    ElasticsearchQueryResult,
    ElkSnapshotResult,
    InfraOpsChangePreviewResult,
    InfraOpsSearchResult,
    InfraOpsSourceResult,
    KafkaConsumerLagResult,
    KibanaSavedObjectsResult,
    KubectlExecPreviewRequest,
    KubernetesResourceResult,
    LokiQueryRequest,
    LokiQueryResult,
    MultiClusterLokiQueryResult,
    MultiClusterPrometheusQueryResult,
    MultiClusterQuerySourceResult,
    PodOperationPreviewRequest,
    PrometheusQueryRequest,
    PrometheusQueryResult,
    RcaSnapshotRequest,
    RcaSnapshotResult,
    ScaleDeploymentPreviewRequest,
)


class InfraOpsValidationError(ValueError):
    pass


MAX_KIBANA_SAVED_OBJECTS_PER_PAGE = 100
KUBERNETES_RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
OBSERVABILITY_SOURCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
MAX_KUBECTL_COMMAND_PART_LENGTH = 200
ObservabilitySourceUrls = tuple[tuple[str, str], ...]
KubernetesSource = tuple[KubernetesClient, tuple[str, ...]]


class InfraOpsService:
    def __init__(
        self,
        *,
        prometheus_client: PrometheusClient,
        loki_client: LokiClient,
        kubernetes_client: KubernetesClient,
        kafka_admin_client: KafkaAdminClient,
        batch_client: BatchClient,
        elasticsearch_client: ElasticsearchClient,
        kibana_client: KibanaClient,
        kubernetes_namespace_allowlist: tuple[str, ...],
        elasticsearch_index_allowlist: tuple[str, ...],
        kubernetes_sources: dict[str, KubernetesSource] | None = None,
        prometheus_sources: tuple[tuple[str, PrometheusClient], ...] | None = None,
        loki_sources: tuple[tuple[str, LokiClient], ...] | None = None,
        elasticsearch_enabled: bool = True,
    ) -> None:
        self._prometheus_client = prometheus_client
        self._loki_client = loki_client
        self._kubernetes_client = kubernetes_client
        self._kafka_admin_client = kafka_admin_client
        self._batch_client = batch_client
        self._elasticsearch_client = elasticsearch_client
        self._kibana_client = kibana_client
        self._kubernetes_namespace_allowlist = kubernetes_namespace_allowlist
        self._elasticsearch_index_allowlist = elasticsearch_index_allowlist
        self._prometheus_sources = prometheus_sources or (("default", prometheus_client),)
        self._loki_sources = loki_sources or (("default", loki_client),)
        self._kubernetes_sources = kubernetes_sources or {
            "eks": (kubernetes_client, kubernetes_namespace_allowlist)
        }
        self._elasticsearch_enabled = elasticsearch_enabled

    @classmethod
    def from_settings(cls, app_settings: Settings | None = None) -> InfraOpsService:
        app_settings = app_settings or settings
        return cls(
            prometheus_client=PrometheusClient(
                app_settings.prometheus_base_url,
                timeout_seconds=app_settings.prometheus_timeout_seconds,
            ),
            loki_client=LokiClient(
                app_settings.loki_base_url,
                timeout_seconds=app_settings.loki_timeout_seconds,
            ),
            kubernetes_client=KubernetesClient(
                app_settings.kubernetes_api_base_url,
                bearer_token=app_settings.kubernetes_bearer_token,
                bearer_token_file=app_settings.kubernetes_bearer_token_file,
                ca_cert_file=app_settings.kubernetes_ca_cert_file,
                timeout_seconds=app_settings.kubernetes_timeout_seconds,
            ),
            kafka_admin_client=KafkaAdminClient(
                app_settings.kafka_admin_base_url,
                timeout_seconds=app_settings.kafka_timeout_seconds,
            ),
            batch_client=BatchClient(
                app_settings.batch_api_base_url,
                timeout_seconds=app_settings.batch_timeout_seconds,
            ),
            elasticsearch_client=ElasticsearchClient(
                app_settings.elasticsearch_base_url,
                username=app_settings.elasticsearch_username,
                password=app_settings.elasticsearch_password,
                timeout_seconds=app_settings.elasticsearch_timeout_seconds,
            ),
            kibana_client=KibanaClient(
                app_settings.kibana_base_url,
                timeout_seconds=app_settings.elasticsearch_timeout_seconds,
            ),
            kubernetes_namespace_allowlist=parse_allowlist(
                app_settings.kubernetes_namespace_allowlist,
            ),
            elasticsearch_index_allowlist=parse_allowlist(
                app_settings.elasticsearch_index_allowlist,
            ),
            kubernetes_sources=build_kubernetes_sources(app_settings),
            prometheus_sources=build_prometheus_sources(app_settings),
            loki_sources=build_loki_sources(app_settings),
            elasticsearch_enabled=app_settings.infraops_elk_enabled,
        )

    def query_prometheus(self, query: str, time: str | None = None) -> PrometheusQueryResult:
        response = self._prometheus_client.query(query=query, time=time)
        return PrometheusQueryResult(status=response["status"], data=response["data"])

    def query_multi_cluster_prometheus(
        self,
        query: str,
        time: str | None = None,
    ) -> MultiClusterPrometheusQueryResult:
        request = PrometheusQueryRequest(query=query, time=time)
        sources = [
            capture_observability_source(
                source_name,
                lambda client=client: client.query(query=request.query, time=request.time),
            )
            for source_name, client in self._prometheus_sources
        ]
        return MultiClusterPrometheusQueryResult(
            query=request.query,
            time=request.time,
            partial=has_partial_observability_sources(sources),
            sources=sources,
        )

    def query_loki(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> LokiQueryResult:
        request = LokiQueryRequest(query=query, start=start, end=end, limit=limit)
        response = self._loki_client.query_range(
            request.query,
            start=request.start,
            end=request.end,
            limit=request.limit,
        )
        return LokiQueryResult(status=response["status"], data=response["data"])

    def query_multi_cluster_loki(
        self,
        query: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> MultiClusterLokiQueryResult:
        request = LokiQueryRequest(query=query, start=start, end=end, limit=limit)
        sources = [
            capture_observability_source(
                source_name,
                lambda client=client: client.query_range(
                    request.query,
                    start=request.start,
                    end=request.end,
                    limit=request.limit,
                ),
            )
            for source_name, client in self._loki_sources
        ]
        return MultiClusterLokiQueryResult(
            query=request.query,
            start=request.start,
            end=request.end,
            limit=request.limit,
            partial=has_partial_observability_sources(sources),
            sources=sources,
        )

    def get_k8s_pods(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("pods", namespace=namespace, source=source)

    def get_k8s_events(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("events", namespace=namespace, source=source)

    def get_k8s_deployments(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("deployments", namespace=namespace, source=source)

    def get_k8s_hpa(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("hpa", namespace=namespace, source=source)

    def get_kafka_consumer_lag(
        self,
        consumer_group: str,
        topic: str | None = None,
    ) -> KafkaConsumerLagResult:
        response = self._kafka_admin_client.consumer_lag(
            consumer_group=consumer_group,
            topic=topic,
        )
        return KafkaConsumerLagResult(
            consumer_group=consumer_group,
            topic=topic,
            response=response,
        )

    def get_batch_run_status(self, job_name: str | None = None) -> BatchRunStatusResult:
        response = self._batch_client.run_status(job_name=job_name)
        return BatchRunStatusResult(job_name=job_name, response=response)

    def preview_scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str | None = None,
    ) -> InfraOpsChangePreviewResult:
        request = ScaleDeploymentPreviewRequest(
            namespace=namespace,
            deployment_name=deployment_name,
            replicas=replicas,
        )
        resolved_namespace = self._resolve_namespace(request.namespace)
        validate_kubernetes_resource_name(request.deployment_name, resource="deployment")
        return InfraOpsChangePreviewResult(
            action="scale_deployment",
            namespace=resolved_namespace,
            target_kind="deployment",
            target_name=request.deployment_name,
            request_payload={
                "namespace": resolved_namespace,
                "deployment_name": request.deployment_name,
                "replicas": request.replicas,
            },
            safety_notes=[
                "Execution is blocked until administrator approval is implemented.",
                "No Kubernetes scale request was sent.",
            ],
        )

    def preview_restart_pod(
        self,
        pod_name: str,
        namespace: str | None = None,
    ) -> InfraOpsChangePreviewResult:
        request = PodOperationPreviewRequest(namespace=namespace, pod_name=pod_name)
        resolved_namespace = self._resolve_namespace(request.namespace)
        validate_kubernetes_resource_name(request.pod_name, resource="pod")
        return InfraOpsChangePreviewResult(
            action="restart_pod",
            namespace=resolved_namespace,
            target_kind="pod",
            target_name=request.pod_name,
            request_payload={"namespace": resolved_namespace, "pod_name": request.pod_name},
            safety_notes=[
                "Execution is blocked until administrator approval is implemented.",
                "No Kubernetes pod mutation request was sent.",
            ],
        )

    def preview_delete_pod(
        self,
        pod_name: str,
        namespace: str | None = None,
    ) -> InfraOpsChangePreviewResult:
        request = PodOperationPreviewRequest(namespace=namespace, pod_name=pod_name)
        resolved_namespace = self._resolve_namespace(request.namespace)
        validate_kubernetes_resource_name(request.pod_name, resource="pod")
        return InfraOpsChangePreviewResult(
            action="delete_pod",
            namespace=resolved_namespace,
            target_kind="pod",
            target_name=request.pod_name,
            request_payload={"namespace": resolved_namespace, "pod_name": request.pod_name},
            safety_notes=[
                "Destructive tool execution is blocked by policy.",
                "No Kubernetes delete request was sent.",
            ],
        )

    def preview_kubectl_exec(
        self,
        pod_name: str,
        command: list[str],
        namespace: str | None = None,
    ) -> InfraOpsChangePreviewResult:
        request = KubectlExecPreviewRequest(
            namespace=namespace,
            pod_name=pod_name,
            command=command,
        )
        resolved_namespace = self._resolve_namespace(request.namespace)
        validate_kubernetes_resource_name(request.pod_name, resource="pod")
        validate_kubectl_exec_command(request.command)
        return InfraOpsChangePreviewResult(
            action="run_kubectl_exec",
            namespace=resolved_namespace,
            target_kind="pod",
            target_name=request.pod_name,
            request_payload={
                "namespace": resolved_namespace,
                "pod_name": request.pod_name,
                "command": request.command,
            },
            safety_notes=[
                "Destructive exec tool execution is blocked by policy.",
                "No Kubernetes exec request was sent.",
            ],
        )

    def query_elasticsearch(
        self,
        index_pattern: str,
        query: dict[str, Any],
    ) -> ElasticsearchQueryResult:
        request = ElasticsearchQueryRequest(index_pattern=index_pattern, query=query)
        validate_index_pattern(
            request.index_pattern,
            allowlist=self._elasticsearch_index_allowlist,
        )
        response = self._elasticsearch_client.search(request.index_pattern, request.query)
        return ElasticsearchQueryResult(
            index_pattern=request.index_pattern,
            response=response,
        )

    def search_elasticsearch_logs(
        self,
        query: str,
        index_pattern: str | None = None,
        size: int = 10,
    ) -> ElasticsearchLogSearchResult:
        resolved_index_pattern = index_pattern or self._elasticsearch_index_allowlist[0]
        request = ElasticsearchLogSearchRequest(
            index_pattern=resolved_index_pattern,
            query=query,
            size=size,
        )
        search_body = {
            "query": {"query_string": {"query": request.query}},
            "size": request.size,
            "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        }
        response = self.query_elasticsearch(
            index_pattern=request.index_pattern or resolved_index_pattern,
            query=search_body,
        ).response
        return ElasticsearchLogSearchResult(
            index_pattern=request.index_pattern or resolved_index_pattern,
            response=response,
        )

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

    def get_kibana_saved_objects(
        self,
        saved_object_type: str = "dashboard",
        search: str | None = None,
        per_page: int = 20,
    ) -> KibanaSavedObjectsResult:
        clamped_per_page = clamp_kibana_per_page(per_page)
        response = self._kibana_client.find_saved_objects(
            saved_object_type,
            search=search,
            per_page=clamped_per_page,
        )
        return KibanaSavedObjectsResult(
            saved_object_type=saved_object_type,
            response=response,
        )

    def create_elk_snapshot(
        self,
        index_pattern: str | None = None,
    ) -> ElkSnapshotResult:
        return ElkSnapshotResult(
            cluster_health=self.get_elasticsearch_cluster_health(),
            index_health=self.get_elasticsearch_index_health(index_pattern=index_pattern),
        )

    def create_rca_snapshot(
        self,
        incident_key: str | None = None,
        namespace: str | None = None,
        index_pattern: str | None = None,
        prometheus_query: str = "up",
        loki_query: str = '{job=~".+"}',
        loki_limit: int = 100,
        kafka_consumer_group: str | None = None,
        kafka_topic: str | None = None,
        batch_job_name: str | None = None,
    ) -> RcaSnapshotResult:
        request = RcaSnapshotRequest(
            incident_key=incident_key,
            namespace=namespace,
            index_pattern=index_pattern,
            prometheus_query=prometheus_query,
            loki_query=loki_query,
            loki_limit=loki_limit,
            kafka_consumer_group=kafka_consumer_group,
            kafka_topic=kafka_topic,
            batch_job_name=batch_job_name,
        )
        sources = [
            self._capture_source(
                "prometheus",
                lambda: self.query_prometheus(request.prometheus_query).model_dump(mode="json"),
            ),
            self._capture_source(
                "loki",
                lambda: self.query_loki(
                    query=request.loki_query,
                    limit=request.loki_limit,
                ).model_dump(mode="json"),
            ),
            self._capture_elasticsearch_source(
                "elasticsearch",
                lambda: self.create_elk_snapshot(
                    index_pattern=request.index_pattern,
                ).model_dump(mode="json"),
            ),
            self._capture_source(
                "kubernetes",
                lambda: {
                    "pods": self.get_k8s_pods(namespace=request.namespace).model_dump(
                        mode="json"
                    ),
                    "events": self.get_k8s_events(namespace=request.namespace).model_dump(
                        mode="json"
                    ),
                    "deployments": self.get_k8s_deployments(
                        namespace=request.namespace,
                    ).model_dump(mode="json"),
                    "hpa": self.get_k8s_hpa(namespace=request.namespace).model_dump(
                        mode="json"
                    ),
                },
            ),
            self._capture_optional_source(
                "kafka",
                request.kafka_consumer_group,
                lambda: self.get_kafka_consumer_lag(
                    consumer_group=request.kafka_consumer_group or "",
                    topic=request.kafka_topic,
                ).model_dump(mode="json"),
            ),
            self._capture_optional_source(
                "batch",
                request.batch_job_name,
                lambda: self.get_batch_run_status(
                    job_name=request.batch_job_name,
                ).model_dump(mode="json"),
            ),
        ]
        return RcaSnapshotResult(
            incident_key=request.incident_key,
            partial=has_partial_sources(sources),
            sources=sources,
        )

    def aggregate_daily_ops_metrics(
        self,
        report_date: str | None = None,
        namespace: str | None = None,
        index_pattern: str | None = None,
        prometheus_query: str = "up",
        loki_query: str = '{job=~".+"}',
        loki_limit: int = 100,
        kafka_consumer_group: str | None = None,
        kafka_topic: str | None = None,
        batch_job_name: str | None = None,
    ) -> DailyOpsMetricsResult:
        request = DailyOpsMetricsRequest(
            report_date=report_date,
            namespace=namespace,
            index_pattern=index_pattern,
            prometheus_query=prometheus_query,
            loki_query=loki_query,
            loki_limit=loki_limit,
            kafka_consumer_group=kafka_consumer_group,
            kafka_topic=kafka_topic,
            batch_job_name=batch_job_name,
        )
        sources = [
            self._capture_source(
                "prometheus",
                lambda: self.query_prometheus(request.prometheus_query).model_dump(mode="json"),
            ),
            self._capture_source(
                "loki",
                lambda: self.query_loki(
                    query=request.loki_query,
                    limit=request.loki_limit,
                ).model_dump(mode="json"),
            ),
            self._capture_elasticsearch_source(
                "elasticsearch_cluster",
                lambda: self.get_elasticsearch_cluster_health().model_dump(mode="json"),
            ),
            self._capture_elasticsearch_source(
                "elasticsearch_indices",
                lambda: self.get_elasticsearch_index_health(
                    index_pattern=request.index_pattern,
                ).model_dump(mode="json"),
            ),
            self._capture_source(
                "kubernetes",
                lambda: {
                    "pod_count": len(
                        self.get_k8s_pods(namespace=request.namespace).items,
                    ),
                    "event_count": len(
                        self.get_k8s_events(namespace=request.namespace).items,
                    ),
                    "deployment_count": len(
                        self.get_k8s_deployments(namespace=request.namespace).items,
                    ),
                    "hpa_count": len(
                        self.get_k8s_hpa(namespace=request.namespace).items,
                    ),
                },
            ),
            self._capture_optional_source(
                "kafka",
                request.kafka_consumer_group,
                lambda: self.get_kafka_consumer_lag(
                    consumer_group=request.kafka_consumer_group or "",
                    topic=request.kafka_topic,
                ).model_dump(mode="json"),
            ),
            self._capture_optional_source(
                "batch",
                request.batch_job_name,
                lambda: self.get_batch_run_status(
                    job_name=request.batch_job_name,
                ).model_dump(mode="json"),
            ),
        ]
        return DailyOpsMetricsResult(
            report_date=request.report_date,
            partial=has_partial_sources(sources),
            metrics=build_daily_metrics(sources),
            sources=sources,
        )

    def search_incidents(
        self,
        query: str | None = None,
        limit: int = 20,
    ) -> InfraOpsSearchResult:
        return InfraOpsSearchResult(
            query=query,
            limit=clamp_search_limit(limit),
            items=[],
            source="incidents",
            note="Incident persistence is not connected yet; returning an empty read-only result.",
        )

    def search_rca_history(
        self,
        query: str | None = None,
        limit: int = 20,
    ) -> InfraOpsSearchResult:
        return InfraOpsSearchResult(
            query=query,
            limit=clamp_search_limit(limit),
            items=[],
            source="rca_history",
            note="RCA history persistence is not connected yet.",
        )

    def _get_kubernetes_resource(
        self,
        resource: str,
        *,
        namespace: str | None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        source_name, client, namespace_allowlist = self._resolve_kubernetes_source(source)
        resolved_namespace = self._resolve_namespace(namespace, allowlist=namespace_allowlist)
        response = {
            "pods": client.pods,
            "events": client.events,
            "deployments": client.deployments,
            "hpa": client.hpa,
        }[resource](resolved_namespace)
        return KubernetesResourceResult(
            source=source_name,
            namespace=resolved_namespace,
            items=response.get("items", []),
            raw=response,
        )

    def _resolve_kubernetes_source(self, source: str | None) -> tuple[str, KubernetesClient, tuple[str, ...]]:
        resolved_source = source.strip() if source else "eks"
        if resolved_source not in self._kubernetes_sources:
            available_sources = ", ".join(sorted(self._kubernetes_sources))
            raise InfraOpsValidationError(
                f"Kubernetes source must be one of: {available_sources}."
            )
        client, namespace_allowlist = self._kubernetes_sources[resolved_source]
        return resolved_source, client, namespace_allowlist

    def _resolve_namespace(
        self,
        namespace: str | None,
        *,
        allowlist: tuple[str, ...] | None = None,
    ) -> str:
        resolved_allowlist = allowlist or self._kubernetes_namespace_allowlist
        resolved_namespace = namespace or resolved_allowlist[0]
        validate_namespace(
            resolved_namespace,
            allowlist=resolved_allowlist,
        )
        return resolved_namespace

    def _capture_source(self, source: str, loader) -> InfraOpsSourceResult:
        try:
            return InfraOpsSourceResult(
                source=source,
                status="SUCCESS",
                data=loader(),
            )
        except Exception as exc:
            return InfraOpsSourceResult(source=source, status="FAILED", error=str(exc))

    def _capture_optional_source(
        self,
        source: str,
        enabled_value: str | None,
        loader,
    ) -> InfraOpsSourceResult:
        if not enabled_value:
            return InfraOpsSourceResult(
                source=source,
                status="SKIPPED",
                error="Required input was not provided.",
            )
        return self._capture_source(source, loader)

    def _capture_elasticsearch_source(self, source: str, loader) -> InfraOpsSourceResult:
        if not self._elasticsearch_enabled:
            return InfraOpsSourceResult(
                source=source,
                status="SKIPPED",
                error="Elasticsearch/OpenSearch integration is disabled.",
            )
        return self._capture_source(source, loader)


def parse_allowlist(value: str) -> tuple[str, ...]:
    allowlist = tuple(item.strip() for item in value.split(",") if item.strip())
    if not allowlist:
        raise InfraOpsValidationError("Elasticsearch index allowlist must not be empty.")
    return allowlist


def build_prometheus_sources(app_settings: Settings) -> tuple[tuple[str, PrometheusClient], ...]:
    source_urls = parse_observability_source_urls(
        app_settings.prometheus_source_urls,
        default_name="default",
        default_url=app_settings.prometheus_base_url,
    )
    return tuple(
        (
            source_name,
            PrometheusClient(
                source_url,
                timeout_seconds=app_settings.prometheus_timeout_seconds,
            ),
        )
        for source_name, source_url in source_urls
    )


def build_loki_sources(app_settings: Settings) -> tuple[tuple[str, LokiClient], ...]:
    source_urls = parse_observability_source_urls(
        app_settings.loki_source_urls,
        default_name="default",
        default_url=app_settings.loki_base_url,
    )
    return tuple(
        (
            source_name,
            LokiClient(
                source_url,
                timeout_seconds=app_settings.loki_timeout_seconds,
            ),
        )
        for source_name, source_url in source_urls
    )


def build_kubernetes_sources(app_settings: Settings) -> dict[str, KubernetesSource]:
    sources: dict[str, KubernetesSource] = {
        "eks": (
            KubernetesClient(
                app_settings.kubernetes_api_base_url,
                bearer_token=app_settings.kubernetes_bearer_token,
                bearer_token_file=app_settings.kubernetes_bearer_token_file,
                ca_cert_file=app_settings.kubernetes_ca_cert_file,
                timeout_seconds=app_settings.kubernetes_timeout_seconds,
            ),
            parse_allowlist(app_settings.kubernetes_namespace_allowlist),
        )
    }
    if app_settings.onprem_kubernetes_api_base_url:
        sources["onprem"] = (
            KubernetesClient(
                app_settings.onprem_kubernetes_api_base_url,
                bearer_token=app_settings.onprem_kubernetes_bearer_token,
                ca_cert_data=app_settings.onprem_kubernetes_ca_cert,
                timeout_seconds=app_settings.kubernetes_timeout_seconds,
            ),
            parse_allowlist(app_settings.onprem_kubernetes_namespace_allowlist),
        )
    return sources


def parse_observability_source_urls(
    value: str,
    *,
    default_name: str,
    default_url: str,
) -> ObservabilitySourceUrls:
    entries = tuple(item.strip() for item in value.split(",") if item.strip())
    if not entries:
        validate_observability_source_url(default_url)
        return ((default_name, default_url),)

    sources: list[tuple[str, str]] = []
    seen_names: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        source_name, source_url = split_observability_source_entry(entry, index=index)

        validate_observability_source_name(source_name)
        validate_observability_source_url(source_url)
        source_key = source_name.lower()
        if source_key in seen_names:
            raise InfraOpsValidationError("Observability source names must be unique.")
        seen_names.add(source_key)
        sources.append((source_name, source_url))
    return tuple(sources)


def split_observability_source_entry(entry: str, *, index: int) -> tuple[str, str]:
    if "=" in entry:
        source_name, source_url = (part.strip() for part in entry.split("=", 1))
        if OBSERVABILITY_SOURCE_NAME_PATTERN.fullmatch(source_name):
            return source_name, source_url
    return f"source-{index}", entry


def validate_observability_source_name(source_name: str) -> None:
    if OBSERVABILITY_SOURCE_NAME_PATTERN.fullmatch(source_name):
        return
    raise InfraOpsValidationError("Observability source name is invalid.")


def validate_observability_source_url(source_url: str) -> None:
    parsed_url = urlparse(source_url)
    if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
        return
    raise InfraOpsValidationError("Observability source URL must be http or https.")


def capture_observability_source(
    source_name: str,
    loader: Callable[[], dict[str, Any]],
) -> MultiClusterQuerySourceResult:
    try:
        return MultiClusterQuerySourceResult(
            source=source_name,
            status="SUCCESS",
            data=loader(),
        )
    except InfraOpsClientError as exc:
        return MultiClusterQuerySourceResult(
            source=source_name,
            status="FAILED",
            error=f"loader failure: {type(exc).__name__}",
        )


def has_partial_observability_sources(sources: list[MultiClusterQuerySourceResult]) -> bool:
    return any(source.status != "SUCCESS" for source in sources)


def validate_index_pattern(index_pattern: str, *, allowlist: tuple[str, ...]) -> None:
    index_patterns = tuple(pattern.strip() for pattern in index_pattern.split(","))
    if not all(index_patterns):
        raise InfraOpsValidationError("Elasticsearch index pattern must not be empty.")
    if any("/" in pattern or "\\" in pattern for pattern in index_patterns):
        raise InfraOpsValidationError(
            "Elasticsearch index pattern must not contain path separators."
        )

    if all(
        any(fnmatch(pattern, allowed) for allowed in allowlist)
        for pattern in index_patterns
    ):
        return
    raise InfraOpsValidationError("Elasticsearch index pattern is not allowlisted.")


def validate_namespace(namespace: str, *, allowlist: tuple[str, ...]) -> None:
    if namespace in allowlist:
        return
    raise InfraOpsValidationError("Kubernetes namespace is not allowlisted.")


def validate_kubernetes_resource_name(name: str, *, resource: str) -> None:
    if len(name) <= 63 and KUBERNETES_RESOURCE_NAME_PATTERN.fullmatch(name):
        return
    raise InfraOpsValidationError(f"Kubernetes {resource} name is invalid.")


def validate_kubectl_exec_command(command: list[str]) -> None:
    if any(not part.strip() for part in command):
        raise InfraOpsValidationError("kubectl exec command parts must not be empty.")
    if any(len(part) > MAX_KUBECTL_COMMAND_PART_LENGTH for part in command):
        raise InfraOpsValidationError("kubectl exec command part is too long.")


def has_partial_sources(sources: list[InfraOpsSourceResult]) -> bool:
    return any(source.status != "SUCCESS" for source in sources)


def build_daily_metrics(sources: list[InfraOpsSourceResult]) -> dict[str, Any]:
    metrics = {
        "successful_sources": sum(source.status == "SUCCESS" for source in sources),
        "failed_sources": sum(source.status == "FAILED" for source in sources),
        "skipped_sources": sum(source.status == "SKIPPED" for source in sources),
    }
    for source in sources:
        if source.source == "kubernetes" and isinstance(source.data, dict):
            metrics.update(source.data)
    return metrics


def clamp_search_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise InfraOpsValidationError("Search limit must be an integer.")
    return min(max(limit, 1), 100)


def clamp_kibana_per_page(per_page: int) -> int:
    if not isinstance(per_page, int) or isinstance(per_page, bool):
        raise InfraOpsValidationError("Kibana per_page must be an integer.")
    return min(max(per_page, 1), MAX_KIBANA_SAVED_OBJECTS_PER_PAGE)
