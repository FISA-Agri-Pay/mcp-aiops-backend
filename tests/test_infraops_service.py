import pytest

from aiops_platform.infraops.clients import (
    ElasticsearchClient,
    InfraOpsClientError,
    JsonHttpClient,
    PrometheusClient,
)
from aiops_platform.infraops.service import (
    InfraOpsService,
    InfraOpsValidationError,
    parse_allowlist,
    validate_index_pattern,
)


class FakeHttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


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


def test_json_http_client_rejects_non_http_url_scheme() -> None:
    with pytest.raises(InfraOpsClientError):
        JsonHttpClient().get_json("file:///etc/passwd")


def test_infraops_service_rejects_non_allowlisted_index_pattern() -> None:
    with pytest.raises(InfraOpsValidationError):
        validate_index_pattern("private-*", allowlist=("logs-*", "filebeat-*"))


def test_infraops_service_maps_elasticsearch_index_health() -> None:
    service = InfraOpsService(
        prometheus_client=PrometheusClient("http://prometheus:9090"),
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
        elasticsearch_index_allowlist=parse_allowlist("logs-*,filebeat-*"),
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
