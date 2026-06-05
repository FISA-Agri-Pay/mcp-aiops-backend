from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime

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
    ScalingAnalysisSnapshotResult,
    ScalingEventItem,
    ScalingEventResult,
    ScalingSummaryResult,
)


class PredictionScalingValidationError(ValueError):
    pass


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
METRIC_NAME_PATTERN = re.compile(r"^[A-Za-z_:][A-Za-z0-9_:]{0,119}$")
MAX_SEARCH_LIMIT = 100


MODEL_VERSIONS = (
    ModelVersionResult(
        model_version_id="traffic-forecast-v2",
        service_name="api",
        model_name="gru-traffic-forecast",
        version="2.0.0",
        status="ACTIVE",
        deployed_at="2026-06-04T12:00:00+00:00",
        description="Short horizon traffic forecast model for autoscaling decisions.",
    ),
    ModelVersionResult(
        model_version_id="traffic-forecast-v1",
        service_name="api",
        model_name="lstm-traffic-forecast",
        version="1.4.2",
        status="ARCHIVED",
        deployed_at="2026-05-10T12:00:00+00:00",
        description="Previous production traffic forecast baseline.",
    ),
    ModelVersionResult(
        model_version_id="batch-runtime-v1",
        service_name="batch-worker",
        model_name="xgboost-runtime-estimator",
        version="1.0.0",
        status="CANDIDATE",
        deployed_at="2026-06-01T08:00:00+00:00",
        description="Candidate model for batch runtime prediction.",
    ),
)


PREDICTION_RUNS = (
    PredictionRunResult(
        prediction_run_id="pred-run-20260605-001",
        model_version_id="traffic-forecast-v2",
        service_name="api",
        namespace="default",
        workload="api",
        status="SUCCEEDED",
        metric_name="http_requests_per_second",
        horizon_minutes=30,
        started_at="2026-06-05T00:00:00+00:00",
        completed_at="2026-06-05T00:00:30+00:00",
    ),
    PredictionRunResult(
        prediction_run_id="pred-run-20260605-002",
        model_version_id="batch-runtime-v1",
        service_name="batch-worker",
        namespace="jobs",
        workload="settlement-worker",
        status="RUNNING",
        metric_name="job_runtime_seconds",
        horizon_minutes=60,
        started_at="2026-06-05T00:10:00+00:00",
    ),
)


PREDICTION_POINTS = (
    PredictionMetricPoint(
        prediction_run_id="pred-run-20260605-001",
        metric_name="http_requests_per_second",
        target_timestamp="2026-06-05T00:05:00+00:00",
        predicted_value=100.0,
        unit="rps",
        confidence_lower=90.0,
        confidence_upper=115.0,
    ),
    PredictionMetricPoint(
        prediction_run_id="pred-run-20260605-001",
        metric_name="http_requests_per_second",
        target_timestamp="2026-06-05T00:10:00+00:00",
        predicted_value=120.0,
        unit="rps",
        confidence_lower=108.0,
        confidence_upper=136.0,
    ),
    PredictionMetricPoint(
        prediction_run_id="pred-run-20260605-001",
        metric_name="http_requests_per_second",
        target_timestamp="2026-06-05T00:15:00+00:00",
        predicted_value=150.0,
        unit="rps",
        confidence_lower=132.0,
        confidence_upper=170.0,
    ),
    PredictionMetricPoint(
        prediction_run_id="pred-run-20260605-002",
        metric_name="job_runtime_seconds",
        target_timestamp="2026-06-05T01:00:00+00:00",
        predicted_value=740.0,
        unit="seconds",
        confidence_lower=680.0,
        confidence_upper=820.0,
    ),
)


ACTUAL_METRICS = (
    ActualMetricItem(
        metric_name="http_requests_per_second",
        namespace="default",
        workload="api",
        observed_at="2026-06-05T00:05:00+00:00",
        actual_value=96.0,
        unit="rps",
    ),
    ActualMetricItem(
        metric_name="http_requests_per_second",
        namespace="default",
        workload="api",
        observed_at="2026-06-05T00:10:00+00:00",
        actual_value=130.0,
        unit="rps",
    ),
    ActualMetricItem(
        metric_name="http_requests_per_second",
        namespace="default",
        workload="api",
        observed_at="2026-06-05T00:15:00+00:00",
        actual_value=144.0,
        unit="rps",
    ),
    ActualMetricItem(
        metric_name="job_runtime_seconds",
        namespace="jobs",
        workload="settlement-worker",
        observed_at="2026-06-05T01:00:00+00:00",
        actual_value=760.0,
        unit="seconds",
    ),
)


SCALING_EVENTS = (
    ScalingEventItem(
        scaling_event_id="scale-evt-20260605-001",
        namespace="default",
        workload="api",
        event_type="SCALE_UP",
        trigger_source="PREDICTION",
        occurred_at="2026-06-05T00:04:30+00:00",
        previous_replicas=2,
        desired_replicas=4,
        reason="Predicted request traffic exceeded the scale-up threshold.",
        related_prediction_run_id="pred-run-20260605-001",
    ),
    ScalingEventItem(
        scaling_event_id="scale-evt-20260605-002",
        namespace="default",
        workload="api",
        event_type="SCALE_DOWN",
        trigger_source="HPA",
        occurred_at="2026-06-05T00:20:00+00:00",
        previous_replicas=4,
        desired_replicas=3,
        reason="Observed CPU utilization returned below the target threshold.",
        related_prediction_run_id=None,
    ),
    ScalingEventItem(
        scaling_event_id="scale-evt-20260605-003",
        namespace="jobs",
        workload="settlement-worker",
        event_type="NOOP",
        trigger_source="KEDA",
        occurred_at="2026-06-05T01:00:00+00:00",
        previous_replicas=1,
        desired_replicas=1,
        reason="Queue depth remained within the configured target.",
        related_prediction_run_id="pred-run-20260605-002",
    ),
)


class PredictionScalingService:
    def get_model_versions(
        self,
        *,
        service_name: str | None = None,
        limit: int = 20,
    ) -> ModelVersionListResult:
        clamped_limit = clamp_limit(limit)
        normalized_service = normalize_optional_identifier(service_name, field_name="service_name")
        items = [
            item
            for item in MODEL_VERSIONS
            if normalized_service is None or item.service_name == normalized_service
        ][:clamped_limit]
        return ModelVersionListResult(
            service_name=normalized_service,
            limit=clamped_limit,
            items=items,
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
        items = [
            run
            for run in PREDICTION_RUNS
            if (
                normalized_model_version is None
                or run.model_version_id == normalized_model_version
            )
            and (normalized_status is None or run.status == normalized_status)
        ][:clamped_limit]
        return PredictionRunListResult(
            model_version_id=normalized_model_version,
            status=normalized_status,
            limit=clamped_limit,
            items=items,
        )

    def get_prediction_metrics(
        self,
        *,
        prediction_run_id: str,
        metric_name: str | None = None,
    ) -> PredictionMetricResult:
        run = get_prediction_run(prediction_run_id)
        normalized_metric = normalize_optional_metric_name(metric_name)
        items = [
            point
            for point in PREDICTION_POINTS
            if point.prediction_run_id == run.prediction_run_id
            and (normalized_metric is None or point.metric_name == normalized_metric)
        ]
        return PredictionMetricResult(
            prediction_run_id=run.prediction_run_id,
            model_version_id=run.model_version_id,
            metric_name=normalized_metric,
            items=items,
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
            for run in PREDICTION_RUNS
            if run.metric_name == normalized_metric
            and (normalized_namespace is None or run.namespace == normalized_namespace)
            and (normalized_workload is None or run.workload == normalized_workload)
        ]
        if not matching_runs:
            raise PredictionScalingValidationError("prediction was not found.")
        latest_run = max(matching_runs, key=lambda run: run.started_at)
        points = [
            point
            for point in PREDICTION_POINTS
            if point.prediction_run_id == latest_run.prediction_run_id
        ]
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
        items = [
            item
            for item in ACTUAL_METRICS
            if item.metric_name == normalized_metric
            and (normalized_namespace is None or item.namespace == normalized_namespace)
            and (normalized_workload is None or item.workload == normalized_workload)
        ][:clamped_limit]
        return ActualMetricResult(
            metric_name=normalized_metric,
            namespace=normalized_namespace,
            workload=normalized_workload,
            limit=clamped_limit,
            items=items,
        )

    def get_prediction_errors(
        self,
        *,
        prediction_run_id: str,
        limit: int = 20,
    ) -> PredictionErrorResult:
        clamped_limit = clamp_limit(limit)
        run = get_prediction_run(prediction_run_id)
        errors = build_prediction_errors(run)[:clamped_limit]
        return PredictionErrorResult(
            prediction_run_id=run.prediction_run_id,
            limit=clamped_limit,
            items=errors,
        )

    def get_prediction_error_metrics(
        self,
        *,
        prediction_run_id: str,
    ) -> PredictionErrorMetricsResult:
        run = get_prediction_run(prediction_run_id)
        errors = build_prediction_errors(run)
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
        items = filter_scaling_events(
            namespace=normalized_namespace,
            workload=normalized_workload,
        )[:clamped_limit]
        return ScalingEventResult(
            namespace=normalized_namespace,
            workload=normalized_workload,
            limit=clamped_limit,
            items=items,
        )

    def get_scaling_summary(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
    ) -> ScalingSummaryResult:
        normalized_namespace = normalize_optional_identifier(namespace, field_name="namespace")
        normalized_workload = normalize_optional_identifier(workload, field_name="workload")
        events = filter_scaling_events(
            namespace=normalized_namespace,
            workload=normalized_workload,
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

    def create_prediction_snapshot(
        self,
        *,
        prediction_run_id: str,
    ) -> PredictionSnapshotResult:
        run = get_prediction_run(prediction_run_id)
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


def get_prediction_run(prediction_run_id: str) -> PredictionRunResult:
    validate_identifier(prediction_run_id, field_name="prediction_run_id")
    normalized_run_id = prediction_run_id.strip().lower()
    for run in PREDICTION_RUNS:
        if run.prediction_run_id == normalized_run_id:
            return run
    raise PredictionScalingValidationError("prediction run was not found.")


def build_prediction_errors(run: PredictionRunResult) -> list[PredictionErrorItem]:
    points = [
        point
        for point in PREDICTION_POINTS
        if point.prediction_run_id == run.prediction_run_id
    ]
    actual_by_timestamp = {
        item.observed_at: item
        for item in ACTUAL_METRICS
        if item.metric_name == run.metric_name
        and item.namespace == run.namespace
        and item.workload == run.workload
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


def filter_scaling_events(
    *,
    namespace: str | None,
    workload: str | None,
) -> list[ScalingEventItem]:
    return [
        event
        for event in SCALING_EVENTS
        if (namespace is None or event.namespace == namespace)
        and (workload is None or event.workload == workload)
    ]


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
