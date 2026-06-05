import pytest

from aiops_platform.infraops.clients import (
    BatchClient,
    ElasticsearchClient,
    InfraOpsClientError,
    JsonHttpClient,
    KafkaAdminClient,
    KibanaClient,
    KubernetesClient,
    LokiClient,
    PrometheusClient,
)
from aiops_platform.infraops.service import (
    InfraOpsService,
    InfraOpsValidationError,
    clamp_kibana_per_page,
    parse_allowlist,
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

    def post_json(self, url, **kwargs):
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self.response


def make_infraops_service(**overrides) -> InfraOpsService:
    dependencies = {
        "prometheus_client": PrometheusClient("http://prometheus:9090"),
        "loki_client": LokiClient("http://loki:3100"),
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
    with pytest.raises(InfraOpsValidationError):
        validate_kubernetes_resource_name("../api", resource="pod")


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


def test_kibana_per_page_rejects_non_integer_values() -> None:
    with pytest.raises(InfraOpsValidationError):
        clamp_kibana_per_page("20")  # type: ignore[arg-type]
