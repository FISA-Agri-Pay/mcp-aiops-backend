from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from aiops_platform.core.database import SessionLocal
from aiops_platform.prediction_scaling.schemas import (
    ActualMetricItem,
    ModelVersionResult,
    PredictionMetricPoint,
    PredictionRunResult,
    ScalingEventItem,
)


@dataclass(frozen=True)
class PredictionPointRecord:
    point: PredictionMetricPoint
    prediction_metric_public_id: str


class PredictionScalingRepository(Protocol):
    def list_model_versions(
        self,
        *,
        service_name: str | None = None,
        limit: int = 20,
    ) -> list[ModelVersionResult]:
        pass

    def list_prediction_runs(
        self,
        *,
        model_version_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[PredictionRunResult]:
        pass

    def get_prediction_run(self, prediction_run_id: str) -> PredictionRunResult | None:
        pass

    def list_prediction_points(
        self,
        *,
        prediction_run_id: str,
        metric_name: str | None = None,
    ) -> list[PredictionMetricPoint]:
        pass

    def list_actual_metrics(
        self,
        *,
        metric_name: str,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> list[ActualMetricItem]:
        pass

    def list_scaling_events(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> list[ScalingEventItem]:
        pass


class SqlPredictionScalingRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def list_model_versions(
        self,
        *,
        service_name: str | None = None,
        limit: int = 20,
    ) -> list[ModelVersionResult]:
        query = text(
            """
            select
                public_id::text as model_version_id,
                model_name,
                model_version,
                target_metric,
                model_status,
                created_at::text as created_at,
                artifact_path,
                model_type
            from ai.model_versions
            where (
                cast(:service_name as text) is null
                or lower(model_name) = cast(:service_name as text)
            )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {"service_name": service_name, "limit": limit},
            ).mappings().all()
        return [build_model_version(row) for row in rows]

    def list_prediction_runs(
        self,
        *,
        model_version_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> list[PredictionRunResult]:
        if model_version_id is not None and not is_uuid(model_version_id):
            return []
        query = text(
            """
            select
                pr.public_id::text as prediction_run_id,
                pr.model_version_public_id::text as model_version_id,
                pr.target_service,
                pr.target_namespace,
                pr.target_metric,
                pr.prediction_horizon_minutes,
                pr.run_status,
                pr.started_at::text as started_at,
                pr.finished_at::text as finished_at
            from ai.prediction_runs pr
            where (
                cast(:model_version_id as uuid) is null
                or pr.model_version_public_id = cast(:model_version_id as uuid)
            )
              and (
                  cast(:status as text) is null
                  or pr.run_status = cast(:status as text)
              )
            order by pr.started_at desc nulls last
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "model_version_id": model_version_id,
                    "status": status,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_prediction_run(row) for row in rows]

    def get_prediction_run(self, prediction_run_id: str) -> PredictionRunResult | None:
        if not is_uuid(prediction_run_id):
            return None
        query = text(
            """
            select
                public_id::text as prediction_run_id,
                model_version_public_id::text as model_version_id,
                target_service,
                target_namespace,
                target_metric,
                prediction_horizon_minutes,
                run_status,
                started_at::text as started_at,
                finished_at::text as finished_at
            from ai.prediction_runs
            where public_id = cast(:prediction_run_id as uuid)
            limit 1
            """
        )
        with self._session_scope() as session:
            row = session.execute(
                query,
                {"prediction_run_id": prediction_run_id},
            ).mappings().first()
        return build_prediction_run(row) if row is not None else None

    def list_prediction_points(
        self,
        *,
        prediction_run_id: str,
        metric_name: str | None = None,
    ) -> list[PredictionMetricPoint]:
        if not is_uuid(prediction_run_id):
            return []
        query = text(
            """
            select
                pr.public_id::text as prediction_run_id,
                pm.metric_name,
                pm.target_time::text as target_timestamp,
                pm.predicted_value,
                pm.namespace,
                pm.service_name,
                mv.target_metric
            from ai.prediction_metrics pm
            join ai.prediction_runs pr on pr.public_id = pm.prediction_run_public_id
            left join ai.model_versions mv on mv.public_id = pr.model_version_public_id
            where pr.public_id = cast(:prediction_run_id as uuid)
              and (
                  cast(:metric_name as text) is null
                  or pm.metric_name = cast(:metric_name as text)
              )
            order by pm.target_time
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {"prediction_run_id": prediction_run_id, "metric_name": metric_name},
            ).mappings().all()
        return [build_prediction_point(row) for row in rows]

    def list_actual_metrics(
        self,
        *,
        metric_name: str,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> list[ActualMetricItem]:
        query = text(
            """
            select
                metric_name,
                namespace,
                service_name,
                measured_at::text as observed_at,
                actual_value
            from ai.actual_metrics
            where metric_name = :metric_name
              and (
                  cast(:namespace as text) is null
                  or namespace = cast(:namespace as text)
              )
              and (
                  cast(:workload as text) is null
                  or service_name = cast(:workload as text)
              )
            order by measured_at
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "metric_name": metric_name,
                    "namespace": namespace,
                    "workload": workload,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_actual_metric(row) for row in rows]

    def list_scaling_events(
        self,
        *,
        namespace: str | None = None,
        workload: str | None = None,
        limit: int = 20,
    ) -> list[ScalingEventItem]:
        query = text(
            """
            select
                se.public_id::text as scaling_event_id,
                se.namespace,
                se.workload,
                se.source_type,
                se.previous_replicas,
                se.new_replicas,
                se.reason,
                se.event_time::text as occurred_at,
                pr.public_id::text as related_prediction_run_id
            from ai.scaling_events se
            left join ai.prediction_metrics pm on pm.public_id = se.prediction_metric_public_id
            left join ai.prediction_runs pr on pr.public_id = pm.prediction_run_public_id
            where (
                cast(:namespace as text) is null
                or se.namespace = cast(:namespace as text)
            )
              and (
                  cast(:workload as text) is null
                  or se.workload = cast(:workload as text)
              )
            order by se.event_time
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {"namespace": namespace, "workload": workload, "limit": limit},
            ).mappings().all()
        return [build_scaling_event(row) for row in rows]

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
            return
        with SessionLocal() as session:
            yield session


def build_model_version(row) -> ModelVersionResult:
    return ModelVersionResult(
        model_version_id=row["model_version_id"],
        service_name=row["model_name"],
        model_name=row["model_name"],
        version=row["model_version"],
        status=map_model_status(row["model_status"]),
        deployed_at=row["created_at"],
        description=row["artifact_path"] or row["model_type"] or row["target_metric"] or "",
    )


def build_prediction_run(row) -> PredictionRunResult:
    return PredictionRunResult(
        prediction_run_id=row["prediction_run_id"],
        model_version_id=row["model_version_id"],
        service_name=row["target_service"],
        namespace=row["target_namespace"],
        workload=row["target_service"],
        status=row["run_status"],
        metric_name=row["target_metric"],
        horizon_minutes=int(row["prediction_horizon_minutes"]),
        started_at=row["started_at"],
        completed_at=row["finished_at"],
    )


def build_prediction_point(row) -> PredictionMetricPoint:
    value = float(row["predicted_value"])
    return PredictionMetricPoint(
        prediction_run_id=row["prediction_run_id"],
        metric_name=row["metric_name"],
        target_timestamp=row["target_timestamp"],
        predicted_value=value,
        unit=infer_unit(row["metric_name"]),
        confidence_lower=value,
        confidence_upper=value,
    )


def build_actual_metric(row) -> ActualMetricItem:
    return ActualMetricItem(
        metric_name=row["metric_name"],
        namespace=row["namespace"],
        workload=row["service_name"],
        observed_at=row["observed_at"],
        actual_value=float(row["actual_value"]),
        unit=infer_unit(row["metric_name"]),
    )


def build_scaling_event(row) -> ScalingEventItem:
    previous = int(row["previous_replicas"] or 0)
    desired = int(row["new_replicas"] or 0)
    return ScalingEventItem(
        scaling_event_id=row["scaling_event_id"],
        namespace=row["namespace"],
        workload=row["workload"],
        event_type=derive_event_type(previous, desired),
        trigger_source=map_trigger_source(row["source_type"], row["related_prediction_run_id"]),
        occurred_at=row["occurred_at"],
        previous_replicas=previous,
        desired_replicas=desired,
        reason=row["reason"] or "",
        related_prediction_run_id=row["related_prediction_run_id"],
    )


def map_model_status(value: str) -> str:
    if value == "ACTIVE":
        return "ACTIVE"
    if value == "INACTIVE":
        return "ARCHIVED"
    return "ARCHIVED"


def map_trigger_source(source_type: str, related_prediction_run_id: str | None) -> str:
    if related_prediction_run_id is not None:
        return "PREDICTION"
    if source_type in {"HPA", "KEDA", "MANUAL"}:
        return source_type
    return "MANUAL"


def derive_event_type(previous: int, desired: int) -> str:
    if desired > previous:
        return "SCALE_UP"
    if desired < previous:
        return "SCALE_DOWN"
    return "NOOP"


def infer_unit(metric_name: str) -> str:
    if metric_name.endswith("_seconds"):
        return "seconds"
    if "request" in metric_name:
        return "rps"
    return "value"


def to_float(value: Decimal | int | float | None) -> float:
    return float(value or 0)


def is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True
