from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any

from aiops_platform.core.config import Settings, settings
from aiops_platform.infraops.clients import (
    BatchClient,
    ElasticsearchClient,
    KafkaAdminClient,
    KibanaClient,
    KubernetesClient,
    LokiClient,
    PrometheusClient,
)
from aiops_platform.infraops.schemas import (
    BatchRunStatusResult,
    ElasticsearchClusterHealthResult,
    ElasticsearchIndexHealthItem,
    ElasticsearchIndexHealthResult,
    ElasticsearchLogSearchRequest,
    ElasticsearchLogSearchResult,
    ElasticsearchQueryRequest,
    ElasticsearchQueryResult,
    ElkSnapshotResult,
    InfraOpsChangePreviewResult,
    KafkaConsumerLagResult,
    KibanaSavedObjectsResult,
    KubectlExecPreviewRequest,
    KubernetesResourceResult,
    LokiQueryRequest,
    LokiQueryResult,
    PodOperationPreviewRequest,
    PrometheusQueryResult,
    ScaleDeploymentPreviewRequest,
)


class InfraOpsValidationError(ValueError):
    pass


MAX_KIBANA_SAVED_OBJECTS_PER_PAGE = 100
KUBERNETES_RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
MAX_KUBECTL_COMMAND_PART_LENGTH = 200


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
        )

    def query_prometheus(self, query: str, time: str | None = None) -> PrometheusQueryResult:
        response = self._prometheus_client.query(query=query, time=time)
        return PrometheusQueryResult(status=response["status"], data=response["data"])

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

    def get_k8s_pods(self, namespace: str | None = None) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("pods", namespace=namespace)

    def get_k8s_events(self, namespace: str | None = None) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("events", namespace=namespace)

    def get_k8s_deployments(self, namespace: str | None = None) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("deployments", namespace=namespace)

    def get_k8s_hpa(self, namespace: str | None = None) -> KubernetesResourceResult:
        return self._get_kubernetes_resource("hpa", namespace=namespace)

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

    def _get_kubernetes_resource(
        self,
        resource: str,
        *,
        namespace: str | None,
    ) -> KubernetesResourceResult:
        resolved_namespace = self._resolve_namespace(namespace)
        response = {
            "pods": self._kubernetes_client.pods,
            "events": self._kubernetes_client.events,
            "deployments": self._kubernetes_client.deployments,
            "hpa": self._kubernetes_client.hpa,
        }[resource](resolved_namespace)
        return KubernetesResourceResult(
            namespace=resolved_namespace,
            items=response.get("items", []),
            raw=response,
        )

    def _resolve_namespace(self, namespace: str | None) -> str:
        resolved_namespace = namespace or self._kubernetes_namespace_allowlist[0]
        validate_namespace(
            resolved_namespace,
            allowlist=self._kubernetes_namespace_allowlist,
        )
        return resolved_namespace


def parse_allowlist(value: str) -> tuple[str, ...]:
    allowlist = tuple(item.strip() for item in value.split(",") if item.strip())
    if not allowlist:
        raise InfraOpsValidationError("Elasticsearch index allowlist must not be empty.")
    return allowlist


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


def clamp_kibana_per_page(per_page: int) -> int:
    if not isinstance(per_page, int) or isinstance(per_page, bool):
        raise InfraOpsValidationError("Kibana per_page must be an integer.")
    return min(max(per_page, 1), MAX_KIBANA_SAVED_OBJECTS_PER_PAGE)
