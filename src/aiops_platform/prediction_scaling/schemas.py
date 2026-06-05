from typing import Any, Literal

from pydantic import BaseModel, Field


class ModelVersionResult(BaseModel):
    model_version_id: str
    service_name: str
    model_name: str
    version: str
    status: Literal["ACTIVE", "CANDIDATE", "ARCHIVED"]
    deployed_at: str
    description: str


class ModelVersionListResult(BaseModel):
    service_name: str | None = None
    limit: int
    items: list[ModelVersionResult]


class PredictionRunResult(BaseModel):
    prediction_run_id: str
    model_version_id: str
    service_name: str
    namespace: str
    workload: str
    status: Literal["SUCCEEDED", "RUNNING", "FAILED"]
    metric_name: str
    horizon_minutes: int
    started_at: str
    completed_at: str | None = None


class PredictionRunListResult(BaseModel):
    model_version_id: str | None = None
    status: str | None = None
    limit: int
    items: list[PredictionRunResult]


class PredictionMetricPoint(BaseModel):
    prediction_run_id: str
    metric_name: str
    target_timestamp: str
    predicted_value: float
    unit: str
    confidence_lower: float
    confidence_upper: float


class PredictionMetricResult(BaseModel):
    prediction_run_id: str
    model_version_id: str
    metric_name: str | None = None
    items: list[PredictionMetricPoint]


class LatestPredictionResult(BaseModel):
    metric_name: str
    namespace: str
    workload: str
    prediction_run_id: str
    target_timestamp: str
    predicted_value: float
    unit: str
    confidence_lower: float
    confidence_upper: float


class ActualMetricItem(BaseModel):
    metric_name: str
    namespace: str
    workload: str
    observed_at: str
    actual_value: float
    unit: str


class ActualMetricResult(BaseModel):
    metric_name: str
    namespace: str | None = None
    workload: str | None = None
    limit: int
    items: list[ActualMetricItem]


class PredictionErrorItem(BaseModel):
    prediction_run_id: str
    metric_name: str
    target_timestamp: str
    predicted_value: float
    actual_value: float
    absolute_error: float
    percentage_error: float


class PredictionErrorResult(BaseModel):
    prediction_run_id: str
    limit: int
    items: list[PredictionErrorItem]


class PredictionErrorMetricsResult(BaseModel):
    prediction_run_id: str
    metric_name: str
    sample_count: int
    mean_absolute_error: float
    mean_absolute_percentage_error: float
    root_mean_squared_error: float


class ScalingEventItem(BaseModel):
    scaling_event_id: str
    namespace: str
    workload: str
    event_type: Literal["SCALE_UP", "SCALE_DOWN", "NOOP"]
    trigger_source: Literal["PREDICTION", "HPA", "KEDA", "MANUAL"]
    occurred_at: str
    previous_replicas: int
    desired_replicas: int
    reason: str
    related_prediction_run_id: str | None = None


class ScalingEventResult(BaseModel):
    namespace: str | None = None
    workload: str | None = None
    limit: int
    items: list[ScalingEventItem]


class ScalingSummaryResult(BaseModel):
    namespace: str | None = None
    workload: str | None = None
    total_events: int
    prediction_driven_events: int
    latest_desired_replicas: int | None = None
    max_desired_replicas: int | None = None
    recommendation: str


class PredictionSnapshotResult(BaseModel):
    snapshot_id: str
    prediction_run_id: str
    model_version_id: str
    generated_at: str
    metrics: list[PredictionMetricPoint]
    error_metrics: PredictionErrorMetricsResult


class ScalingAnalysisSnapshotResult(BaseModel):
    snapshot_id: str
    namespace: str | None = None
    workload: str | None = None
    generated_at: str
    summary: ScalingSummaryResult
    events: list[ScalingEventItem]
    evidence: dict[str, Any] = Field(default_factory=dict)
