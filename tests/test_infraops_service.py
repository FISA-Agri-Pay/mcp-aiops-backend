import pytest

from aiops_platform.infraops.clients import (
    AlertmanagerClient,
    ArgoCdClient,
    AwsOpsClient,
    BatchClient,
    ElasticsearchClient,
    InfraOpsClientError,
    JsonHttpClient,
    KafkaAdminClient,
    KibanaClient,
    KubernetesClient,
    LokiClient,
    PrometheusClient,
    TempoClient,
)
from aiops_platform.infraops.service import (
    InfraOpsService,
    InfraOpsValidationError,
    capture_observability_source,
    clamp_kibana_per_page,
    parse_allowlist,
    parse_observability_source_urls,
    validate_index_pattern,
    validate_kubectl_exec_command,
    validate_kubernetes_resource_name,
    validate_namespace,
)


class FakeHttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.response

    def get_text(self, url, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self.response if isinstance(self.response, str) else ""

    def post_json(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.response


class FailingHttpClient:
    def get_json(self, url, **kwargs):
        raise InfraOpsClientError("source unavailable")

    def post_json(self, url, **kwargs):
        raise InfraOpsClientError("source unavailable")


def make_infraops_service(**overrides) -> InfraOpsService:
    dependencies = {
        "prometheus_client": PrometheusClient("http://prometheus:9090"),
        "loki_client": LokiClient("http://loki:3100"),
        "tempo_client": TempoClient("http://tempo:3200"),
        "kubernetes_client": KubernetesClient("http://kubernetes:8001"),
        "kafka_admin_client": KafkaAdminClient("http://kafka-admin:8080"),
        "batch_client": BatchClient("http://batch-api:8081"),
        "elasticsearch_client": ElasticsearchClient("http://elasticsearch:9200"),
        "kibana_client": KibanaClient("http://kibana:5601"),
        "kubernetes_namespace_allowlist": parse_allowlist("default,kube-system"),
        "elasticsearch_index_allowlist": parse_allowlist("logs-*,filebeat-*"),
    }
    dependencies.update(overrides)
    return InfraOpsService(**dependencies)


def test_prometheus_client_calls_instant_query_api() -> None:
    http_client = FakeHttpClient({"status": "success", "data": {"result": []}})
    client = PrometheusClient(
        "http://prometheus:9090",
        timeout_seconds=3,
        http_client=http_client,
    )

    assert client.query("up", time="2026-06-04T00:00:00Z") == {
        "status": "success",
        "data": {"result": []},
    }
    assert http_client.calls[0]["url"] == "http://prometheus:9090/api/v1/query"
    assert http_client.calls[0]["params"] == {
        "query": "up",
        "time": "2026-06-04T00:00:00Z",
    }
    assert http_client.calls[0]["timeout"] == 3


def test_loki_client_calls_query_range_api() -> None:
    http_client = FakeHttpClient({"status": "success", "data": {"result": []}})
    client = LokiClient(
        "http://loki:3100",
        timeout_seconds=3,
        http_client=http_client,
    )

    assert client.query_range("{app=\"api\"}", start="1", end="2", limit=50) == {
        "status": "success",
        "data": {"result": []},
    }
    assert http_client.calls[0]["url"] == "http://loki:3100/loki/api/v1/query_range"
    assert http_client.calls[0]["params"] == {
        "query": '{app="api"}',
        "start": "1",
        "end": "2",
        "limit": "50",
    }


def test_tempo_client_searches_traces_and_reads_trace_by_id() -> None:
    search_http_client = FakeHttpClient({"traces": [{"traceID": "abc"}]})
    search_client = TempoClient(
        "http://tempo:3200",
        timeout_seconds=3,
        http_client=search_http_client,
    )

    assert search_client.search(
        service_name="service-catalog",
        operation_name="POST /checkout",
        start="100",
        end="200",
        min_duration="100ms",
        limit=10,
    ) == {"traces": [{"traceID": "abc"}]}
    assert search_http_client.calls[0]["url"] == "http://tempo:3200/api/search"
    assert search_http_client.calls[0]["params"] == {
        "limit": "10",
        "tags": "service.name=service-catalog name=POST /checkout",
        "start": "100",
        "end": "200",
        "minDuration": "100ms",
    }

    trace_http_client = FakeHttpClient({"batches": []})
    trace_client = TempoClient(
        "http://tempo:3200",
        timeout_seconds=3,
        http_client=trace_http_client,
    )

    assert trace_client.trace("abc/123") == {"batches": []}
    assert trace_http_client.calls[0]["url"] == (
        "http://tempo:3200/api/traces/abc%2F123"
    )


def test_kubernetes_client_calls_namespaced_read_apis() -> None:
    http_client = FakeHttpClient({"items": []})
    client = KubernetesClient(
        "http://kubernetes:8001",
        bearer_token="token",
        timeout_seconds=3,
        http_client=http_client,
    )

    assert client.pods("default") == {"items": []}
    assert client.deployments("default") == {"items": []}
    assert client.hpa("default") == {"items": []}
    assert http_client.calls[0]["url"] == (
        "http://kubernetes:8001/api/v1/namespaces/default/pods"
    )
    assert http_client.calls[1]["url"] == (
        "http://kubernetes:8001/apis/apps/v1/namespaces/default/deployments"
    )
    assert http_client.calls[2]["url"] == (
        "http://kubernetes:8001/apis/autoscaling/v2/namespaces/default/"
        "horizontalpodautoscalers"
    )
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer token"


def test_kubernetes_client_reads_pod_logs_and_single_deployment() -> None:
    log_http_client = FakeHttpClient("line 1\nline 2\n")
    log_client = KubernetesClient(
        "http://kubernetes:8001",
        bearer_token="token",
        timeout_seconds=3,
        http_client=log_http_client,
    )

    assert log_client.pod_logs(
        "default",
        "api-123",
        container="api",
        since_seconds=60,
        tail_lines=10,
    ) == "line 1\nline 2\n"
    assert log_http_client.calls[0]["url"] == (
        "http://kubernetes:8001/api/v1/namespaces/default/pods/api-123/log"
    )
    assert log_http_client.calls[0]["params"] == {
        "tailLines": "10",
        "container": "api",
        "sinceSeconds": "60",
    }

    deployment_http_client = FakeHttpClient({"metadata": {"name": "api"}})
    deployment_client = KubernetesClient(
        "http://kubernetes:8001",
        http_client=deployment_http_client,
    )

    assert deployment_client.deployment("default", "api") == {"metadata": {"name": "api"}}
    assert deployment_http_client.calls[0]["url"] == (
        "http://kubernetes:8001/apis/apps/v1/namespaces/default/deployments/api"
    )


def test_kubernetes_client_creates_namespaced_job() -> None:
    http_client = FakeHttpClient({"metadata": {"name": "rca-job"}})
    client = KubernetesClient(
        "http://kubernetes:8001",
        bearer_token="token",
        timeout_seconds=3,
        http_client=http_client,
    )
    manifest = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": "rca-job"},
    }

    assert client.create_job("default", manifest) == {"metadata": {"name": "rca-job"}}
    assert http_client.calls[0]["method"] == "POST"
    assert http_client.calls[0]["url"] == (
        "http://kubernetes:8001/apis/batch/v1/namespaces/default/jobs"
    )
    assert http_client.calls[0]["json_body"] == manifest
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer token"


def test_kubernetes_client_reads_bearer_token_file(tmp_path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("file-token\n", encoding="utf-8")
    http_client = FakeHttpClient({"items": []})
    client = KubernetesClient(
        "https://kubernetes.default.svc",
        bearer_token_file=str(token_file),
        http_client=http_client,
    )

    assert client.pods("default") == {"items": []}
    assert http_client.calls[0]["headers"]["Authorization"] == "Bearer file-token"


def test_kubernetes_client_rejects_missing_service_account_files(tmp_path) -> None:
    with pytest.raises(InfraOpsClientError, match="bearer token file"):
        KubernetesClient(
            "https://kubernetes.default.svc",
            bearer_token_file=str(tmp_path / "missing-token"),
        )

    with pytest.raises(InfraOpsClientError, match="CA certificate file"):
        KubernetesClient(
            "https://kubernetes.default.svc",
            ca_cert_file=str(tmp_path / "missing-ca.crt"),
        )


def test_kafka_admin_client_calls_consumer_lag_api() -> None:
    http_client = FakeHttpClient({"total_lag": 3})
    client = KafkaAdminClient(
        "http://kafka-admin:8080",
        timeout_seconds=3,
        http_client=http_client,
    )

    assert client.consumer_lag("payments", topic="orders") == {"total_lag": 3}
    assert http_client.calls[0]["url"] == (
        "http://kafka-admin:8080/kafka/consumer-groups/payments/lag"
    )
    assert http_client.calls[0]["params"] == {"topic": "orders"}


def test_kafka_admin_client_encodes_consumer_group_path_segment() -> None:
    http_client = FakeHttpClient({"total_lag": 3})
    client = KafkaAdminClient(
        "http://kafka-admin:8080",
        http_client=http_client,
    )

    client.consumer_lag("team/a")

    assert http_client.calls[0]["url"] == (
        "http://kafka-admin:8080/kafka/consumer-groups/team%2Fa/lag"
    )


def test_alertmanager_client_calls_alerts_api() -> None:
    http_client = FakeHttpClient([{"labels": {"alertname": "HighErrorRate"}}])
    client = AlertmanagerClient(
        "http://alertmanager:9093",
        timeout_seconds=3,
        http_client=http_client,
    )

    assert client.alerts(active_only=True, severity="critical") == [
        {"labels": {"alertname": "HighErrorRate"}}
    ]
    assert http_client.calls[0]["url"] == "http://alertmanager:9093/api/v2/alerts"
    assert http_client.calls[0]["params"] == {
        "active": "true",
        "severity": "critical",
    }


def test_aws_and_argocd_read_clients_call_proxy_apis() -> None:
    aws_http_client = FakeHttpClient({"Attributes": {"ApproximateNumberOfMessages": "0"}})
    aws_client = AwsOpsClient(
        "http://ops-proxy:8080",
        timeout_seconds=3,
        http_client=aws_http_client,
    )

    assert aws_client.sqs_queue_attributes(
        queue_name="credit-payment-requested.fifo",
        region="ap-northeast-2",
    ) == {"Attributes": {"ApproximateNumberOfMessages": "0"}}
    assert aws_http_client.calls[0]["url"] == (
        "http://ops-proxy:8080/aws/sqs/queue-attributes"
    )
    assert aws_http_client.calls[0]["params"] == {
        "queue_name": "credit-payment-requested.fifo",
        "region": "ap-northeast-2",
    }

    argocd_http_client = FakeHttpClient({"sync": {"status": "Synced"}})
    argocd_client = ArgoCdClient(
        "http://ops-proxy:8080",
        timeout_seconds=3,
        http_client=argocd_http_client,
    )

    assert argocd_client.application_status(application_name="service-catalog") == {
        "sync": {"status": "Synced"}
    }
    assert argocd_http_client.calls[0]["url"] == (
        "http://ops-proxy:8080/argocd/application-status"
    )
    assert argocd_http_client.calls[0]["params"] == {
        "application_name": "service-catalog"
    }


def test_batch_client_calls_run_status_api() -> None:
    http_client = FakeHttpClient({"runs": []})
    client = BatchClient(
        "http://batch-api:8081",
        timeout_seconds=3,
        http_client=http_client,
    )

    assert client.run_status(job_name="daily-close") == {"runs": []}
    assert http_client.calls[0]["url"] == "http://batch-api:8081/batch/runs/status"
    assert http_client.calls[0]["params"] == {"job_name": "daily-close"}


def test_elasticsearch_client_calls_cluster_health_api() -> None:
    http_client = FakeHttpClient({"status": "green", "cluster_name": "local"})
    client = ElasticsearchClient(
        "http://elasticsearch:9200",
        username="elastic",
        password="secret",
        timeout_seconds=5,
        http_client=http_client,
    )

    assert client.cluster_health() == {"status": "green", "cluster_name": "local"}
    assert http_client.calls[0]["url"] == "http://elasticsearch:9200/_cluster/health"
    assert http_client.calls[0]["headers"]["Authorization"].startswith("Basic ")
    assert http_client.calls[0]["timeout"] == 5


def test_elasticsearch_client_calls_search_api() -> None:
    http_client = FakeHttpClient({"hits": {"hits": []}})
    client = ElasticsearchClient(
        "http://elasticsearch:9200",
        timeout_seconds=5,
        http_client=http_client,
    )

    assert client.search("logs-*", {"query": {"match_all": {}}}) == {
        "hits": {"hits": []},
    }
    assert http_client.calls[0]["method"] == "POST"
    assert http_client.calls[0]["url"] == "http://elasticsearch:9200/logs-*/_search"
    assert http_client.calls[0]["json_body"] == {"query": {"match_all": {}}}


def test_elasticsearch_client_encodes_index_pattern_path_segment() -> None:
    http_client = FakeHttpClient({"hits": {"hits": []}})
    client = ElasticsearchClient(
        "http://elasticsearch:9200",
        http_client=http_client,
    )

    client.search("logs api,*", {"query": {"match_all": {}}})

    assert http_client.calls[0]["url"] == (
        "http://elasticsearch:9200/logs%20api,*/_search"
    )


def test_kibana_client_calls_saved_objects_find_api() -> None:
    http_client = FakeHttpClient({"saved_objects": []})
    client = KibanaClient(
        "http://kibana:5601",
        timeout_seconds=5,
        http_client=http_client,
    )

    assert client.find_saved_objects("dashboard", search="api") == {
        "saved_objects": [],
    }
    assert http_client.calls[0]["url"] == "http://kibana:5601/api/saved_objects/_find"
    assert http_client.calls[0]["params"] == {
        "type": "dashboard",
        "per_page": "20",
        "search": "api",
    }


def test_json_http_client_rejects_non_http_url_scheme() -> None:
    with pytest.raises(InfraOpsClientError):
        JsonHttpClient().get_json("file:///etc/passwd")


def test_infraops_service_rejects_non_allowlisted_index_pattern() -> None:
    with pytest.raises(InfraOpsValidationError):
        validate_index_pattern("private-*", allowlist=("logs-*", "filebeat-*"))


def test_infraops_service_validates_comma_separated_index_patterns() -> None:
    validate_index_pattern("logs-*, filebeat-*", allowlist=("logs-*", "filebeat-*"))

    with pytest.raises(InfraOpsValidationError):
        validate_index_pattern("logs-*, private-*", allowlist=("logs-*", "filebeat-*"))


def test_infraops_service_rejects_index_pattern_path_separators() -> None:
    with pytest.raises(InfraOpsValidationError):
        validate_index_pattern("logs-*/private", allowlist=("logs-*", "filebeat-*"))


def test_infraops_service_rejects_non_allowlisted_namespace() -> None:
    with pytest.raises(InfraOpsValidationError):
        validate_namespace("prod", allowlist=("default", "kube-system"))


def test_infraops_service_rejects_invalid_kubernetes_resource_name() -> None:
    invalid_names = [
        "../api",
        "a..b",
        "a.-b",
        "a" * 64,
    ]

    for name in invalid_names:
        with pytest.raises(InfraOpsValidationError):
            validate_kubernetes_resource_name(name, resource="pod")


def test_infraops_service_rejects_invalid_kubectl_exec_command() -> None:
    with pytest.raises(InfraOpsValidationError):
        validate_kubectl_exec_command(["sh", ""])


def test_infraops_service_previews_ops_write_requests_without_execution() -> None:
    service = make_infraops_service()

    scale_preview = service.preview_scale_deployment(
        deployment_name="api",
        replicas=3,
        namespace="default",
    )
    restart_preview = service.preview_restart_pod(
        pod_name="api-123",
        namespace="default",
    )

    assert scale_preview.model_dump(mode="json") == {
        "action": "scale_deployment",
        "namespace": "default",
        "target_kind": "deployment",
        "target_name": "api",
        "request_payload": {
            "namespace": "default",
            "deployment_name": "api",
            "replicas": 3,
        },
        "dry_run": True,
        "safety_notes": [
            "Execution is blocked until administrator approval is implemented.",
            "No Kubernetes scale request was sent.",
        ],
    }
    assert restart_preview.dry_run is True
    assert restart_preview.action == "restart_pod"


def test_infraops_service_previews_destructive_requests_without_execution() -> None:
    service = make_infraops_service()

    delete_preview = service.preview_delete_pod(pod_name="api-123", namespace="default")
    exec_preview = service.preview_kubectl_exec(
        pod_name="api-123",
        command=["sh", "-c", "date"],
        namespace="default",
    )

    assert delete_preview.action == "delete_pod"
    assert delete_preview.dry_run is True
    assert exec_preview.request_payload["command"] == ["sh", "-c", "date"]
    assert exec_preview.safety_notes[0] == "Destructive exec tool execution is blocked by policy."


def test_infraops_service_maps_loki_query() -> None:
    service = make_infraops_service(
        loki_client=LokiClient(
            "http://loki:3100",
            http_client=FakeHttpClient({"status": "success", "data": {"result": []}}),
        ),
    )

    result = service.query_loki(query='{app="api"}', limit=50)

    assert result.status == "success"
    assert result.data == {"result": []}


def test_infraops_service_maps_multi_cluster_prometheus_partial_results() -> None:
    service = make_infraops_service(
        prometheus_sources=(
            (
                "onprem",
                PrometheusClient(
                    "http://onprem-prometheus:9090",
                    http_client=FakeHttpClient(
                        {"status": "success", "data": {"result": [{"value": 1}]}}
                    ),
                ),
            ),
            (
                "aws",
                PrometheusClient(
                    "http://aws-prometheus:9090",
                    http_client=FailingHttpClient(),
                ),
            ),
        ),
    )

    result = service.query_multi_cluster_prometheus(query="up")

    assert result.query == "up"
    assert result.partial is True
    assert [source.source for source in result.sources] == ["onprem", "aws"]
    assert result.sources[0].status == "SUCCESS"
    assert result.sources[0].data == {
        "status": "success",
        "data": {"result": [{"value": 1}]},
    }
    assert result.sources[1].status == "FAILED"
    assert result.sources[1].error == "loader failure: InfraOpsClientError"


def test_multi_cluster_source_capture_reraises_unexpected_errors() -> None:
    def broken_loader():
        raise RuntimeError("programming bug")

    with pytest.raises(RuntimeError, match="programming bug"):
        capture_observability_source("onprem", broken_loader)


def test_infraops_service_maps_multi_cluster_loki_results() -> None:
    service = make_infraops_service(
        loki_sources=(
            (
                "onprem",
                LokiClient(
                    "http://onprem-loki:3100",
                    http_client=FakeHttpClient(
                        {"status": "success", "data": {"result": []}}
                    ),
                ),
            ),
        ),
    )

    result = service.query_multi_cluster_loki(
        query='{app="api"}',
        start="1",
        end="2",
        limit=50,
    )

    assert result.partial is False
    assert result.limit == 50
    assert result.sources[0].source == "onprem"
    assert result.sources[0].data == {"status": "success", "data": {"result": []}}


def test_infraops_service_maps_tempo_trace_search_and_summary() -> None:
    response = {
        "traces": [
            {"traceID": "trace-1", "durationMs": 120, "status": "ok"},
            {"traceID": "trace-2", "durationMs": 250, "status": "error"},
        ]
    }
    service = make_infraops_service(
        tempo_client=TempoClient(
            "http://tempo:3200",
            http_client=FakeHttpClient(response),
        ),
    )

    search = service.search_traces(service_name="service-catalog", limit=2)
    summary = service.get_service_trace_summary(
        service_name="service-catalog",
        limit=2,
    )

    assert search.traces == response["traces"]
    assert search.query["service_name"] == "service-catalog"
    assert summary.trace_count == 2
    assert summary.error_trace_count == 1
    assert summary.duration_ms_summary == {
        "min": 120.0,
        "max": 250.0,
        "avg": 185.0,
    }


def test_infraops_service_extracts_trace_error_spans() -> None:
    trace = {
        "batches": [
            {
                "resource": {
                    "attributes": [
                        {
                            "key": "service.name",
                            "value": {"stringValue": "service-catalog"},
                        }
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "trace-1",
                                "spanId": "span-1",
                                "name": "POST /checkout",
                                "startTimeUnixNano": "1000000",
                                "endTimeUnixNano": "6000000",
                                "status": {"code": 2},
                                "attributes": [
                                    {
                                        "key": "http.status_code",
                                        "value": {"intValue": 500},
                                    }
                                ],
                            },
                            {
                                "traceId": "trace-1",
                                "spanId": "span-2",
                                "name": "SELECT product",
                                "status": {"code": 1},
                            },
                        ]
                    }
                ],
            }
        ]
    }
    service = make_infraops_service(
        tempo_client=TempoClient(
            "http://tempo:3200",
            http_client=FakeHttpClient(trace),
        ),
    )

    trace_result = service.get_trace_by_id("trace-1")
    errors = service.get_trace_error_spans("trace-1")

    assert trace_result.span_count == 2
    assert trace_result.error_span_count == 1
    assert errors.error_span_count == 1
    assert errors.error_spans[0]["name"] == "POST /checkout"
    assert errors.error_spans[0]["service_name"] == "service-catalog"
    assert errors.error_spans[0]["duration_ms"] == 5.0


def test_infraops_service_maps_kubernetes_resources() -> None:
    http_client = FakeHttpClient({"items": [{"metadata": {"name": "api-pod"}}]})
    service = make_infraops_service(
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=http_client,
        ),
    )

    result = service.get_k8s_pods(namespace="default")

    assert result.namespace == "default"
    assert result.items == [{"metadata": {"name": "api-pod"}}]
    assert http_client.calls[0]["url"] == (
        "http://kubernetes:8001/api/v1/namespaces/default/pods"
    )


def test_infraops_service_maps_pod_logs_and_rollout_status() -> None:
    log_http_client = FakeHttpClient("error line\n")
    log_service = make_infraops_service(
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=log_http_client,
        ),
    )

    logs = log_service.get_pod_logs(
        pod_name="api-123",
        namespace="default",
        tail_lines=10,
    )

    assert logs.logs == "error line\n"
    assert logs.tail_lines == 10
    assert log_http_client.calls[0]["url"] == (
        "http://kubernetes:8001/api/v1/namespaces/default/pods/api-123/log"
    )

    deployment = {
        "metadata": {"name": "api", "generation": 3},
        "spec": {"replicas": 2},
        "status": {
            "observedGeneration": 3,
            "updatedReplicas": 2,
            "readyReplicas": 2,
            "availableReplicas": 2,
            "conditions": [{"type": "Available", "status": "True"}],
        },
    }
    rollout_service = make_infraops_service(
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=FakeHttpClient(deployment),
        ),
    )

    rollout = rollout_service.get_rollout_status(
        deployment_name="api",
        namespace="default",
    )

    assert rollout.rollout_status == "HEALTHY"
    assert rollout.ready_replicas == 2
    assert rollout.conditions == [{"type": "Available", "status": "True"}]


def test_infraops_service_preserves_scale_to_zero_deployments() -> None:
    deployment = {
        "metadata": {
            "name": "worker",
            "creationTimestamp": "2026-06-11T02:00:00Z",
            "generation": 4,
        },
        "spec": {
            "replicas": 0,
            "template": {
                "spec": {
                    "containers": [
                        {"name": "worker", "image": "example.com/worker:v2"}
                    ]
                }
            },
        },
        "status": {
            "observedGeneration": 4,
            "updatedReplicas": 0,
            "readyReplicas": 0,
            "availableReplicas": 0,
            "unavailableReplicas": 0,
        },
    }
    rollout_service = make_infraops_service(
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=FakeHttpClient(deployment),
        ),
    )
    recent_service = make_infraops_service(
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=FakeHttpClient({"items": [deployment]}),
        ),
    )

    rollout = rollout_service.get_rollout_status(
        deployment_name="worker",
        namespace="default",
    )
    recent = recent_service.get_recent_deployments(namespace="default")

    assert rollout.rollout_status == "HEALTHY"
    assert rollout.desired_replicas == 0
    assert rollout.ready_replicas == 0
    assert recent.items[0]["desired_replicas"] == 0
    assert recent.items[0]["ready_replicas"] == 0
    assert recent.items[0]["available_replicas"] == 0


def test_infraops_service_maps_current_images_and_recent_deployments() -> None:
    deployments = {
        "items": [
            {
                "metadata": {
                    "name": "api",
                    "creationTimestamp": "2026-06-11T01:00:00Z",
                    "generation": 2,
                },
                "spec": {
                    "replicas": 2,
                    "template": {
                        "spec": {
                            "containers": [
                                {
                                    "name": "api",
                                    "image": "example.com/service-catalog:v1",
                                }
                            ]
                        }
                    },
                },
                "status": {"readyReplicas": 1, "updatedReplicas": 2},
            }
        ]
    }
    service = make_infraops_service(
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=FakeHttpClient(deployments),
        ),
    )

    images = service.get_current_image_tags(namespace="default")
    recent = service.get_recent_deployments(namespace="default")

    assert images.items == [
        {
            "deployment_name": "api",
            "container_name": "api",
            "image": "example.com/service-catalog:v1",
            "repository": "example.com/service-catalog",
            "tag": "v1",
            "digest": None,
        }
    ]
    assert recent.items[0]["deployment_name"] == "api"
    assert recent.items[0]["images"][0]["tag"] == "v1"


def test_infraops_service_returns_read_placeholders_for_unconfigured_external_tools() -> None:
    service = make_infraops_service()

    sqs = service.get_sqs_queue_attributes(queue_name="credit-payment-requested.fifo")
    argocd = service.get_argocd_application_status(application_name="service-catalog")

    assert sqs.source == "aws"
    assert sqs.resource == "sqs_queue_attributes"
    assert sqs.note == "AWS ops read proxy is not configured."
    assert argocd.source == "argocd"
    assert argocd.resource == "application_status"
    assert argocd.note == "ArgoCD read API is not configured."


def test_infraops_service_maps_alertmanager_alerts() -> None:
    service = make_infraops_service(
        alertmanager_client=AlertmanagerClient(
            "http://alertmanager:9093",
            http_client=FakeHttpClient(
                [
                    {"labels": {"alertname": "Checkout500", "severity": "critical"}},
                    {"labels": {"alertname": "InfoOnly", "severity": "info"}},
                ]
            ),
        )
    )

    result = service.get_alertmanager_alerts(active_only=True, limit=1)

    assert result.source == "alertmanager"
    assert result.raw_count == 2
    assert result.items == [
        {"labels": {"alertname": "Checkout500", "severity": "critical"}}
    ]


def test_infraops_service_maps_onprem_kubernetes_source() -> None:
    eks_http_client = FakeHttpClient({"items": []})
    onprem_http_client = FakeHttpClient({"items": [{"metadata": {"name": "onprem-pod"}}]})
    service = make_infraops_service(
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=eks_http_client,
        ),
        kubernetes_sources={
            "eks": (
                KubernetesClient("http://kubernetes:8001", http_client=eks_http_client),
                parse_allowlist("default,kube-system"),
            ),
            "onprem": (
                KubernetesClient(
                    "https://10.30.2.51:6443",
                    bearer_token="token",
                    http_client=onprem_http_client,
                ),
                parse_allowlist("kkpp,monitoring"),
            ),
        },
    )

    result = service.get_k8s_pods(namespace="kkpp", source="onprem")

    assert result.source == "onprem"
    assert result.namespace == "kkpp"
    assert result.items == [{"metadata": {"name": "onprem-pod"}}]
    assert onprem_http_client.calls[0]["url"] == (
        "https://10.30.2.51:6443/api/v1/namespaces/kkpp/pods"
    )


def test_infraops_service_rejects_unknown_kubernetes_source() -> None:
    service = make_infraops_service()

    with pytest.raises(InfraOpsValidationError, match="Kubernetes source"):
        service.get_k8s_pods(namespace="default", source="missing")


def test_infraops_service_maps_kafka_consumer_lag() -> None:
    service = make_infraops_service(
        kafka_admin_client=KafkaAdminClient(
            "http://kafka-admin:8080",
            http_client=FakeHttpClient({"total_lag": 3}),
        ),
    )

    result = service.get_kafka_consumer_lag("payments", topic="orders")

    assert result.consumer_group == "payments"
    assert result.topic == "orders"
    assert result.response == {"total_lag": 3}


def test_infraops_service_maps_batch_run_status() -> None:
    service = make_infraops_service(
        batch_client=BatchClient(
            "http://batch-api:8081",
            http_client=FakeHttpClient({"runs": []}),
        ),
    )

    result = service.get_batch_run_status(job_name="daily-close")

    assert result.job_name == "daily-close"
    assert result.response == {"runs": []}


def test_infraops_service_maps_elasticsearch_index_health() -> None:
    service = make_infraops_service(
        elasticsearch_client=ElasticsearchClient(
            "http://elasticsearch:9200",
            http_client=FakeHttpClient(
                [
                    {
                        "index": "logs-api-2026.06.04",
                        "health": "green",
                        "status": "open",
                        "docs.count": "10",
                        "store.size": "20kb",
                    }
                ]
            ),
        ),
    )

    result = service.get_elasticsearch_index_health("logs-*")

    assert result.model_dump(mode="json") == {
        "indices": [
            {
                "index": "logs-api-2026.06.04",
                "health": "green",
                "status": "open",
                "docs_count": "10",
                "store_size": "20kb",
            }
        ]
    }


def test_infraops_service_maps_elasticsearch_log_search() -> None:
    http_client = FakeHttpClient({"hits": {"hits": []}})
    service = make_infraops_service(
        elasticsearch_client=ElasticsearchClient(
            "http://elasticsearch:9200",
            http_client=http_client,
        ),
    )

    result = service.search_elasticsearch_logs(query="level:error", index_pattern="logs-*")

    assert result.index_pattern == "logs-*"
    assert result.response == {"hits": {"hits": []}}
    assert http_client.calls[0]["json_body"]["query"] == {
        "query_string": {"query": "level:error"},
    }


def test_infraops_service_clamps_kibana_saved_objects_per_page() -> None:
    http_client = FakeHttpClient({"saved_objects": []})
    service = make_infraops_service(
        kibana_client=KibanaClient("http://kibana:5601", http_client=http_client),
    )

    service.get_kibana_saved_objects(per_page=1000)
    service.get_kibana_saved_objects(per_page=0)

    assert http_client.calls[0]["params"]["per_page"] == "100"
    assert http_client.calls[1]["params"]["per_page"] == "1"


def test_infraops_service_creates_partial_rca_snapshot() -> None:
    service = make_infraops_service(
        prometheus_client=PrometheusClient(
            "http://prometheus:9090",
            http_client=FakeHttpClient({"status": "success", "data": {"result": []}}),
        ),
        loki_client=LokiClient(
            "http://loki:3100",
            http_client=FakeHttpClient({"status": "success", "data": {"result": []}}),
        ),
        elasticsearch_client=ElasticsearchClient(
            "http://elasticsearch:9200",
            http_client=FailingHttpClient(),
        ),
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=FakeHttpClient({"items": []}),
        ),
        batch_client=BatchClient(
            "http://batch-api:8081",
            http_client=FakeHttpClient({"runs": []}),
        ),
    )

    result = service.create_rca_snapshot(incident_key="INC-1", namespace="default")

    assert result.incident_key == "INC-1"
    assert result.partial is True
    assert {source.source: source.status for source in result.sources} == {
        "prometheus": "SUCCESS",
        "loki": "SUCCESS",
        "elasticsearch": "FAILED",
        "kubernetes": "SUCCESS",
        "kafka": "SKIPPED",
        "batch": "SKIPPED",
    }

    enriched = service.create_rca_snapshot(
        incident_key="INC-1",
        namespace="default",
        context_bundle={"schema_version": "incident_context_bundle.v1"},
    )
    sources = {source.source: source for source in enriched.sources}
    assert sources["incident_context_bundle"].status == "SUCCESS"
    assert sources["incident_context_bundle"].data == {
        "schema_version": "incident_context_bundle.v1"
    }


def test_infraops_service_aggregates_daily_ops_metrics() -> None:
    service = make_infraops_service(
        prometheus_client=PrometheusClient(
            "http://prometheus:9090",
            http_client=FakeHttpClient({"status": "success", "data": {"result": []}}),
        ),
        loki_client=LokiClient(
            "http://loki:3100",
            http_client=FakeHttpClient({"status": "success", "data": {"result": []}}),
        ),
        elasticsearch_client=ElasticsearchClient(
            "http://elasticsearch:9200",
            http_client=FailingHttpClient(),
        ),
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=FakeHttpClient({"items": [{"metadata": {"name": "api"}}]}),
        ),
        batch_client=BatchClient(
            "http://batch-api:8081",
            http_client=FakeHttpClient({"runs": []}),
        ),
    )

    result = service.aggregate_daily_ops_metrics(
        report_date="2026-06-05",
        namespace="default",
    )

    assert result.report_date == "2026-06-05"
    assert result.partial is True
    assert result.metrics == {
        "successful_sources": 3,
        "failed_sources": 2,
        "skipped_sources": 2,
        "pod_count": 1,
        "event_count": 1,
        "deployment_count": 1,
        "hpa_count": 1,
    }
    assert {source.source for source in result.sources} >= {"prometheus", "loki"}


def test_infraops_service_skips_elasticsearch_when_disabled_but_keeps_loki() -> None:
    service = make_infraops_service(
        prometheus_client=PrometheusClient(
            "http://prometheus:9090",
            http_client=FakeHttpClient({"status": "success", "data": {"result": []}}),
        ),
        loki_client=LokiClient(
            "http://loki:3100",
            http_client=FakeHttpClient({"status": "success", "data": {"result": []}}),
        ),
        elasticsearch_client=ElasticsearchClient(
            "http://elasticsearch:9200",
            http_client=FailingHttpClient(),
        ),
        kubernetes_client=KubernetesClient(
            "http://kubernetes:8001",
            http_client=FakeHttpClient({"items": []}),
        ),
        batch_client=BatchClient(
            "http://batch-api:8081",
            http_client=FakeHttpClient({"runs": []}),
        ),
        elasticsearch_enabled=False,
    )

    result = service.aggregate_daily_ops_metrics(report_date="2026-06-05")

    statuses = {source.source: source.status for source in result.sources}
    assert statuses["loki"] == "SUCCESS"
    assert statuses["elasticsearch_cluster"] == "SKIPPED"
    assert statuses["elasticsearch_indices"] == "SKIPPED"


def test_infraops_service_returns_search_skeletons() -> None:
    service = make_infraops_service()

    incidents = service.search_incidents(query="payment", limit=1000)
    history = service.search_rca_history(query="latency", limit=0)

    assert incidents.limit == 100
    assert incidents.items == []
    assert incidents.source == "incidents"
    assert history.limit == 1
    assert history.items == []
    assert history.source == "rca_history"


def test_kibana_per_page_rejects_non_integer_values() -> None:
    with pytest.raises(InfraOpsValidationError):
        clamp_kibana_per_page("20")  # type: ignore[arg-type]


def test_observability_source_url_parser_supports_named_and_default_sources() -> None:
    assert parse_observability_source_urls(
        "",
        default_name="default",
        default_url="http://prometheus:9090",
    ) == (("default", "http://prometheus:9090"),)
    assert parse_observability_source_urls(
        "onprem=http://prometheus:9090,aws=http://aws-prometheus:9090",
        default_name="default",
        default_url="http://prometheus:9090",
    ) == (
        ("onprem", "http://prometheus:9090"),
        ("aws", "http://aws-prometheus:9090"),
    )
    assert parse_observability_source_urls(
        "http://prometheus:9090/api/v1?tenant=a",
        default_name="default",
        default_url="http://prometheus:9090",
    ) == (("source-1", "http://prometheus:9090/api/v1?tenant=a"),)


def test_observability_source_url_parser_rejects_invalid_sources() -> None:
    with pytest.raises(InfraOpsValidationError, match="must be http or https"):
        parse_observability_source_urls(
            "bad source=http://prometheus:9090",
            default_name="default",
            default_url="http://prometheus:9090",
        )

    with pytest.raises(InfraOpsValidationError, match="source names must be unique"):
        parse_observability_source_urls(
            "aws=http://a,AWS=http://b",
            default_name="default",
            default_url="http://prometheus:9090",
        )

    with pytest.raises(InfraOpsValidationError, match="must be http or https"):
        parse_observability_source_urls(
            "aws=file:///etc/passwd",
            default_name="default",
            default_url="http://prometheus:9090",
        )

    with pytest.raises(InfraOpsValidationError, match="must be http or https"):
        parse_observability_source_urls(
            "",
            default_name="default",
            default_url="localhost:9090",
        )
