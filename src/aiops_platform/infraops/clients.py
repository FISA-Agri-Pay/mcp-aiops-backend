from __future__ import annotations

import base64
import json
import ssl
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


class InfraOpsClientError(RuntimeError):
    pass


class JsonHttpClient:
    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> Any:
        return self._request_json(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            ssl_context=ssl_context,
        )

    def post_json(
        self,
        url: str,
        *,
        json_body: Mapping[str, Any],
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> Any:
        request_headers = {"Content-Type": "application/json", **dict(headers or {})}
        return self._request_json(
            "POST",
            url,
            params=params,
            headers=request_headers,
            timeout=timeout,
            data=json.dumps(json_body).encode("utf-8"),
            ssl_context=ssl_context,
        )

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        ssl_context: ssl.SSLContext | None = None,
    ) -> str:
        return self._request_text(
            "GET",
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            ssl_context=ssl_context,
        )

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        data: bytes | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> Any:
        body = self._request_text(
            method,
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            data=data,
            ssl_context=ssl_context,
        )

        if not body:
            return {}

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise InfraOpsClientError(f"Invalid JSON from {url}") from exc

    def _request_text(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        data: bytes | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> str:
        request_url = url
        if params:
            request_url = f"{url}?{urlencode(params)}"

        scheme = urlparse(request_url).scheme
        if scheme not in {"http", "https"}:
            raise InfraOpsClientError(f"Unsupported URL scheme for {request_url}")

        request = Request(
            request_url,
            data=data,
            headers=dict(headers or {}),
            method=method,
        )
        try:
            with urlopen(request, timeout=timeout, context=ssl_context) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise InfraOpsClientError(f"HTTP {exc.code} from {request_url}: {detail}") from exc
        except URLError as exc:
            raise InfraOpsClientError(f"Failed to call {request_url}: {exc.reason}") from exc

        return body


class PrometheusClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    def query(self, query: str, time: str | None = None) -> dict[str, Any]:
        params = {"query": query}
        if time is not None:
            params["time"] = time

        return self._http_client.get_json(
            urljoin(self._base_url, "api/v1/query"),
            params=params,
            timeout=self._timeout_seconds,
        )


class LokiClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    def query_range(
        self,
        query: str,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params = {"query": query, "limit": str(limit)}
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end

        return self._http_client.get_json(
            urljoin(self._base_url, "loki/api/v1/query_range"),
            params=params,
            timeout=self._timeout_seconds,
        )


class TempoClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/" if base_url else ""
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    def search(
        self,
        *,
        traceql: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        start: str | None = None,
        end: str | None = None,
        min_duration: str | None = None,
        max_duration: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise InfraOpsClientError("Tempo base URL is not configured.")

        params = {"limit": str(limit)}
        if traceql:
            params["q"] = traceql
        else:
            tags = build_tempo_search_tags(
                service_name=service_name,
                operation_name=operation_name,
            )
            if tags:
                params["tags"] = tags
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if min_duration is not None:
            params["minDuration"] = min_duration
        if max_duration is not None:
            params["maxDuration"] = max_duration

        return self._http_client.get_json(
            urljoin(self._base_url, "api/search"),
            params=params,
            timeout=self._timeout_seconds,
        )

    def trace(self, trace_id: str) -> dict[str, Any]:
        if not self.is_configured:
            raise InfraOpsClientError("Tempo base URL is not configured.")
        encoded_trace_id = quote(trace_id, safe="")
        return self._http_client.get_json(
            urljoin(self._base_url, f"api/traces/{encoded_trace_id}"),
            timeout=self._timeout_seconds,
        )


def build_tempo_search_tags(
    *,
    service_name: str | None,
    operation_name: str | None,
) -> str:
    tags = []
    if service_name:
        tags.append(f"service.name={service_name}")
    if operation_name:
        tags.append(f"name={operation_name}")
    return " ".join(tags)


class AlertmanagerClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/" if base_url else ""
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    def alerts(
        self,
        *,
        active_only: bool = True,
        receiver: str | None = None,
        alertname: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_configured:
            raise InfraOpsClientError("Alertmanager base URL is not configured.")

        params = {"active": str(active_only).lower()}
        if receiver is not None:
            params["receiver"] = receiver
        if alertname is not None:
            params["alertname"] = alertname
        if severity is not None:
            params["severity"] = severity

        response = self._http_client.get_json(
            urljoin(self._base_url, "api/v2/alerts"),
            params=params,
            timeout=self._timeout_seconds,
        )
        return response if isinstance(response, list) else response.get("alerts", [])


class KubernetesClient:
    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str = "",
        bearer_token_file: str = "",
        ca_cert_file: str = "",
        ca_cert_data: str = "",
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()
        self._headers = self._build_headers(
            bearer_token=self._resolve_bearer_token(
                bearer_token=bearer_token,
                bearer_token_file=bearer_token_file,
            )
        )
        self._ssl_context = self._build_ssl_context(ca_cert_file, ca_cert_data)

    def pods(self, namespace: str) -> dict[str, Any]:
        return self._get_namespaced_resource(namespace, "pods")

    def events(self, namespace: str) -> dict[str, Any]:
        return self._get_namespaced_resource(namespace, "events")

    def deployments(self, namespace: str) -> dict[str, Any]:
        return self._http_client.get_json(
            urljoin(self._base_url, f"apis/apps/v1/namespaces/{namespace}/deployments"),
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def hpa(self, namespace: str) -> dict[str, Any]:
        return self._http_client.get_json(
            urljoin(
                self._base_url,
                f"apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers",
            ),
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def service(self, namespace: str, service_name: str) -> dict[str, Any]:
        encoded_service_name = quote(service_name, safe="")
        return self._http_client.get_json(
            urljoin(
                self._base_url,
                f"api/v1/namespaces/{namespace}/services/{encoded_service_name}",
            ),
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def endpoints(self, namespace: str, service_name: str) -> dict[str, Any]:
        encoded_service_name = quote(service_name, safe="")
        return self._http_client.get_json(
            urljoin(
                self._base_url,
                f"api/v1/namespaces/{namespace}/endpoints/{encoded_service_name}",
            ),
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def ingresses(self, namespace: str) -> dict[str, Any]:
        return self._http_client.get_json(
            urljoin(
                self._base_url,
                f"apis/networking.k8s.io/v1/namespaces/{namespace}/ingresses",
            ),
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def deployment(self, namespace: str, deployment_name: str) -> dict[str, Any]:
        encoded_deployment_name = quote(deployment_name, safe="")
        return self._http_client.get_json(
            urljoin(
                self._base_url,
                f"apis/apps/v1/namespaces/{namespace}/deployments/{encoded_deployment_name}",
            ),
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def pod_logs(
        self,
        namespace: str,
        pod_name: str,
        *,
        container: str | None = None,
        since_seconds: int | None = None,
        tail_lines: int = 200,
    ) -> str:
        encoded_pod_name = quote(pod_name, safe="")
        params = {"tailLines": str(tail_lines)}
        if container is not None:
            params["container"] = container
        if since_seconds is not None:
            params["sinceSeconds"] = str(since_seconds)
        return self._http_client.get_text(
            urljoin(
                self._base_url,
                f"api/v1/namespaces/{namespace}/pods/{encoded_pod_name}/log",
            ),
            params=params,
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def create_job(self, namespace: str, job_manifest: Mapping[str, Any]) -> dict[str, Any]:
        return self._http_client.post_json(
            urljoin(self._base_url, f"apis/batch/v1/namespaces/{namespace}/jobs"),
            json_body=job_manifest,
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    def _get_namespaced_resource(self, namespace: str, resource: str) -> dict[str, Any]:
        return self._http_client.get_json(
            urljoin(self._base_url, f"api/v1/namespaces/{namespace}/{resource}"),
            headers=self._headers,
            timeout=self._timeout_seconds,
            ssl_context=self._ssl_context,
        )

    @staticmethod
    def _resolve_bearer_token(*, bearer_token: str, bearer_token_file: str) -> str:
        if bearer_token:
            return bearer_token
        if not bearer_token_file:
            return ""

        try:
            return Path(bearer_token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise InfraOpsClientError(
                f"Failed to read Kubernetes bearer token file: {bearer_token_file}"
            ) from exc

    @staticmethod
    def _build_headers(bearer_token: str) -> dict[str, str]:
        if not bearer_token:
            return {}
        return {"Authorization": f"Bearer {bearer_token}"}

    @staticmethod
    def _build_ssl_context(ca_cert_file: str, ca_cert_data: str = "") -> ssl.SSLContext | None:
        if ca_cert_data:
            return ssl.create_default_context(cadata=ca_cert_data)
        if not ca_cert_file:
            return None
        try:
            return ssl.create_default_context(cafile=ca_cert_file)
        except OSError as exc:
            raise InfraOpsClientError(
                f"Failed to read Kubernetes CA certificate file: {ca_cert_file}"
            ) from exc


class KafkaAdminClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    def consumer_lag(
        self,
        consumer_group: str,
        topic: str | None = None,
    ) -> dict[str, Any]:
        params = {}
        if topic is not None:
            params["topic"] = topic
        encoded_consumer_group = quote(consumer_group, safe="")
        return self._http_client.get_json(
            urljoin(self._base_url, f"kafka/consumer-groups/{encoded_consumer_group}/lag"),
            params=params,
            timeout=self._timeout_seconds,
        )


class BatchClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    def run_status(self, job_name: str | None = None) -> dict[str, Any]:
        params = {}
        if job_name is not None:
            params["job_name"] = job_name
        return self._http_client.get_json(
            urljoin(self._base_url, "batch/runs/status"),
            params=params,
            timeout=self._timeout_seconds,
        )


class AwsOpsClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/" if base_url else ""
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    def sqs_queue_attributes(self, **params: str) -> dict[str, Any]:
        return self._get("aws/sqs/queue-attributes", params=params)

    def sqs_dlq_attributes(self, **params: str) -> dict[str, Any]:
        return self._get("aws/sqs/dlq-attributes", params=params)

    def alb_target_health(self, **params: str) -> dict[str, Any]:
        return self._get("aws/alb/target-health", params=params)

    def cloudfront_origin_mapping(self, **params: str) -> dict[str, Any]:
        return self._get("aws/cloudfront/origin-mapping", params=params)

    def cloudfront_distribution_status(self, **params: str) -> dict[str, Any]:
        return self._get("aws/cloudfront/distribution-status", params=params)

    def _get(self, path: str, *, params: Mapping[str, str]) -> dict[str, Any]:
        if not self.is_configured:
            raise InfraOpsClientError("AWS ops read proxy base URL is not configured.")
        return self._http_client.get_json(
            urljoin(self._base_url, path),
            params={key: value for key, value in params.items() if value},
            timeout=self._timeout_seconds,
        )


class ArgoCdClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/" if base_url else ""
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url)

    def application_status(
        self,
        *,
        application_name: str,
        project: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_configured:
            raise InfraOpsClientError("ArgoCD read API base URL is not configured.")
        params = {"application_name": application_name}
        if project is not None:
            params["project"] = project
        return self._http_client.get_json(
            urljoin(self._base_url, "argocd/application-status"),
            params=params,
            timeout=self._timeout_seconds,
        )


class ElasticsearchClient:
    def __init__(
        self,
        base_url: str,
        *,
        username: str = "",
        password: str = "",
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()
        self._headers = self._build_headers(username=username, password=password)

    def cluster_health(self) -> dict[str, Any]:
        return self._http_client.get_json(
            urljoin(self._base_url, "_cluster/health"),
            headers=self._headers,
            timeout=self._timeout_seconds,
        )

    def index_health(self, index_pattern: str) -> list[dict[str, Any]]:
        encoded_index_pattern = quote(index_pattern, safe="*,")
        return self._http_client.get_json(
            urljoin(self._base_url, f"_cat/indices/{encoded_index_pattern}"),
            params={
                "format": "json",
                "h": "index,health,status,docs.count,store.size",
            },
            headers=self._headers,
            timeout=self._timeout_seconds,
        )

    def search(self, index_pattern: str, query: Mapping[str, Any]) -> dict[str, Any]:
        encoded_index_pattern = quote(index_pattern, safe="*,")
        return self._http_client.post_json(
            urljoin(self._base_url, f"{encoded_index_pattern}/_search"),
            json_body=query,
            headers=self._headers,
            timeout=self._timeout_seconds,
        )

    @staticmethod
    def _build_headers(username: str, password: str) -> dict[str, str]:
        if not username:
            return {}

        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}"}


class KibanaClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        http_client: JsonHttpClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client or JsonHttpClient()

    def find_saved_objects(
        self,
        saved_object_type: str,
        *,
        search: str | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        params = {
            "type": saved_object_type,
            "per_page": str(per_page),
        }
        if search:
            params["search"] = search

        return self._http_client.get_json(
            urljoin(self._base_url, "api/saved_objects/_find"),
            params=params,
            timeout=self._timeout_seconds,
        )
