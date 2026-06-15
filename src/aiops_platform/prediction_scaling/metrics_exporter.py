from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import Request, urlopen


class MetricsExporterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportedMetricValue:
    metric_name: str
    namespace: str
    service: str
    value: float
    labels: dict[str, str]


METRIC_NAME_BY_PROMETHEUS_NAME = {
    "aiops_predicted_rps": "predicted_rps",
    "aiops_predicted_pods": "predicted_pods",
    "aiops_base_pods": "base_pods",
    "aiops_extra_demand": "extra_demand",
    "aiops_allocation_score": "allocation_score",
    "aiops_onprem_adjusted_pods": "onprem_adjusted_pods",
}
GENERIC_METRIC_NAME = "aiops_prediction_metric_value"
METRIC_LINE_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
)
LABEL_PATTERN = re.compile(r'(?P<key>[A-Za-z_][A-Za-z0-9_]*)="(?P<value>(?:\\.|[^"])*)"')


class MetricsExporterClient:
    def __init__(self, url: str, *, timeout_seconds: float = 5.0) -> None:
        self._url = url
        self._timeout_seconds = timeout_seconds

    def read_metrics(self) -> str:
        if not self._url:
            return ""
        request = Request(self._url, method="GET")
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except URLError as exc:
            raise MetricsExporterError("failed to read predictive metrics exporter") from exc


def parse_predictive_metrics(text: str) -> dict[tuple[str, str, str], ExportedMetricValue]:
    values: dict[tuple[str, str, str], ExportedMetricValue] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = METRIC_LINE_PATTERN.match(line)
        if match is None:
            continue
        prometheus_name = match.group("name")
        labels = parse_labels(match.group("labels") or "")
        metric_name = resolve_metric_name(prometheus_name, labels)
        namespace = labels.get("namespace")
        service = labels.get("service")
        if metric_name is None or not namespace or not service:
            continue
        values[(namespace, service, metric_name)] = ExportedMetricValue(
            metric_name=metric_name,
            namespace=namespace,
            service=service,
            value=float(match.group("value")),
            labels=labels,
        )
    return values


def parse_labels(raw_labels: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    for match in LABEL_PATTERN.finditer(raw_labels):
        labels[match.group("key")] = unescape_label_value(match.group("value"))
    return labels


def resolve_metric_name(prometheus_name: str, labels: dict[str, str]) -> str | None:
    if prometheus_name == GENERIC_METRIC_NAME:
        return labels.get("metric_name")
    return METRIC_NAME_BY_PROMETHEUS_NAME.get(prometheus_name)


def unescape_label_value(value: str) -> str:
    return value.replace(r"\\", "\\").replace(r"\"", '"').replace(r"\n", "\n")
