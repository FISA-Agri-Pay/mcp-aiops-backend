from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime
from string import Template
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
PREDICTIVE_EXPORTER_METRIC_NAMES = PREDICTIVE_METRIC_NAMES + ("actual_rps",)
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


class PredictivePrometheusReader(Protocol):
    def query_multi_cluster_prometheus(
        self,
        query: str,
        time: str | None = None,
    ):
        pass


class PredictionScalingService:
    def __init__(
        self,
        repository: PredictionScalingRepository | None = None,
        metrics_reader: PredictiveMetricsReader | None = None,
        kubernetes_reader: PredictiveKubernetesReader | None = None,
        prometheus_reader: PredictivePrometheusReader | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        infraops_service = InfraOpsService.from_settings() if kubernetes_reader is None else None
        self._repository = repository or SqlPredictionScalingRepository()
        self._metrics_reader = metrics_reader or MetricsExporterClient(
            settings.prediction_scaling_metrics_exporter_url,
            timeout_seconds=settings.prediction_scaling_metrics_timeout_seconds,
        )
        self._kubernetes_reader = kubernetes_reader or infraops_service
        self._prometheus_reader = prometheus_reader
        if self._prometheus_reader is None and hasattr(
            self._kubernetes_reader,
            "query_multi_cluster_prometheus",
        ):
            self._prometheus_reader = self._kubernetes_reader
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
        scaling_track_status = calculate_scaling_track_status(
            scale_gap=scale_gap,
            onprem_adjusted_pods=onprem_adjusted_pods,
            current_replicas=current_replicas,
        )
        predicted_rps = values.get("predicted_rps")
        actual_rps, actual_rps_evidence = self._resolve_actual_rps(
            namespace=namespace,
            service_name=service_name,
            short_service=short_service,
            values=values,
        )
        rps_deviation = calculate_rps_deviation(
            actual_rps=actual_rps,
            predicted_rps=predicted_rps,
        )
        rps_deviation_percent = calculate_rps_deviation_percent(
            actual_rps=actual_rps,
            predicted_rps=predicted_rps,
        )
        prediction_match_status = calculate_prediction_match_status(
            actual_rps=actual_rps,
            predicted_rps=predicted_rps,
            warning_deviation_percent=(
                settings.prediction_scaling_rps_warning_deviation_percent
            ),
        )
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
            prediction_match_status=prediction_match_status,
            rps_deviation_percent=rps_deviation_percent,
            rps_warning_deviation_percent=(
                settings.prediction_scaling_rps_warning_deviation_percent
            ),
            rps_critical_deviation_percent=(
                settings.prediction_scaling_rps_critical_deviation_percent
            ),
            max_replicas=max_replicas,
        )
        evidence_errors = list(k8s_state["errors"])
        if exporter_error is not None:
            evidence_errors.append(f"metrics_exporter: {exporter_error}")
        if actual_rps_evidence.get("error") is not None:
            evidence_errors.append(f"actual_rps: {actual_rps_evidence['error']}")
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
            predicted_rps=predicted_rps,
            actual_rps=actual_rps,
            rps_deviation=rps_deviation,
            rps_deviation_percent=rps_deviation_percent,
            prediction_match_status=prediction_match_status,
            predicted_pods=values.get("predicted_pods"),
            base_pods=values.get("base_pods"),
            extra_demand=values.get("extra_demand"),
            allocation_score=values.get("allocation_score"),
            onprem_adjusted_pods=onprem_adjusted_pods,
            current_replicas=current_replicas,
            desired_replicas=desired_replicas,
            max_replicas=max_replicas,
            scale_gap=scale_gap,
            scaling_track_status=scaling_track_status,
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
                actual_rps=actual_rps,
                predicted_rps=predicted_rps,
                rps_deviation_percent=rps_deviation_percent,
                prediction_match_status=prediction_match_status,
                scaling_track_status=scaling_track_status,
            ),
            evidence={
                "db_metric_names": sorted(db_metrics),
                "exporter_used": any(
                    (settings.prediction_scaling_prediction_namespace, short_service, metric_name)
                    in exporter_metrics
                    for metric_name in PREDICTIVE_EXPORTER_METRIC_NAMES
                ),
                "actual_rps": actual_rps_evidence,
                "deployment_found": deployment is not None,
                "hpa_found": hpa is not None,
                "scaled_object_found": scaled_object is not None,
                "errors": evidence_errors,
            },
        )

    def _resolve_actual_rps(
        self,
        *,
        namespace: str,
        service_name: str,
        short_service: str,
        values: dict[str, float],
    ) -> tuple[float | None, dict[str, Any]]:
        exported_actual_rps = values.get("actual_rps")
        if exported_actual_rps is not None:
            return exported_actual_rps, {"source": "metrics_exporter"}
        query = build_actual_rps_query(
            template=settings.prediction_scaling_actual_rps_query_template,
            namespace=namespace,
            service_name=service_name,
            short_service=short_service,
        )
        if not query:
            return None, {"source": "disabled"}
        if self._prometheus_reader is None:
            return None, {"source": "prometheus", "query": query}
        try:
            result = self._prometheus_reader.query_multi_cluster_prometheus(query=query)
        except Exception as exc:
            return None, {
                "source": "prometheus",
                "query": query,
                "error": exc.__class__.__name__,
            }
        actual_rps, source_name, error = extract_actual_rps_from_prometheus_result(
            result,
            preferred_source=settings.prediction_scaling_actual_rps_prometheus_source,
        )
        evidence: dict[str, Any] = {
            "source": source_name or "prometheus",
            "query": query,
        }
        if error is not None:
            evidence["error"] = error
        return actual_rps, evidence

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
    for metric_name in PREDICTIVE_EXPORTER_METRIC_NAMES:
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


def calculate_scaling_track_status(
    *,
    scale_gap: float | None,
    onprem_adjusted_pods: float | None,
    current_replicas: int | None,
) -> str:
    if scale_gap is None or onprem_adjusted_pods is None or current_replicas is None:
        return "unknown"
    if scale_gap > 0:
        return "lagging"
    if current_replicas > onprem_adjusted_pods:
        return "overprovisioned"
    return "tracking"


def calculate_rps_deviation(
    *,
    actual_rps: float | None,
    predicted_rps: float | None,
) -> float | None:
    if actual_rps is None or predicted_rps is None:
        return None
    return round(actual_rps - predicted_rps, 4)


def calculate_rps_deviation_percent(
    *,
    actual_rps: float | None,
    predicted_rps: float | None,
) -> float | None:
    if actual_rps is None or predicted_rps is None or predicted_rps <= 0:
        return None
    return round(abs(actual_rps - predicted_rps) / predicted_rps * 100, 2)


def calculate_prediction_match_status(
    *,
    actual_rps: float | None,
    predicted_rps: float | None,
    warning_deviation_percent: float,
) -> str:
    deviation_percent = calculate_rps_deviation_percent(
        actual_rps=actual_rps,
        predicted_rps=predicted_rps,
    )
    if actual_rps is None or predicted_rps is None or deviation_percent is None:
        return "unknown"
    if deviation_percent < warning_deviation_percent:
        return "matched"
    if actual_rps > predicted_rps:
        return "under_predicted"
    return "over_predicted"


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
    prediction_match_status: str,
    rps_deviation_percent: float | None,
    rps_warning_deviation_percent: float,
    rps_critical_deviation_percent: float,
    max_replicas: int | None,
) -> str:
    if not has_prediction:
        return "high"
    if (
        prediction_match_status == "under_predicted"
        and rps_deviation_percent is not None
        and rps_deviation_percent >= rps_critical_deviation_percent
    ):
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
    if (
        prediction_match_status == "under_predicted"
        and rps_deviation_percent is not None
        and rps_deviation_percent >= rps_warning_deviation_percent
    ):
        return "medium"
    if (
        prediction_match_status == "over_predicted"
        and rps_deviation_percent is not None
        and rps_deviation_percent >= rps_critical_deviation_percent
    ):
        return "medium"
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
    actual_rps: float | None,
    predicted_rps: float | None,
    rps_deviation_percent: float | None,
    prediction_match_status: str,
    scaling_track_status: str,
) -> str:
    if risk_level == "high":
        if prediction_match_status == "under_predicted":
            return (
                f"{service}: 실제 RPS가 예측값보다 높습니다 "
                f"({format_number(actual_rps)} vs {format_number(predicted_rps)}, "
                f"편차={format_number(rps_deviation_percent)}%). "
                "사전 스케일링 상태를 우선 확인해야 합니다."
            )
        if freshness == "missing":
            return (
                f"{service}: 예측 근거 데이터가 없습니다. "
                "GRU exporter와 DB 적재 상태를 확인하세요."
            )
        if scaling_limited is True:
            return (
                f"{service}: HPA가 스케일링 제한 상태입니다. "
                "max replica 설정이 예측 수요 반영을 막고 있을 수 있습니다."
            )
        if scaling_active is False:
            return f"{service}: HPA 스케일링이 비활성 상태라 KEDA/HPA 신호가 적용되지 않고 있습니다."
        if max_replicas is not None and onprem_adjusted_pods is not None:
            if onprem_adjusted_pods > max_replicas:
                return f"{service}: 예측 수요가 max replicas({max_replicas})를 초과합니다."
        return f"{service}: 예측 스케일 차이가 큽니다. 사전 스케일링 상태를 확인하세요."
    if risk_level == "medium":
        if prediction_match_status == "under_predicted":
            return (
                f"{service}: 실제 RPS가 예측보다 높아지는 흐름입니다 "
                f"(편차={format_number(rps_deviation_percent)}%)."
            )
        if prediction_match_status == "over_predicted":
            return (
                f"{service}: 실제 RPS가 예측보다 낮습니다 "
                f"(편차={format_number(rps_deviation_percent)}%). "
                "과다 스케일링 가능성을 확인하세요."
            )
        if freshness != "fresh":
            return (
                f"{service}: 예측값 freshness가 {freshness} 상태입니다. "
                "예측 결과를 신뢰하기 전에 모델 출력 갱신 여부를 확인하세요."
            )
        return f"{service}: 예측 수요가 현재 replica보다 약간 앞서 있습니다."
    if scale_gap is not None:
        if scaling_track_status == "overprovisioned":
            return (
                f"{service}: 현재 replica가 조정된 예측 수요보다 많습니다 "
                f"(현재={current_replicas}, 조정값={onprem_adjusted_pods})."
            )
        return (
            f"{service}: 예측 기반 스케일링이 수요를 추적 중입니다 "
            f"(상태={scaling_track_status}, 현재={current_replicas}, "
            f"조정값={onprem_adjusted_pods}, 차이={scale_gap})."
        )
    return f"{service}: 예측 스케일링 근거가 있으며 위험도는 낮습니다."


def build_predictive_status_summary(items: list[PredictiveScalingStatusItem]) -> str:
    if not items:
        return "평가된 예측 스케일링 서비스가 없습니다."
    high = sum(item.risk_level == "high" for item in items)
    medium = sum(item.risk_level == "medium" for item in items)
    if high:
        return f"{high}개 서비스에서 높은 예측 스케일링 위험이 감지되었습니다."
    if medium:
        return f"{medium}개 서비스에서 중간 예측 스케일링 위험이 감지되었습니다."
    return "평가된 모든 서비스의 예측 스케일링 위험도는 낮습니다."


def format_number(value: float | int | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:g}"


def build_actual_rps_query(
    *,
    template: str,
    namespace: str,
    service_name: str,
    short_service: str,
) -> str:
    normalized_template = template.strip()
    if not normalized_template:
        return ""
    return Template(normalized_template).safe_substitute(
        namespace=namespace,
        service=service_name,
        short_service=short_service,
    )


def extract_actual_rps_from_prometheus_result(
    result,
    *,
    preferred_source: str,
) -> tuple[float | None, str | None, str | None]:
    sources = getattr(result, "sources", [])
    if not sources:
        return None, None, "no Prometheus source returned"
    preferred = preferred_source.strip()
    ordered_sources = sorted(
        sources,
        key=lambda source: 0 if preferred and source.source == preferred else 1,
    )
    first_error: str | None = None
    for source in ordered_sources:
        if source.status != "SUCCESS" or source.data is None:
            first_error = source.error or f"{source.source} failed"
            continue
        value = extract_prometheus_vector_value(source.data)
        if value is not None:
            return value, source.source, None
        first_error = f"{source.source} returned no vector value"
    return None, preferred or None, first_error


def extract_prometheus_vector_value(data: dict[str, Any]) -> float | None:
    if data.get("status") != "success":
        return None
    result = data.get("data", {}).get("result", [])
    if not isinstance(result, list):
        return None
    for item in result:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, list) or len(value) < 2:
            continue
        parsed = parse_float(value[1])
        if parsed is not None:
            return parsed
    return None


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


def parse_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if math.isfinite(float(value)):
            return float(value)
        return None
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


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
