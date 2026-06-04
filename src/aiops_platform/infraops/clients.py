from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
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
    ) -> Any:
        request_url = url
        if params:
            request_url = f"{url}?{urlencode(params)}"

        scheme = urlparse(request_url).scheme
        if scheme not in {"http", "https"}:
            raise InfraOpsClientError(f"Unsupported URL scheme for {request_url}")

        request = Request(request_url, headers=dict(headers or {}), method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise InfraOpsClientError(f"HTTP {exc.code} from {request_url}: {detail}") from exc
        except URLError as exc:
            raise InfraOpsClientError(f"Failed to call {request_url}: {exc.reason}") from exc

        if not body:
            return {}

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise InfraOpsClientError(f"Invalid JSON from {request_url}") from exc


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
        return self._http_client.get_json(
            urljoin(self._base_url, f"_cat/indices/{index_pattern}"),
            params={
                "format": "json",
                "h": "index,health,status,docs.count,store.size",
            },
            headers=self._headers,
            timeout=self._timeout_seconds,
        )

    @staticmethod
    def _build_headers(username: str, password: str) -> dict[str, str]:
        if not username:
            return {}

        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        return {"Authorization": f"Basic {token}"}
