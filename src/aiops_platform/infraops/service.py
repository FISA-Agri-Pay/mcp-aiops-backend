from __future__ import annotations

import re
import socket
from collections.abc import Callable
from fnmatch import fnmatch
from ipaddress import ip_address, ip_network
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from aiops_platform.core.config import Settings, settings
from aiops_platform.infraops.clients import (
    AlertmanagerClient,
    ArgoCdClient,
    AwsOpsClient,
    BatchClient,
    ElasticsearchClient,
    InfraOpsClientError,
    KafkaAdminClient,
    KibanaClient,
    KubernetesClient,
    LokiClient,
    PrometheusClient,
    TempoClient,
)
from aiops_platform.infraops.schemas import (
    AlertmanagerAlertsRequest,
    AlertmanagerAlertsResult,
    BatchRunStatusResult,
    CurrentImageTagsRequest,
    CurrentImageTagsResult,
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
    InfraOpsExternalReadResult,
    InfraOpsSearchResult,
    InfraOpsSourceResult,
    KafkaConsumerLagResult,
    KibanaSavedObjectsResult,
    KubectlExecPreviewRequest,
    KubernetesIngressBackendMappingResult,
    KubernetesResourceResult,
    KubernetesServiceEndpointsResult,
    LokiQueryRequest,
    LokiQueryResult,
    MultiClusterLokiQueryResult,
    MultiClusterPrometheusQueryResult,
    MultiClusterQuerySourceResult,
    OnpremHttpRouteCheckResult,
    OnpremTcpConnectivityResult,
    PodLogsRequest,
    PodLogsResult,
    PodOperationPreviewRequest,
    PrometheusQueryRequest,
    PrometheusQueryResult,
    RcaSnapshotRequest,
    RcaSnapshotResult,
    RecentDeploymentsRequest,
    RecentDeploymentsResult,
    RolloutStatusRequest,
    RolloutStatusResult,
    ScaleDeploymentPreviewRequest,
    TraceByIdRequest,
    TraceByIdResult,
    TraceErrorSpansResult,
    TraceSearchRequest,
    TraceSearchResult,
    TraceServiceSummaryResult,
)


class InfraOpsValidationError(ValueError):
    pass


MAX_KIBANA_SAVED_OBJECTS_PER_PAGE = 100
KUBERNETES_RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
OBSERVABILITY_SOURCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
MAX_KUBECTL_COMMAND_PART_LENGTH = 200
DEFAULT_ONPREM_METALLB_ADDRESS = "10.30.2.100"
DEFAULT_ONPREM_INGRESS_ENDPOINT = "http://10.30.2.100"
DEFAULT_ONPREM_INGRESS_HEALTH_PATH = "/actuator/health"
PRIVATE_CONNECTIVITY_NETWORKS = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)
ObservabilitySourceUrls = tuple[tuple[str, str], ...]
KubernetesSource = tuple[KubernetesClient, tuple[str, ...]]


class InfraOpsService:
    def __init__(
        self,
        *,
        prometheus_client: PrometheusClient,
        loki_client: LokiClient,
        tempo_client: TempoClient,
        kubernetes_client: KubernetesClient,
        kafka_admin_client: KafkaAdminClient,
        batch_client: BatchClient,
        elasticsearch_client: ElasticsearchClient,
        kibana_client: KibanaClient,
        kubernetes_namespace_allowlist: tuple[str, ...],
        elasticsearch_index_allowlist: tuple[str, ...],
        alertmanager_client: AlertmanagerClient | None = None,
        aws_ops_client: AwsOpsClient | None = None,
        argocd_client: ArgoCdClient | None = None,
        kubernetes_sources: dict[str, KubernetesSource] | None = None,
        prometheus_sources: tuple[tuple[str, PrometheusClient], ...] | None = None,
        loki_sources: tuple[tuple[str, LokiClient], ...] | None = None,
        elasticsearch_enabled: bool = True,
    ) -> None:
        self._prometheus_client = prometheus_client
        self._loki_client = loki_client
        self._tempo_client = tempo_client
        self._kubernetes_client = kubernetes_client
        self._kafka_admin_client = kafka_admin_client
        self._batch_client = batch_client
        self._elasticsearch_client = elasticsearch_client
        self._kibana_client = kibana_client
        self._alertmanager_client = alertmanager_client or AlertmanagerClient("")
        self._aws_ops_client = aws_ops_client or AwsOpsClient("")
        self._argocd_client = argocd_client or ArgoCdClient("")
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
            tempo_client=TempoClient(
                app_settings.tempo_base_url,
                timeout_seconds=app_settings.tempo_timeout_seconds,
            ),
            alertmanager_client=AlertmanagerClient(
                app_settings.alertmanager_base_url,
                timeout_seconds=app_settings.alertmanager_timeout_seconds,
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
            aws_ops_client=AwsOpsClient(
                app_settings.aws_ops_base_url,
                timeout_seconds=app_settings.aws_ops_timeout_seconds,
            ),
            argocd_client=ArgoCdClient(
                app_settings.argocd_read_base_url,
                timeout_seconds=app_settings.argocd_timeout_seconds,
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

    def search_traces(
        self,
        traceql: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        start: str | None = None,
        end: str | None = None,
        min_duration: str | None = None,
        max_duration: str | None = None,
        limit: int = 20,
    ) -> TraceSearchResult:
        request = TraceSearchRequest(
            traceql=traceql,
            service_name=service_name,
            operation_name=operation_name,
            start=start,
            end=end,
            min_duration=min_duration,
            max_duration=max_duration,
            limit=limit,
        )
        response = self._tempo_client.search(
            traceql=request.traceql,
            service_name=request.service_name,
            operation_name=request.operation_name,
            start=request.start,
            end=request.end,
            min_duration=request.min_duration,
            max_duration=request.max_duration,
            limit=request.limit,
        )
        return TraceSearchResult(
            query=request.model_dump(mode="json"),
            traces=extract_traces_from_search_response(response),
            raw=response,
        )

    def get_trace_by_id(self, trace_id: str) -> TraceByIdResult:
        request = TraceByIdRequest(trace_id=trace_id)
        response = self._tempo_client.trace(request.trace_id)
        spans = extract_spans_from_trace_payload(response)
        error_spans = [span for span in spans if is_error_span(span)]
        return TraceByIdResult(
            trace_id=request.trace_id,
            trace=response,
            span_count=len(spans),
            error_span_count=len(error_spans),
        )

    def get_service_trace_summary(
        self,
        service_name: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> TraceServiceSummaryResult:
        request = TraceSearchRequest(
            service_name=service_name,
            start=start,
            end=end,
            limit=limit,
        )
        response = self._tempo_client.search(
            service_name=request.service_name,
            start=request.start,
            end=request.end,
            limit=request.limit,
        )
        traces = extract_traces_from_search_response(response)
        return TraceServiceSummaryResult(
            service_name=service_name,
            start=start,
            end=end,
            limit=request.limit,
            trace_count=len(traces),
            error_trace_count=count_error_traces(traces),
            duration_ms_summary=summarize_trace_durations(traces),
            traces=traces,
            raw=response,
        )

    def get_trace_error_spans(self, trace_id: str) -> TraceErrorSpansResult:
        request = TraceByIdRequest(trace_id=trace_id)
        response = self._tempo_client.trace(request.trace_id)
        spans = extract_spans_from_trace_payload(response)
        error_spans = [span for span in spans if is_error_span(span)]
        return TraceErrorSpansResult(
            trace_id=request.trace_id,
            span_count=len(spans),
            error_span_count=len(error_spans),
            error_spans=error_spans,
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

    def check_onprem_metallb_endpoint(
        self,
        address: str = DEFAULT_ONPREM_METALLB_ADDRESS,
        port: int = 80,
        timeout_seconds: float = 3.0,
    ) -> OnpremTcpConnectivityResult:
        validate_private_ip_target(address)
        validate_tcp_port(port)
        resolved_timeout = clamp_timeout_seconds(timeout_seconds)
        started_at = perf_counter()
        try:
            with socket.create_connection((address, port), timeout=resolved_timeout):
                latency_ms = round((perf_counter() - started_at) * 1000, 2)
            return OnpremTcpConnectivityResult(
                target_host=address,
                port=port,
                timeout_seconds=resolved_timeout,
                reachable=True,
                status="HEALTHY",
                latency_ms=latency_ms,
            )
        except OSError as exc:
            latency_ms = round((perf_counter() - started_at) * 1000, 2)
            return OnpremTcpConnectivityResult(
                target_host=address,
                port=port,
                timeout_seconds=resolved_timeout,
                reachable=False,
                status="DEGRADED",
                latency_ms=latency_ms,
                error=exc.__class__.__name__,
            )

    def check_onprem_ingress_route(
        self,
        endpoint: str = DEFAULT_ONPREM_INGRESS_ENDPOINT,
        host_header: str | None = None,
        path: str = DEFAULT_ONPREM_INGRESS_HEALTH_PATH,
        expected_status_min: int = 200,
        expected_status_max: int = 399,
        timeout_seconds: float = 5.0,
    ) -> OnpremHttpRouteCheckResult:
        url = build_private_http_url(endpoint=endpoint, path=path)
        validate_http_host_header(host_header)
        validate_http_status_range(expected_status_min, expected_status_max)
        resolved_timeout = clamp_timeout_seconds(timeout_seconds)
        headers = {"Host": host_header} if host_header else {}
        started_at = perf_counter()
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=resolved_timeout) as response:
                response_body = response.read(512).decode("utf-8", errors="replace")
                http_status = response.status
                latency_ms = round((perf_counter() - started_at) * 1000, 2)
        except HTTPError as exc:
            response_body = exc.read(512).decode("utf-8", errors="replace")
            http_status = exc.code
            latency_ms = round((perf_counter() - started_at) * 1000, 2)
            healthy = expected_status_min <= http_status <= expected_status_max
            return OnpremHttpRouteCheckResult(
                url=url,
                host_header=host_header,
                path=path,
                timeout_seconds=resolved_timeout,
                expected_status_min=expected_status_min,
                expected_status_max=expected_status_max,
                reachable=True,
                healthy=healthy,
                status="HEALTHY" if healthy else "DEGRADED",
                http_status=http_status,
                latency_ms=latency_ms,
                response_excerpt=response_body[:256],
                error=f"HTTP {http_status}",
            )
        except URLError as exc:
            latency_ms = round((perf_counter() - started_at) * 1000, 2)
            return OnpremHttpRouteCheckResult(
                url=url,
                host_header=host_header,
                path=path,
                timeout_seconds=resolved_timeout,
                expected_status_min=expected_status_min,
                expected_status_max=expected_status_max,
                reachable=False,
                healthy=False,
                status="DEGRADED",
                latency_ms=latency_ms,
                error=exc.reason.__class__.__name__,
            )

        healthy = expected_status_min <= http_status <= expected_status_max
        return OnpremHttpRouteCheckResult(
            url=url,
            host_header=host_header,
            path=path,
            timeout_seconds=resolved_timeout,
            expected_status_min=expected_status_min,
            expected_status_max=expected_status_max,
            reachable=True,
            healthy=healthy,
            status="HEALTHY" if healthy else "DEGRADED",
            http_status=http_status,
            latency_ms=latency_ms,
            response_excerpt=response_body[:256],
        )

    def get_k8s_service_endpoints(
        self,
        service_name: str,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesServiceEndpointsResult:
        validate_kubernetes_resource_name(service_name, resource="service")
        source_name, client, namespace_allowlist = self._resolve_kubernetes_source(source)
        resolved_namespace = self._resolve_namespace(
            namespace,
            allowlist=namespace_allowlist,
        )
        service = client.service(resolved_namespace, service_name)
        endpoints = client.endpoints(resolved_namespace, service_name)
        ready_addresses, not_ready_addresses = summarize_endpoint_addresses(endpoints)
        service_spec = service.get("spec", {})
        return KubernetesServiceEndpointsResult(
            source=source_name,
            namespace=resolved_namespace,
            service_name=service_name,
            service_type=service_spec.get("type"),
            cluster_ip=service_spec.get("clusterIP"),
            selector=service_spec.get("selector") or {},
            ports=service_spec.get("ports") or [],
            ready_addresses=ready_addresses,
            not_ready_addresses=not_ready_addresses,
            ready_count=len(ready_addresses),
            not_ready_count=len(not_ready_addresses),
            status="HEALTHY" if ready_addresses and not not_ready_addresses else "DEGRADED",
        )

    def get_k8s_ingress_backend_mapping(
        self,
        namespace: str | None = None,
        source: str | None = None,
        host: str | None = None,
        path: str | None = None,
        service_name: str | None = None,
    ) -> KubernetesIngressBackendMappingResult:
        source_name, client, namespace_allowlist = self._resolve_kubernetes_source(source)
        resolved_namespace = self._resolve_namespace(
            namespace,
            allowlist=namespace_allowlist,
        )
        if service_name is not None:
            validate_kubernetes_resource_name(service_name, resource="service")
        validate_optional_ingress_host(host)
        if path is not None:
            validate_http_path(path)

        ingresses = client.ingresses(resolved_namespace).get("items", [])
        matched_rules = find_ingress_backend_rules(
            ingresses,
            host=host,
            path=path,
            service_name=service_name,
        )
        return KubernetesIngressBackendMappingResult(
            source=source_name,
            namespace=resolved_namespace,
            host=host,
            path=path,
            service_name=service_name,
            matched_rules=matched_rules,
            ingress_count=len(ingresses),
            status="HEALTHY" if matched_rules else "DEGRADED",
        )

    def get_pod_logs(
        self,
        pod_name: str,
        namespace: str | None = None,
        container: str | None = None,
        since_seconds: int | None = None,
        tail_lines: int = 200,
        source: str | None = None,
    ) -> PodLogsResult:
        request = PodLogsRequest(
            namespace=namespace,
            pod_name=pod_name,
            container=container,
            since_seconds=since_seconds,
            tail_lines=tail_lines,
            source=source,
        )
        source_name, client, namespace_allowlist = self._resolve_kubernetes_source(
            request.source
        )
        resolved_namespace = self._resolve_namespace(
            request.namespace,
            allowlist=namespace_allowlist,
        )
        validate_kubernetes_resource_name(request.pod_name, resource="pod")
        if request.container is not None:
            validate_kubernetes_resource_name(request.container, resource="container")

        logs = client.pod_logs(
            resolved_namespace,
            request.pod_name,
            container=request.container,
            since_seconds=request.since_seconds,
            tail_lines=request.tail_lines,
        )
        return PodLogsResult(
            source=source_name,
            namespace=resolved_namespace,
            pod_name=request.pod_name,
            container=request.container,
            since_seconds=request.since_seconds,
            tail_lines=request.tail_lines,
            logs=logs,
        )

    def get_rollout_status(
        self,
        deployment_name: str,
        namespace: str | None = None,
        source: str | None = None,
    ) -> RolloutStatusResult:
        request = RolloutStatusRequest(
            namespace=namespace,
            deployment_name=deployment_name,
            source=source,
        )
        source_name, client, namespace_allowlist = self._resolve_kubernetes_source(
            request.source
        )
        resolved_namespace = self._resolve_namespace(
            request.namespace,
            allowlist=namespace_allowlist,
        )
        validate_kubernetes_resource_name(request.deployment_name, resource="deployment")
        deployment = client.deployment(resolved_namespace, request.deployment_name)
        return build_rollout_status_result(
            source=source_name,
            namespace=resolved_namespace,
            deployment_name=request.deployment_name,
            deployment=deployment,
        )

    def get_alertmanager_alerts(
        self,
        active_only: bool = True,
        receiver: str | None = None,
        alertname: str | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> AlertmanagerAlertsResult:
        request = AlertmanagerAlertsRequest(
            active_only=active_only,
            receiver=receiver,
            alertname=alertname,
            severity=severity,
            limit=limit,
        )
        alerts = self._alertmanager_client.alerts(
            active_only=request.active_only,
            receiver=request.receiver,
            alertname=request.alertname,
            severity=request.severity,
        )
        return AlertmanagerAlertsResult(
            active_only=request.active_only,
            receiver=request.receiver,
            alertname=request.alertname,
            severity=request.severity,
            limit=request.limit,
            items=alerts[: request.limit],
            raw_count=len(alerts),
        )

    def get_sqs_queue_attributes(
        self,
        queue_name: str | None = None,
        queue_url: str | None = None,
        region: str | None = None,
    ) -> InfraOpsExternalReadResult:
        request = clean_request_payload(
            queue_name=queue_name,
            queue_url=queue_url,
            region=region,
        )
        return self._aws_external_read(
            resource="sqs_queue_attributes",
            request=request,
            loader=lambda: self._aws_ops_client.sqs_queue_attributes(**request),
        )

    def get_sqs_dlq_attributes(
        self,
        queue_name: str | None = None,
        queue_url: str | None = None,
        region: str | None = None,
    ) -> InfraOpsExternalReadResult:
        request = clean_request_payload(
            queue_name=queue_name,
            queue_url=queue_url,
            region=region,
        )
        return self._aws_external_read(
            resource="sqs_dlq_attributes",
            request=request,
            loader=lambda: self._aws_ops_client.sqs_dlq_attributes(**request),
        )

    def get_alb_target_health(
        self,
        target_group_arn: str | None = None,
        target_group_name: str | None = None,
        load_balancer_name: str | None = None,
        region: str | None = None,
    ) -> InfraOpsExternalReadResult:
        request = clean_request_payload(
            target_group_arn=target_group_arn,
            target_group_name=target_group_name,
            load_balancer_name=load_balancer_name,
            region=region,
        )
        return self._aws_external_read(
            resource="alb_target_health",
            request=request,
            loader=lambda: self._aws_ops_client.alb_target_health(**request),
        )

    def get_cloudfront_origin_mapping(
        self,
        distribution_id: str | None = None,
        domain_name: str | None = None,
    ) -> InfraOpsExternalReadResult:
        request = clean_request_payload(
            distribution_id=distribution_id,
            domain_name=domain_name,
        )
        return self._aws_external_read(
            resource="cloudfront_origin_mapping",
            request=request,
            loader=lambda: self._aws_ops_client.cloudfront_origin_mapping(**request),
        )

    def get_cloudfront_distribution_status(
        self,
        distribution_id: str | None = None,
    ) -> InfraOpsExternalReadResult:
        request = clean_request_payload(distribution_id=distribution_id)
        return self._aws_external_read(
            resource="cloudfront_distribution_status",
            request=request,
            loader=lambda: self._aws_ops_client.cloudfront_distribution_status(**request),
        )

    def get_argocd_application_status(
        self,
        application_name: str,
        project: str | None = None,
    ) -> InfraOpsExternalReadResult:
        request = clean_request_payload(
            application_name=application_name,
            project=project,
        )
        if not self._argocd_client.is_configured:
            return InfraOpsExternalReadResult(
                source="argocd",
                resource="application_status",
                request=request,
                response={},
                note="ArgoCD read API is not configured.",
            )
        return InfraOpsExternalReadResult(
            source="argocd",
            resource="application_status",
            request=request,
            response=self._argocd_client.application_status(
                application_name=application_name,
                project=project,
            ),
        )

    def get_current_image_tags(
        self,
        namespace: str | None = None,
        deployment_name: str | None = None,
        source: str | None = None,
    ) -> CurrentImageTagsResult:
        request = CurrentImageTagsRequest(
            namespace=namespace,
            deployment_name=deployment_name,
            source=source,
        )
        source_name, client, namespace_allowlist = self._resolve_kubernetes_source(
            request.source
        )
        resolved_namespace = self._resolve_namespace(
            request.namespace,
            allowlist=namespace_allowlist,
        )
        if request.deployment_name is not None:
            validate_kubernetes_resource_name(
                request.deployment_name,
                resource="deployment",
            )
            deployments = [
                client.deployment(resolved_namespace, request.deployment_name),
            ]
        else:
            deployments = client.deployments(resolved_namespace).get("items", [])

        return CurrentImageTagsResult(
            source=source_name,
            namespace=resolved_namespace,
            deployment_name=request.deployment_name,
            items=build_image_tag_items(deployments),
        )

    def get_recent_deployments(
        self,
        namespace: str | None = None,
        source: str | None = None,
        limit: int = 20,
    ) -> RecentDeploymentsResult:
        request = RecentDeploymentsRequest(
            namespace=namespace,
            source=source,
            limit=limit,
        )
        source_name, client, namespace_allowlist = self._resolve_kubernetes_source(
            request.source
        )
        resolved_namespace = self._resolve_namespace(
            request.namespace,
            allowlist=namespace_allowlist,
        )
        deployments = client.deployments(resolved_namespace).get("items", [])
        deployments = sorted(
            deployments,
            key=lambda item: item.get("metadata", {}).get("creationTimestamp") or "",
            reverse=True,
        )
        return RecentDeploymentsResult(
            source=source_name,
            namespace=resolved_namespace,
            limit=request.limit,
            items=[
                summarize_deployment_item(deployment)
                for deployment in deployments[: request.limit]
            ],
        )

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
        source: str | None = None,
        index_pattern: str | None = None,
        prometheus_query: str = "up",
        loki_query: str = '{job=~".+"}',
        loki_limit: int = 100,
        kafka_consumer_group: str | None = None,
        kafka_topic: str | None = None,
        batch_job_name: str | None = None,
        context_bundle: dict[str, Any] | None = None,
    ) -> RcaSnapshotResult:
        request = RcaSnapshotRequest(
            incident_key=incident_key,
            namespace=namespace,
            source=source,
            index_pattern=index_pattern,
            prometheus_query=prometheus_query,
            loki_query=loki_query,
            loki_limit=loki_limit,
            kafka_consumer_group=kafka_consumer_group,
            kafka_topic=kafka_topic,
            batch_job_name=batch_job_name,
            context_bundle=context_bundle,
        )
        sources = [
            *(
                [
                    InfraOpsSourceResult(
                        source="incident_context_bundle",
                        status="SUCCESS",
                        data=request.context_bundle,
                    )
                ]
                if request.context_bundle
                else []
            ),
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
                    "pods": self.get_k8s_pods(
                        namespace=request.namespace,
                        source=request.source,
                    ).model_dump(mode="json"),
                    "events": self.get_k8s_events(
                        namespace=request.namespace,
                        source=request.source,
                    ).model_dump(mode="json"),
                    "deployments": self.get_k8s_deployments(
                        namespace=request.namespace,
                        source=request.source,
                    ).model_dump(mode="json"),
                    "hpa": self.get_k8s_hpa(
                        namespace=request.namespace,
                        source=request.source,
                    ).model_dump(mode="json"),
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

    def _resolve_kubernetes_source(
        self,
        source: str | None,
    ) -> tuple[str, KubernetesClient, tuple[str, ...]]:
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

    def _aws_external_read(
        self,
        *,
        resource: str,
        request: dict[str, Any],
        loader: Callable[[], dict[str, Any]],
    ) -> InfraOpsExternalReadResult:
        if not self._aws_ops_client.is_configured:
            return InfraOpsExternalReadResult(
                source="aws",
                resource=resource,
                request=request,
                response={},
                note="AWS ops read proxy is not configured.",
            )
        return InfraOpsExternalReadResult(
            source="aws",
            resource=resource,
            request=request,
            response=loader(),
        )


def parse_allowlist(value: str) -> tuple[str, ...]:
    allowlist = tuple(item.strip() for item in value.split(",") if item.strip())
    if not allowlist:
        raise InfraOpsValidationError("Elasticsearch index allowlist must not be empty.")
    return allowlist


def validate_private_ip_target(address: str) -> None:
    try:
        parsed_address = ip_address(address)
    except ValueError as exc:
        raise InfraOpsValidationError(
            "Connectivity target must be a literal private IP address."
        ) from exc
    if any(parsed_address in network for network in PRIVATE_CONNECTIVITY_NETWORKS):
        return
    raise InfraOpsValidationError(
        "Connectivity target must be in an approved private network."
    )


def validate_tcp_port(port: int) -> None:
    if 1 <= port <= 65535:
        return
    raise InfraOpsValidationError("TCP port must be between 1 and 65535.")


def clamp_timeout_seconds(timeout_seconds: float) -> float:
    return min(max(float(timeout_seconds), 0.1), 15.0)


def build_private_http_url(*, endpoint: str, path: str) -> str:
    parsed_endpoint = urlparse(endpoint)
    if parsed_endpoint.scheme not in {"http", "https"} or parsed_endpoint.hostname is None:
        raise InfraOpsValidationError("Ingress endpoint must be an http(s) URL.")
    validate_private_ip_target(parsed_endpoint.hostname)
    validate_http_path(path)
    base_url = endpoint.rstrip("/") + "/"
    return urljoin(base_url, path.lstrip("/"))


def validate_http_path(path: str) -> None:
    if path.startswith("/") and len(path) <= 512 and "\r" not in path and "\n" not in path:
        return
    raise InfraOpsValidationError("HTTP path must start with '/' and be at most 512 chars.")


def validate_http_host_header(host_header: str | None) -> None:
    if host_header is None:
        return
    if (
        1 <= len(host_header) <= 253
        and "\r" not in host_header
        and "\n" not in host_header
        and re.fullmatch(r"[A-Za-z0-9.*-]+(?:\.[A-Za-z0-9*-]+)*", host_header)
    ):
        return
    raise InfraOpsValidationError("Host header is invalid.")


def validate_optional_ingress_host(host: str | None) -> None:
    if host is None:
        return
    validate_http_host_header(host)


def validate_http_status_range(status_min: int, status_max: int) -> None:
    if 100 <= status_min <= status_max <= 599:
        return
    raise InfraOpsValidationError("Expected HTTP status range must be between 100 and 599.")


def summarize_endpoint_addresses(
    endpoints: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ready_addresses: list[dict[str, Any]] = []
    not_ready_addresses: list[dict[str, Any]] = []
    for subset in endpoints.get("subsets", []) or []:
        ports = subset.get("ports", []) or []
        for address in subset.get("addresses", []) or []:
            ready_addresses.append(summarize_endpoint_address(address, ports=ports))
        for address in subset.get("notReadyAddresses", []) or []:
            not_ready_addresses.append(summarize_endpoint_address(address, ports=ports))
    return ready_addresses, not_ready_addresses


def summarize_endpoint_address(
    address: dict[str, Any],
    *,
    ports: list[dict[str, Any]],
) -> dict[str, Any]:
    target_ref = address.get("targetRef") or {}
    return {
        key: value
        for key, value in {
            "ip": address.get("ip"),
            "node_name": address.get("nodeName"),
            "target_kind": target_ref.get("kind"),
            "target_name": target_ref.get("name"),
            "ports": ports,
        }.items()
        if value not in (None, [], {})
    }


def find_ingress_backend_rules(
    ingresses: list[dict[str, Any]],
    *,
    host: str | None,
    path: str | None,
    service_name: str | None,
) -> list[dict[str, Any]]:
    matched_rules = []
    for ingress in ingresses:
        ingress_name = ingress.get("metadata", {}).get("name")
        for rule in ingress.get("spec", {}).get("rules", []) or []:
            rule_host = rule.get("host")
            if host is not None and rule_host != host:
                continue
            http = rule.get("http") or {}
            for path_rule in http.get("paths", []) or []:
                backend_service = (
                    path_rule.get("backend", {}).get("service", {}).get("name")
                )
                path_value = path_rule.get("path")
                if service_name is not None and backend_service != service_name:
                    continue
                if path is not None and not ingress_path_matches(
                    request_path=path,
                    rule_path=path_value,
                    path_type=path_rule.get("pathType"),
                ):
                    continue
                matched_rules.append(
                    {
                        "ingress_name": ingress_name,
                        "host": rule_host,
                        "path": path_value,
                        "path_type": path_rule.get("pathType"),
                        "backend_service": backend_service,
                        "backend_port": path_rule.get("backend", {})
                        .get("service", {})
                        .get("port", {}),
                    }
                )
    return matched_rules


def ingress_path_matches(
    *,
    request_path: str,
    rule_path: str | None,
    path_type: str | None,
) -> bool:
    if not rule_path:
        return True
    if path_type == "Exact":
        return request_path == rule_path
    return request_path.startswith(rule_path.rstrip("/") or "/")


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


def clean_request_payload(**values: str | None) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def extract_traces_from_search_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    traces = response.get("traces")
    if isinstance(traces, list):
        return [trace for trace in traces if isinstance(trace, dict)]

    data = response.get("data")
    if isinstance(data, dict) and isinstance(data.get("traces"), list):
        return [trace for trace in data["traces"] if isinstance(trace, dict)]
    if isinstance(data, list):
        return [trace for trace in data if isinstance(trace, dict)]
    return []


def summarize_trace_durations(traces: list[dict[str, Any]]) -> dict[str, float | None]:
    durations = [
        duration
        for duration in (extract_trace_duration_ms(trace) for trace in traces)
        if duration is not None
    ]
    if not durations:
        return {"min": None, "max": None, "avg": None}
    return {
        "min": min(durations),
        "max": max(durations),
        "avg": sum(durations) / len(durations),
    }


def extract_trace_duration_ms(trace: dict[str, Any]) -> float | None:
    for key in ("durationMs", "duration_ms", "duration"):
        value = trace.get(key)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def count_error_traces(traces: list[dict[str, Any]]) -> int:
    return sum(contains_error_signal(trace) for trace in traces)


def contains_error_signal(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered_key = str(key).lower()
            if lowered_key in {"error", "errored"} and item is True:
                return True
            if lowered_key in {"status", "statuscode", "status_code"}:
                lowered_item = str(item).lower()
                if "error" in lowered_item or lowered_item in {"2", "500"}:
                    return True
            if contains_error_signal(item):
                return True
    if isinstance(value, list):
        return any(contains_error_signal(item) for item in value)
    if isinstance(value, str):
        return "status_code_error" in value.lower()
    return False


def extract_spans_from_trace_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for resource_span in iter_resource_span_groups(payload):
        resource_attributes = extract_attributes(resource_span.get("resource", {}))
        scope_span_groups = (
            resource_span.get("scopeSpans")
            or resource_span.get("instrumentationLibrarySpans")
            or []
        )
        for scope_span_group in scope_span_groups:
            for span in scope_span_group.get("spans", []):
                if isinstance(span, dict):
                    spans.append(normalize_span(span, resource_attributes))
    if spans:
        return spans

    raw_spans = payload.get("spans", [])
    if isinstance(raw_spans, list):
        return [
            normalize_span(span, {})
            for span in raw_spans
            if isinstance(span, dict)
        ]
    return []


def iter_resource_span_groups(payload: dict[str, Any]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for key in ("resourceSpans", "batches"):
        value = payload.get(key)
        if isinstance(value, list):
            groups.extend(item for item in value if isinstance(item, dict))

    data = payload.get("data")
    if isinstance(data, dict):
        groups.extend(iter_resource_span_groups(data))
    return groups


def normalize_span(
    span: dict[str, Any],
    resource_attributes: dict[str, Any],
) -> dict[str, Any]:
    attributes = extract_attributes(span)
    start_time = span.get("startTimeUnixNano")
    end_time = span.get("endTimeUnixNano")
    return {
        "trace_id": span.get("traceId") or span.get("traceID"),
        "span_id": span.get("spanId") or span.get("spanID"),
        "parent_span_id": span.get("parentSpanId") or span.get("parentSpanID"),
        "name": span.get("name"),
        "service_name": resource_attributes.get("service.name"),
        "start_time_unix_nano": start_time,
        "end_time_unix_nano": end_time,
        "duration_ms": calculate_span_duration_ms(start_time, end_time),
        "status": span.get("status"),
        "attributes": attributes,
        "resource_attributes": resource_attributes,
        "events": span.get("events") or [],
    }


def extract_attributes(source: dict[str, Any]) -> dict[str, Any]:
    attributes = source.get("attributes", [])
    if isinstance(attributes, dict):
        return attributes
    if not isinstance(attributes, list):
        return {}

    result: dict[str, Any] = {}
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        key = attribute.get("key")
        if not key:
            continue
        result[str(key)] = decode_otlp_value(attribute.get("value"))
    return result


def decode_otlp_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in (
        "stringValue",
        "intValue",
        "doubleValue",
        "boolValue",
        "arrayValue",
        "kvlistValue",
        "bytesValue",
    ):
        if key in value:
            return value[key]
    return value


def calculate_span_duration_ms(start_time: Any, end_time: Any) -> float | None:
    try:
        start = int(start_time)
        end = int(end_time)
    except (TypeError, ValueError):
        return None
    if end < start:
        return None
    return (end - start) / 1_000_000


def is_error_span(span: dict[str, Any]) -> bool:
    status = span.get("status")
    if isinstance(status, dict):
        code = status.get("code")
        if code in {2, "2", "STATUS_CODE_ERROR", "ERROR"}:
            return True
    elif str(status).upper() in {"2", "STATUS_CODE_ERROR", "ERROR"}:
        return True

    attributes = span.get("attributes", {})
    if attributes.get("error") is True:
        return True
    status_code = attributes.get("http.status_code") or attributes.get("http.response.status_code")
    try:
        if status_code is not None and int(status_code) >= 500:
            return True
    except (TypeError, ValueError):
        pass

    for event in span.get("events", []):
        if isinstance(event, dict) and "exception" in str(event.get("name", "")).lower():
            return True
    return False


def extract_desired_replicas(spec: dict[str, Any]) -> int:
    replicas = spec.get("replicas")
    if isinstance(replicas, bool):
        return 1
    if isinstance(replicas, int):
        return max(replicas, 0)
    return 1


def build_rollout_status_result(
    *,
    source: str,
    namespace: str,
    deployment_name: str,
    deployment: dict[str, Any],
) -> RolloutStatusResult:
    metadata = deployment.get("metadata", {})
    spec = deployment.get("spec", {})
    status = deployment.get("status", {})
    desired_replicas = extract_desired_replicas(spec)
    generation = metadata.get("generation")
    observed_generation = status.get("observedGeneration")
    updated_replicas = status.get("updatedReplicas") or 0
    ready_replicas = status.get("readyReplicas") or 0
    unavailable_replicas = status.get("unavailableReplicas") or 0

    rollout_status: Literal["HEALTHY", "PROGRESSING", "DEGRADED"] = "HEALTHY"
    if (
        isinstance(generation, int)
        and isinstance(observed_generation, int)
        and observed_generation < generation
    ):
        rollout_status = "PROGRESSING"
    elif updated_replicas < desired_replicas:
        rollout_status = "PROGRESSING"
    elif ready_replicas < desired_replicas or unavailable_replicas:
        rollout_status = "DEGRADED"

    return RolloutStatusResult(
        source=source,
        namespace=namespace,
        deployment_name=deployment_name,
        rollout_status=rollout_status,
        generation=generation,
        observed_generation=observed_generation,
        desired_replicas=desired_replicas,
        updated_replicas=updated_replicas,
        ready_replicas=ready_replicas,
        available_replicas=status.get("availableReplicas") or 0,
        unavailable_replicas=unavailable_replicas,
        conditions=status.get("conditions") or [],
        raw=deployment,
    )


def build_image_tag_items(deployments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for deployment in deployments:
        metadata = deployment.get("metadata", {})
        deployment_name = metadata.get("name")
        pod_spec = (
            deployment.get("spec", {})
            .get("template", {})
            .get("spec", {})
        )
        for container in pod_spec.get("containers", []):
            image = container.get("image", "")
            items.append(
                {
                    "deployment_name": deployment_name,
                    "container_name": container.get("name"),
                    **parse_image_reference(image),
                }
            )
    return items


def summarize_deployment_item(deployment: dict[str, Any]) -> dict[str, Any]:
    metadata = deployment.get("metadata", {})
    status = deployment.get("status", {})
    spec = deployment.get("spec", {})
    return {
        "deployment_name": metadata.get("name"),
        "created_at": metadata.get("creationTimestamp"),
        "generation": metadata.get("generation"),
        "desired_replicas": extract_desired_replicas(spec),
        "updated_replicas": status.get("updatedReplicas") or 0,
        "ready_replicas": status.get("readyReplicas") or 0,
        "available_replicas": status.get("availableReplicas") or 0,
        "images": [
            parse_image_reference(container.get("image", ""))
            for container in (
                deployment.get("spec", {})
                .get("template", {})
                .get("spec", {})
                .get("containers", [])
            )
        ],
    }


def parse_image_reference(image: str) -> dict[str, str | None]:
    image_without_digest, separator, digest = image.partition("@")
    last_segment = image_without_digest.rsplit("/", 1)[-1]
    repository = image_without_digest
    tag = None
    if ":" in last_segment:
        repository, tag = image_without_digest.rsplit(":", 1)
    return {
        "image": image,
        "repository": repository or None,
        "tag": tag,
        "digest": digest if separator else None,
    }


def clamp_kibana_per_page(per_page: int) -> int:
    if not isinstance(per_page, int) or isinstance(per_page, bool):
        raise InfraOpsValidationError("Kibana per_page must be an integer.")
    return min(max(per_page, 1), MAX_KIBANA_SAVED_OBJECTS_PER_PAGE)
