from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from aiops_platform.core.config import settings
from aiops_platform.infraops.service import InfraOpsService
from aiops_platform.prediction_scaling.metrics_exporter import (
    ExportedMetricValue,
    MetricsExporterClient,
    MetricsExporterError,
    parse_predictive_metrics,
)
from aiops_platform.prediction_scaling.repository import (
    PredictionScalingRepository,
    SqlPredictionScalingRepository,
)
from aiops_platform.prediction_scaling.schemas import (
    ActualMetricItem,
    ActualMetricResult,
    LatestPredictionResult,
    ModelVersionListResult,
    ModelVersionResult,
    PredictionErrorItem,
    PredictionErrorMetricsResult,
    PredictionErrorResult,
    PredictionMetricPoint,
    PredictionMetricResult,
    PredictionRunListResult,
    PredictionRunResult,
    PredictionSnapshotResult,
    PredictiveMetricValue,
    PredictiveScalingStatusItem,
    PredictiveScalingStatusResult,
    ScalingAnalysisSnapshotResult,
    ScalingEventItem,
    ScalingEventResult,
    ScalingSummaryResult,
)


class PredictionScalingValidationError(ValueError):
    pass


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
METRIC_NAME_PATTERN = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]{0,119}$")
MAX_SEARCH_LIMIT = settings.prediction_scaling_max_search_limit
PREDICTIVE_METRIC_NAMES = (
    "predicted_rps",
    "predicted_pods",
    "base_pods",
    "extra_demand",
    "allocation_score",
    "onprem_adjusted_pods",
)
PREDICTIVE_SERVICE_MAP = {
    "service-payment": "payment",
    "service-core": "core",
    "service-auth": "auth",
    "service-admin": "admin",
}
SHORT_SERVICE_TO_WORKLOAD = {
    short_service: workload
    for workload, short_service in PREDICTIVE_SERVICE_MAP.items()
}


class PredictiveMetricsReader(Protocol):
    def read_metrics(self) -> str:
        pass


class PredictiveKubernetesReader(Protocol):
    def get_k8s_deployments(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ):
        pass

    def get_k8s_hpa(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ):
        pass

    def get_k8s_scaled_objects(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ):
        pass


class PredictionScalingService:
    def __init__(
        self,
        repository: PredictionScalingRepository | None = None,
        metrics_reader: PredictiveMetricsReader | None = None,
        kubernetes_reader: PredictiveKubernetesReader | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository or SqlPredictionScalingRepository()
        self._metrics_reader = metrics_reader or MetricsExporterClient(
            settings.prediction_scaling_metrics_exporter_url,
            timeout_seconds=settings.prediction_scaling_metrics_timeout_seconds,
        )
        self._kubernetes_reader = kubernetes_reader or InfraOpsService.from_settings()
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def _list_model_versions(
        self,
        *,
        service_name: str | None = None,
        limit: int = 20,
    ) -> list[ModelVersionResult]:
        return self._repository.list_model_versions(service_name=service_name, limit=limit)[:limit]

    def _list_prediction_runs(
        self,
        *,
        model_version_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[PredictionRunResult]:
        return self._repository.list_prediction_runs(
            model_version_id=model_version_id,
            status=status,
            limit=limit,
        )[:limit]

    def _list_prediction_points(
        self,
        *,
        prediction_run_id: str,
        metric_name: str | None = None,
    ) -> list[PredictionMetricPoint]:
        return self._repository.list_prediction_points(
            prediction_run_id=prediction_run_id,
            metric_name=metric_name,
        )

    def _list_actual_metrics(
        self,
        *,
        metric_name: str,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> list[ActualMetricItem]:
        return self._repository.list_actual_metrics(
            metric_name=metric_name,
            namespace=namespace,
            workload=workload,
            limit=limit,
        )[:limit]

    def _list_scaling_events(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> list[ScalingEventItem]:
        return self._repository.list_scaling_events(
            namespace=namespace,
            workload=workload,
            limit=limit,
        )[:limit]

    def get_model_versions(
        self,
        *,
        service_name: str | None = None,
        limit: int = 20,
    ) -> ModelVersionListResult:
        clamped_limit = clamp_limit(limit)
        normalized_service = normalize_optional_identifier(service_name, field_name="service_name")
        return ModelVersionListResult(
            service_name=normalized_service,
            limit=clamped_limit,
            items=self._list_model_versions(
                service_name=normalized_service,
                limit=clamped_limit,
            ),
        )

    def get_prediction_runs(
        self,
        *,
        model_version_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> PredictionRunListResult:
        clamped_limit = clamp_limit(limit)
        normalized_model_version = normalize_optional_identifier(
            model_version_id,
            field_name="model_version_id",
        )
        normalized_status = normalize_optional_status(status)
        return PredictionRunListResult(
            model_version_id=normalized_model_version,
            status=normalized_status,
            limit=clamped_limit,
            items=self._list_prediction_runs(
                model_version_id=normalized_model_version,
                status=normalized_status,
                limit=clamped_limit,
            ),
        )

    def get_prediction_metrics(
        self,
        *,
        prediction_run_id: str,
        metric_name: str | None = None,
    ) -> PredictionMetricResult:
        run = self._get_prediction_run(prediction_run_id)
        normalized_metric = normalize_optional_metric_name(metric_name)
        return PredictionMetricResult(
            prediction_run_id=run.prediction_run_id,
            model_version_id=run.model_version_id,
            metric_name=normalized_metric,
            items=self._list_prediction_points(
                prediction_run_id=run.prediction_run_id,
                metric_name=normalized_metric,
            ),
        )

    def get_latest_prediction(
        self,
        *,
        metric_name: str,
        namespace: str | None = None,
        workload: str | None = None,
    ) -> LatestPredictionResult:
        normalized_metric = normalize_metric_name(metric_name)
        normalized_namespace = normalize_optional_identifier(namespace, field_name="namespace")
        normalized_workload = normalize_optional_identifier(workload, field_name="workload")
        matching_runs = [
            run
            for run in self._list_prediction_runs(limit=MAX_SEARCH_LIMIT)
            if run.metric_name == normalized_metric
            and (normalized_namespace is None or run.namespace == normalized_namespace)
            and (normalized_workload is None or run.workload == normalized_workload)
        ]
        if not matching_runs:
            raise PredictionScalingValidationError("prediction was not found.")
        latest_run = max(matching_runs, key=lambda run: run.started_at)
        points = self._list_prediction_points(
            prediction_run_id=latest_run.prediction_run_id,
        )
        if not points:
            raise PredictionScalingValidationError("prediction metric was not found.")
        latest_point = max(points, key=lambda point: point.target_timestamp)
        return LatestPredictionResult(
            metric_name=latest_point.metric_name,
            namespace=latest_run.namespace,
            workload=latest_run.workload,
            prediction_run_id=latest_run.prediction_run_id,
            target_timestamp=latest_point.target_timestamp,
            predicted_value=latest_point.predicted_value,
            unit=latest_point.unit,
            confidence_lower=latest_point.confidence_lower,
            confidence_upper=latest_point.confidence_upper,
        )

    def get_actual_metrics(
        self,
        *,
        metric_name: str,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> ActualMetricResult:
        clamped_limit = clamp_limit(limit)
        normalized_metric = normalize_metric_name(metric_name)
        normalized_namespace = normalize_optional_identifier(namespace, field_name="namespace")
        normalized_workload = normalize_optional_identifier(workload, field_name="workload")
        return ActualMetricResult(
            metric_name=normalized_metric,
            namespace=normalized_namespace,
            workload=normalized_workload,
            limit=clamped_limit,
            items=self._list_actual_metrics(
                metric_name=normalized_metric,
                namespace=normalized_namespace,
                workload=normalized_workload,
                limit=clamped_limit,
            ),
        )

    def get_prediction_errors(
        self,
        *,
        prediction_run_id: str,
        limit: int = 20,
    ) -> PredictionErrorResult:
        clamped_limit = clamp_limit(limit)
        run = self._get_prediction_run(prediction_run_id)
        return PredictionErrorResult(
            prediction_run_id=run.prediction_run_id,
            limit=clamped_limit,
            items=self._build_prediction_errors(run)[:clamped_limit],
        )

    def get_prediction_error_metrics(
        self,
        *,
        prediction_run_id: str,
    ) -> PredictionErrorMetricsResult:
        run = self._get_prediction_run(prediction_run_id)
        errors = self._build_prediction_errors(run)
        if not errors:
            raise PredictionScalingValidationError("prediction errors were not found.")
        sample_count = len(errors)
        mean_absolute_error = sum(item.absolute_error for item in errors) / sample_count
        mean_absolute_percentage_error = (
            sum(item.percentage_error for item in errors) / sample_count
        )
        root_mean_squared_error = math.sqrt(
            sum(item.absolute_error**2 for item in errors) / sample_count
        )
        return PredictionErrorMetricsResult(
            prediction_run_id=run.prediction_run_id,
            metric_name=run.metric_name,
            sample_count=sample_count,
            mean_absolute_error=round(mean_absolute_error, 2),
            mean_absolute_percentage_error=round(mean_absolute_percentage_error, 4),
            root_mean_squared_error=round(root_mean_squared_error, 2),
        )

    def get_scaling_events(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> ScalingEventResult:
        clamped_limit = clamp_limit(limit)
        normalized_namespace = normalize_optional_identifier(namespace, field_name="namespace")
        normalized_workload = normalize_optional_identifier(workload, field_name="workload")
        return ScalingEventResult(
            namespace=normalized_namespace,
            workload=normalized_workload,
            limit=clamped_limit,
            items=self._list_scaling_events(
                namespace=normalized_namespace,
                workload=normalized_workload,
                limit=clamped_limit,
            ),
        )

    def get_scaling_summary(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
    ) -> ScalingSummaryResult:
        normalized_namespace = normalize_optional_identifier(namespace, field_name="namespace")
        normalized_workload = normalize_optional_identifier(workload, field_name="workload")
        events = self._list_scaling_events(
            namespace=normalized_namespace,
            workload=normalized_workload,
            limit=MAX_SEARCH_LIMIT,
        )
        desired_replicas = [event.desired_replicas for event in events]
        prediction_events = [
            event for event in events if event.trigger_source == "PREDICTION"
        ]
        return ScalingSummaryResult(
            namespace=normalized_namespace,
            workload=normalized_workload,
            total_events=len(events),
            prediction_driven_events=len(prediction_events),
            latest_desired_replicas=desired_replicas[-1] if desired_replicas else None,
            max_desired_replicas=max(desired_replicas) if desired_replicas else None,
            recommendation=build_scaling_recommendation(events),
        )

    def get_predictive_scaling_status(
        self,
        *,
        namespace: str | None = None,
        service: str | None = None,
        horizon_minutes: int = 180,
        include_keda: bool = True,
        include_hpa: bool = True,
    ) -> PredictiveScalingStatusResult:
        resolved_namespace = normalize_optional_identifier(
            namespace,
            field_name="namespace",
        ) or "kkpp"
        validate_horizon_minutes(horizon_minutes)
        validate_bool(include_keda, field_name="include_keda")
        validate_bool(include_hpa, field_name="include_hpa")
        services = resolve_predictive_services(service)
        generated_at = self._now_provider()
        exporter_metrics, exporter_error = self._read_exporter_metrics()
        k8s_state = self._read_predictive_kubernetes_state(
            namespace=resolved_namespace,
            include_keda=include_keda,
            include_hpa=include_hpa,
        )
        items = [
            self._build_predictive_scaling_item(
                namespace=resolved_namespace,
                service_name=service_name,
                short_service=short_service,
                horizon_minutes=horizon_minutes,
                exporter_metrics=exporter_metrics,
                exporter_error=exporter_error,
                k8s_state=k8s_state,
                generated_at=generated_at,
            )
            for service_name, short_service in services
        ]
        return PredictiveScalingStatusResult(
            namespace=resolved_namespace,
            service=service,
            horizon_minutes=horizon_minutes,
            generated_at=generated_at.isoformat(),
            items=items,
            summary=build_predictive_status_summary(items),
        )

    def create_prediction_snapshot(
        self,
        *,
        prediction_run_id: str,
    ) -> PredictionSnapshotResult:
        run = self._get_prediction_run(prediction_run_id)
        metrics = self.get_prediction_metrics(
            prediction_run_id=run.prediction_run_id,
        ).items
        return PredictionSnapshotResult(
            snapshot_id=build_snapshot_id("prediction", run.prediction_run_id),
            prediction_run_id=run.prediction_run_id,
            model_version_id=run.model_version_id,
            generated_at=datetime.now(UTC).isoformat(),
            metrics=metrics,
            error_metrics=self.get_prediction_error_metrics(
                prediction_run_id=run.prediction_run_id,
            ),
        )

    def create_scaling_analysis_snapshot(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
    ) -> ScalingAnalysisSnapshotResult:
        summary = self.get_scaling_summary(namespace=namespace, workload=workload)
        events = self.get_scaling_events(
            namespace=summary.namespace,
            workload=summary.workload,
            limit=MAX_SEARCH_LIMIT,
        ).items
        return ScalingAnalysisSnapshotResult(
            snapshot_id=build_snapshot_id(
                "scaling",
                f"{summary.namespace or 'all'}-{summary.workload or 'all'}",
            ),
            namespace=summary.namespace,
            workload=summary.workload,
            generated_at=datetime.now(UTC).isoformat(),
            summary=summary,
            events=events,
            evidence={
                "event_ids": [event.scaling_event_id for event in events],
                "related_prediction_run_ids": sorted(
                    {
                        event.related_prediction_run_id
                        for event in events
                        if event.related_prediction_run_id is not None
                    }
                ),
            },
        )

    def _get_prediction_run(self, prediction_run_id: str) -> PredictionRunResult:
        validate_identifier(prediction_run_id, field_name="prediction_run_id")
        normalized_run_id = prediction_run_id.strip().lower()
        run = self._repository.get_prediction_run(normalized_run_id)
        if run is None:
            raise PredictionScalingValidationError("prediction run was not found.")
        return run

    def _build_prediction_errors(self, run: PredictionRunResult) -> list[PredictionErrorItem]:
        points = self._list_prediction_points(prediction_run_id=run.prediction_run_id)
        actual_by_timestamp = {
            item.observed_at: item
            for item in self._list_actual_metrics(
                metric_name=run.metric_name,
                namespace=run.namespace,
                workload=run.workload,
                limit=MAX_SEARCH_LIMIT,
            )
        }
        errors = []
        for point in points:
            actual = actual_by_timestamp.get(point.target_timestamp)
            if actual is None:
                continue
            absolute_error = abs(actual.actual_value - point.predicted_value)
            percentage_error = absolute_error / actual.actual_value if actual.actual_value else 0.0
            errors.append(
                PredictionErrorItem(
                    prediction_run_id=run.prediction_run_id,
                    metric_name=point.metric_name,
                    target_timestamp=point.target_timestamp,
                    predicted_value=point.predicted_value,
                    actual_value=actual.actual_value,
                    absolute_error=round(absolute_error, 2),
                    percentage_error=round(percentage_error, 4),
                )
            )
        return errors

    def _read_exporter_metrics(
        self,
    ) -> tuple[dict[tuple[str, str, str], ExportedMetricValue], str | None]:
        try:
            return parse_predictive_metrics(self._metrics_reader.read_metrics()), None
        except (MetricsExporterError, OSError) as exc:
            return {}, str(exc)

    def _read_predictive_kubernetes_state(
        self,
        *,
        namespace: str,
        include_keda: bool,
        include_hpa: bool,
    ) -> dict[str, Any]:
        source = settings.prediction_scaling_kubernetes_source
        state: dict[str, Any] = {
            "deployments": {},
            "hpa": {},
            "scaled_objects": {},
            "errors": [],
        }
        try:
            deployments = self._kubernetes_reader.get_k8s_deployments(
                namespace=namespace,
                source=source,
            )
            state["deployments"] = index_kubernetes_items(deployments.items)
        except Exception as exc:
            state["errors"].append(f"deployments: {exc.__class__.__name__}")

        if include_hpa:
            try:
                hpa = self._kubernetes_reader.get_k8s_hpa(namespace=namespace, source=source)
                state["hpa"] = index_kubernetes_items(hpa.items)
            except Exception as exc:
                state["errors"].append(f"hpa: {exc.__class__.__name__}")

        if include_keda:
            try:
                scaled_objects = self._kubernetes_reader.get_k8s_scaled_objects(
                    namespace=namespace,
                    source=source,
                )
                state["scaled_objects"] = index_kubernetes_items(scaled_objects.items)
            except Exception as exc:
                state["errors"].append(f"scaled_objects: {exc.__class__.__name__}")

        return state

    def _build_predictive_scaling_item(
        self,
        *,
        namespace: str,
        service_name: str,
        short_service: str,
        horizon_minutes: int,
        exporter_metrics: dict[tuple[str, str, str], ExportedMetricValue],
        exporter_error: str | None,
        k8s_state: dict[str, Any],
        generated_at: datetime,
    ) -> PredictiveScalingStatusItem:
        db_metrics = self._read_predictive_metric_values(
            short_service=short_service,
            horizon_minutes=horizon_minutes,
        )
        values = merge_predictive_metric_values(
            short_service=short_service,
            db_metrics=db_metrics,
            exporter_metrics=exporter_metrics,
        )
        deployment_name = service_name
        hpa_name = f"keda-hpa-{service_name}-gru"
        scaled_object_name = f"{service_name}-gru"
        deployment = k8s_state["deployments"].get(deployment_name)
        hpa = k8s_state["hpa"].get(hpa_name)
        scaled_object = k8s_state["scaled_objects"].get(scaled_object_name)
        current_replicas = extract_current_replicas(hpa=hpa, deployment=deployment)
        desired_replicas = extract_desired_replicas(hpa=hpa, deployment=deployment)
        max_replicas = extract_max_replicas(hpa=hpa, scaled_object=scaled_object)
        onprem_adjusted_pods = values.get("onprem_adjusted_pods")
        scale_gap = calculate_scale_gap(onprem_adjusted_pods, current_replicas)
        freshness = calculate_prediction_freshness(
            created_at=extract_latest_created_at(db_metrics),
            generated_at=generated_at,
            stale_after_hours=settings.prediction_scaling_stale_after_hours,
        )
        scaling_active = extract_condition_bool(hpa, "ScalingActive")
        scaling_limited = extract_condition_bool(hpa, "ScalingLimited")
        risk_level = calculate_predictive_risk_level(
            has_prediction=bool(db_metrics) or has_exporter_prediction(values),
            freshness=freshness,
            scale_gap=scale_gap,
            scaling_active=scaling_active,
            scaling_limited=scaling_limited,
            onprem_adjusted_pods=onprem_adjusted_pods,
            current_replicas=current_replicas,
            predicted_pods=values.get("predicted_pods"),
            max_replicas=max_replicas,
        )
        evidence_errors = list(k8s_state["errors"])
        if exporter_error is not None:
            evidence_errors.append(f"metrics_exporter: {exporter_error}")
        return PredictiveScalingStatusItem(
            namespace=namespace,
            service=service_name,
            short_service=short_service,
            deployment=deployment_name,
            scaled_object=scaled_object_name,
            hpa=hpa_name,
            model_version=extract_latest_model_version(db_metrics, exporter_metrics, short_service),
            target_time=extract_latest_target_time(db_metrics),
            created_at=extract_latest_created_at(db_metrics),
            predicted_rps=values.get("predicted_rps"),
            predicted_pods=values.get("predicted_pods"),
            base_pods=values.get("base_pods"),
            extra_demand=values.get("extra_demand"),
            allocation_score=values.get("allocation_score"),
            onprem_adjusted_pods=onprem_adjusted_pods,
            current_replicas=current_replicas,
            desired_replicas=desired_replicas,
            max_replicas=max_replicas,
            scale_gap=scale_gap,
            scaling_active=scaling_active,
            scaling_limited=scaling_limited,
            prediction_freshness=freshness,
            risk_level=risk_level,
            summary=build_predictive_item_summary(
                service=service_name,
                risk_level=risk_level,
                freshness=freshness,
                scale_gap=scale_gap,
                scaling_active=scaling_active,
                scaling_limited=scaling_limited,
                current_replicas=current_replicas,
                onprem_adjusted_pods=onprem_adjusted_pods,
                max_replicas=max_replicas,
            ),
            evidence={
                "db_metric_names": sorted(db_metrics),
                "exporter_used": any(
                    (settings.prediction_scaling_prediction_namespace, short_service, metric_name)
                    in exporter_metrics
                    for metric_name in PREDICTIVE_METRIC_NAMES
                ),
                "deployment_found": deployment is not None,
                "hpa_found": hpa is not None,
                "scaled_object_found": scaled_object is not None,
                "errors": evidence_errors,
            },
        )

    def _read_predictive_metric_values(
        self,
        *,
        short_service: str,
        horizon_minutes: int,
    ) -> dict[str, PredictiveMetricValue]:
        rows = self._repository.get_predictive_metric_values(
            prediction_namespace=settings.prediction_scaling_prediction_namespace,
            service_name=short_service,
            metric_names=PREDICTIVE_METRIC_NAMES,
            horizon_minutes=horizon_minutes,
        )
        return {row.metric_name: row for row in rows}


def resolve_predictive_services(service: str | None) -> list[tuple[str, str]]:
    if service is None:
        return list(PREDICTIVE_SERVICE_MAP.items())
    normalized_service = normalize_optional_identifier(service, field_name="service")
    if normalized_service in PREDICTIVE_SERVICE_MAP:
        return [(normalized_service, PREDICTIVE_SERVICE_MAP[normalized_service])]
    if normalized_service in SHORT_SERVICE_TO_WORKLOAD:
        return [(SHORT_SERVICE_TO_WORKLOAD[normalized_service], normalized_service)]
    raise PredictionScalingValidationError("service is not supported.")


def validate_horizon_minutes(value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PredictionScalingValidationError("horizon_minutes must be a positive integer.")


def validate_bool(value: bool, *, field_name: str) -> None:
    if not isinstance(value, bool):
        raise PredictionScalingValidationError(f"{field_name} must be a boolean.")


def index_kubernetes_items(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        metadata["name"]: item
        for item in items
        if isinstance(item, dict)
        and isinstance((metadata := item.get("metadata", {})), dict)
        and isinstance(metadata.get("name"), str)
    }


def merge_predictive_metric_values(
    *,
    short_service: str,
    db_metrics: dict[str, PredictiveMetricValue],
    exporter_metrics: dict[tuple[str, str, str], ExportedMetricValue],
) -> dict[str, float]:
    values: dict[str, float] = {}
    prediction_namespace = settings.prediction_scaling_prediction_namespace
    for metric_name in PREDICTIVE_METRIC_NAMES:
        exported = exporter_metrics.get((prediction_namespace, short_service, metric_name))
        if exported is not None:
            values[metric_name] = exported.value
            continue
        db_value = db_metrics.get(metric_name)
        if db_value is not None:
            values[metric_name] = db_value.predicted_value
    return values


def extract_current_replicas(
    *,
    hpa: dict[str, Any] | None,
    deployment: dict[str, Any] | None,
) -> int | None:
    if hpa is not None:
        value = hpa.get("status", {}).get("currentReplicas")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    if deployment is None:
        return None
    status = deployment.get("status", {})
    spec = deployment.get("spec", {})
    for key in ("replicas", "readyReplicas", "availableReplicas"):
        value = status.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return int_or_none(spec.get("replicas"))


def extract_desired_replicas(
    *,
    hpa: dict[str, Any] | None,
    deployment: dict[str, Any] | None,
) -> int | None:
    if hpa is not None:
        value = hpa.get("status", {}).get("desiredReplicas")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    if deployment is None:
        return None
    return int_or_none(deployment.get("spec", {}).get("replicas"))


def extract_max_replicas(
    *,
    hpa: dict[str, Any] | None,
    scaled_object: dict[str, Any] | None,
) -> int | None:
    if hpa is not None:
        value = hpa.get("spec", {}).get("maxReplicas")
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    if scaled_object is None:
        return None
    return int_or_none(scaled_object.get("spec", {}).get("maxReplicaCount"))


def extract_condition_bool(resource: dict[str, Any] | None, condition_type: str) -> bool | None:
    if resource is None:
        return None
    conditions = resource.get("status", {}).get("conditions") or []
    if not isinstance(conditions, list):
        return None
    for condition in conditions:
        if not isinstance(condition, dict) or condition.get("type") != condition_type:
            continue
        status = str(condition.get("status", "")).lower()
        if status == "true":
            return True
        if status == "false":
            return False
    return None


def calculate_scale_gap(
    onprem_adjusted_pods: float | None,
    current_replicas: int | None,
) -> float | None:
    if onprem_adjusted_pods is None or current_replicas is None:
        return None
    return round(onprem_adjusted_pods - current_replicas, 2)


def calculate_prediction_freshness(
    *,
    created_at: str | None,
    generated_at: datetime,
    stale_after_hours: int,
) -> str:
    if created_at is None:
        return "missing"
    parsed_created_at = parse_datetime(created_at)
    if parsed_created_at is None:
        return "unknown"
    age_seconds = (generated_at - parsed_created_at).total_seconds()
    return "stale" if age_seconds > stale_after_hours * 3600 else "fresh"


def calculate_predictive_risk_level(
    *,
    has_prediction: bool,
    freshness: str,
    scale_gap: float | None,
    scaling_active: bool | None,
    scaling_limited: bool | None,
    onprem_adjusted_pods: float | None,
    current_replicas: int | None,
    predicted_pods: float | None,
    max_replicas: int | None,
) -> str:
    if not has_prediction:
        return "high"
    if scale_gap is not None and scale_gap >= 3:
        return "high"
    if scaling_active is False:
        return "high"
    if scaling_limited is True:
        return "high"
    if (
        onprem_adjusted_pods is not None
        and max_replicas is not None
        and onprem_adjusted_pods > max_replicas
    ):
        return "high"
    if scale_gap is not None and scale_gap > 0:
        return "medium"
    if freshness in {"stale", "missing", "unknown"}:
        return "medium"
    if (
        current_replicas is not None
        and predicted_pods is not None
        and current_replicas < predicted_pods
    ):
        return "medium"
    return "low"


def build_predictive_item_summary(
    *,
    service: str,
    risk_level: str,
    freshness: str,
    scale_gap: float | None,
    scaling_active: bool | None,
    scaling_limited: bool | None,
    current_replicas: int | None,
    onprem_adjusted_pods: float | None,
    max_replicas: int | None,
) -> str:
    if risk_level == "high":
        if freshness == "missing":
            return (
                f"{service}: prediction evidence is missing; "
                "verify GRU exporter and DB ingestion."
            )
        if scaling_limited is True:
            return (
                f"{service}: HPA is scaling-limited; "
                "max replica capacity may be blocking demand."
            )
        if scaling_active is False:
            return f"{service}: HPA scaling is inactive; KEDA/HPA signal is not being applied."
        if max_replicas is not None and onprem_adjusted_pods is not None:
            if onprem_adjusted_pods > max_replicas:
                return f"{service}: predicted demand exceeds max replicas ({max_replicas})."
        return f"{service}: predictive scale gap is high; pre-scale investigation is recommended."
    if risk_level == "medium":
        if freshness != "fresh":
            return (
                f"{service}: prediction is {freshness}; "
                "refresh model output before relying on it."
            )
        return f"{service}: predictive demand is slightly ahead of current replicas."
    if scale_gap is not None:
        return (
            f"{service}: predictive scaling is tracking demand "
            f"(current={current_replicas}, adjusted={onprem_adjusted_pods}, gap={scale_gap})."
        )
    return f"{service}: predictive scaling evidence is available with low risk."


def build_predictive_status_summary(items: list[PredictiveScalingStatusItem]) -> str:
    if not items:
        return "No predictive scaling services were evaluated."
    high = sum(item.risk_level == "high" for item in items)
    medium = sum(item.risk_level == "medium" for item in items)
    if high:
        return f"{high} service(s) show high predictive scaling risk."
    if medium:
        return f"{medium} service(s) show medium predictive scaling risk."
    return "All evaluated services show low predictive scaling risk."


def extract_latest_created_at(metrics: dict[str, PredictiveMetricValue]) -> str | None:
    return select_latest_metric(metrics).created_at if metrics else None


def extract_latest_target_time(metrics: dict[str, PredictiveMetricValue]) -> str | None:
    return select_latest_metric(metrics).target_time if metrics else None


def extract_latest_model_version(
    db_metrics: dict[str, PredictiveMetricValue],
    exporter_metrics: dict[tuple[str, str, str], ExportedMetricValue],
    short_service: str,
) -> str | None:
    prediction_namespace = settings.prediction_scaling_prediction_namespace
    for metric_name in PREDICTIVE_METRIC_NAMES:
        exported = exporter_metrics.get((prediction_namespace, short_service, metric_name))
        if exported is not None and exported.labels.get("model_version"):
            return exported.labels["model_version"]
    return select_latest_metric(db_metrics).model_version if db_metrics else None


def select_latest_metric(metrics: dict[str, PredictiveMetricValue]) -> PredictiveMetricValue:
    return max(metrics.values(), key=lambda metric: metric.created_at)


def has_exporter_prediction(values: dict[str, float]) -> bool:
    return any(metric_name in values for metric_name in PREDICTIVE_METRIC_NAMES)


def parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_optional_identifier(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    validate_identifier(value, field_name=field_name)
    return value.strip().lower()


def validate_identifier(value: str, *, field_name: str) -> None:
    if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value.strip()):
        return
    raise PredictionScalingValidationError(f"{field_name} is invalid.")


def normalize_metric_name(value: str) -> str:
    if isinstance(value, str) and METRIC_NAME_PATTERN.fullmatch(value.strip()):
        return value.strip()
    raise PredictionScalingValidationError("metric_name is invalid.")


def normalize_optional_metric_name(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_metric_name(value)


def normalize_optional_status(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PredictionScalingValidationError("status is invalid.")
    normalized = value.strip().upper()
    if normalized in {"SUCCEEDED", "RUNNING", "FAILED"}:
        return normalized
    raise PredictionScalingValidationError("status is invalid.")


def clamp_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise PredictionScalingValidationError("limit must be an integer.")
    return min(max(limit, 1), MAX_SEARCH_LIMIT)


def build_scaling_recommendation(events: list[ScalingEventItem]) -> str:
    if not events:
        return "No scaling event evidence is available for this filter."
    if any(event.trigger_source == "PREDICTION" for event in events):
        return "Review prediction-driven scale-up accuracy before changing autoscaling thresholds."
    return "Review observed HPA/KEDA events before enabling prediction-driven scaling."


def build_snapshot_id(snapshot_type: str, target_id: str) -> str:
    digest = hashlib.sha256(f"{snapshot_type}:{target_id}".encode()).hexdigest()[:8]
    safe_target = re.sub(r"[^a-z0-9-]+", "-", target_id.lower()).strip("-")
    return f"{snapshot_type}-snapshot-{safe_target}-{digest}"
