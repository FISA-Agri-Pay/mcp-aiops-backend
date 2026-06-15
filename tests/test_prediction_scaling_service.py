from datetime import UTC, datetime, timedelta

import pytest

from aiops_platform.infraops.schemas import KubernetesResourceResult
from aiops_platform.prediction_scaling.repository import SqlPredictionScalingRepository
from aiops_platform.prediction_scaling.schemas import PredictiveMetricValue
from aiops_platform.prediction_scaling.service import (
    PredictionScalingService,
    PredictionScalingValidationError,
)
from tests.seed_constants import (
    MODEL_TRAFFIC_V1_ID,
    MODEL_TRAFFIC_V2_ID,
    PREDICTION_RUN_API_ID,
    SCALING_EVENT_DOWN_ID,
    SCALING_EVENT_UP_ID,
)

NOW = datetime(2026, 6, 15, 0, 0, tzinfo=UTC)


class FakePredictiveRepository:
    def __init__(self, *, created_at: str = "2026-06-14T10:00:00+00:00") -> None:
        self.created_at = created_at

    def get_predictive_metric_values(
        self,
        *,
        prediction_namespace: str,
        service_name: str,
        metric_names: tuple[str, ...],
        horizon_minutes: int,
    ) -> list[PredictiveMetricValue]:
        values = {
            "predicted_rps": 250.0,
            "predicted_pods": 4.0,
            "base_pods": 1.0,
            "extra_demand": 8.0,
            "allocation_score": 8.0,
            "onprem_adjusted_pods": 4.0,
        }
        return [
            PredictiveMetricValue(
                metric_name=metric_name,
                namespace=prediction_namespace,
                service_name=service_name,
                predicted_value=values[metric_name],
                target_time="2026-06-15T00:05:00+00:00",
                model_version="service_gru_annual_2026_20260614082519",
                created_at=self.created_at,
            )
            for metric_name in metric_names
        ]


class EmptyPredictiveRepository(FakePredictiveRepository):
    def get_predictive_metric_values(self, **kwargs) -> list[PredictiveMetricValue]:
        return []


class FakeMetricsReader:
    def __init__(self, text: str = "") -> None:
        self.text = text

    def read_metrics(self) -> str:
        return self.text


class FakePredictiveKubernetesReader:
    def __init__(
        self,
        *,
        current_replicas: int = 4,
        desired_replicas: int = 4,
        max_replicas: int = 8,
        scaling_active: bool = True,
        scaling_limited: bool = False,
    ) -> None:
        self.current_replicas = current_replicas
        self.desired_replicas = desired_replicas
        self.max_replicas = max_replicas
        self.scaling_active = scaling_active
        self.scaling_limited = scaling_limited

    def get_k8s_deployments(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        return KubernetesResourceResult(
            source=source or "onprem",
            namespace=namespace or "kkpp",
            items=[
                {
                    "metadata": {"name": "service-payment"},
                    "spec": {"replicas": self.desired_replicas},
                    "status": {
                        "replicas": self.current_replicas,
                        "readyReplicas": self.current_replicas,
                        "availableReplicas": self.current_replicas,
                    },
                }
            ],
            raw={"items": []},
        )

    def get_k8s_hpa(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        return KubernetesResourceResult(
            source=source or "onprem",
            namespace=namespace or "kkpp",
            items=[
                {
                    "metadata": {"name": "keda-hpa-service-payment-gru"},
                    "spec": {"maxReplicas": self.max_replicas},
                    "status": {
                        "currentReplicas": self.current_replicas,
                        "desiredReplicas": self.desired_replicas,
                        "conditions": [
                            {
                                "type": "ScalingActive",
                                "status": "True" if self.scaling_active else "False",
                            },
                            {
                                "type": "ScalingLimited",
                                "status": "True" if self.scaling_limited else "False",
                            },
                        ],
                    },
                }
            ],
            raw={"items": []},
        )

    def get_k8s_scaled_objects(
        self,
        namespace: str | None = None,
        source: str | None = None,
    ) -> KubernetesResourceResult:
        return KubernetesResourceResult(
            source=source or "onprem",
            namespace=namespace or "kkpp",
            items=[
                {
                    "metadata": {"name": "service-payment-gru"},
                    "spec": {
                        "minReplicaCount": 1,
                        "maxReplicaCount": self.max_replicas,
                        "triggers": [
                            {
                                "type": "external",
                                "metadata": {
                                    "metricName": "onprem_adjusted_pods",
                                    "targetSize": "1",
                                },
                            }
                        ],
                    },
                }
            ],
            raw={"items": []},
        )


def test_model_versions_and_prediction_runs_can_be_filtered() -> None:
    service = PredictionScalingService()

    models = service.get_model_versions(service_name="api", limit=10)
    runs = service.get_prediction_runs(model_version_id="not-a-uuid-model", status="succeeded")

    assert [item.model_version_id for item in models.items] == [
        MODEL_TRAFFIC_V2_ID,
        MODEL_TRAFFIC_V1_ID,
    ]
    assert runs.status == "SUCCEEDED"
    assert [run.prediction_run_id for run in runs.items] == []

    runs = service.get_prediction_runs(model_version_id=MODEL_TRAFFIC_V2_ID, status="succeeded")
    assert [run.prediction_run_id for run in runs.items] == [PREDICTION_RUN_API_ID]
    assert runs.items[0].status == "SUCCEEDED"


def test_prediction_metrics_actuals_and_errors_are_deterministic() -> None:
    service = PredictionScalingService()

    predictions = service.get_prediction_metrics(
        prediction_run_id=PREDICTION_RUN_API_ID,
    )
    actuals = service.get_actual_metrics(
        metric_name="http_requests_per_second",
        namespace="default",
        workload="api",
        limit=10,
    )
    errors = service.get_prediction_errors(
        prediction_run_id=f" {PREDICTION_RUN_API_ID.upper()} ",
        limit=10,
    )
    error_metrics = service.get_prediction_error_metrics(
        prediction_run_id=PREDICTION_RUN_API_ID,
    )

    assert [point.predicted_value for point in predictions.items] == [100.0, 120.0, 150.0]
    assert [item.actual_value for item in actuals.items] == [96.0, 130.0, 144.0]
    assert errors.prediction_run_id == PREDICTION_RUN_API_ID
    assert [item.absolute_error for item in errors.items] == [4.0, 10.0, 6.0]
    assert error_metrics.sample_count == 3
    assert error_metrics.mean_absolute_error == 6.67
    assert error_metrics.root_mean_squared_error == 7.12


def test_prediction_run_lookup_does_not_depend_on_list_scan(monkeypatch) -> None:
    repository = SqlPredictionScalingRepository()

    def fail_list_scan(**kwargs):
        raise AssertionError("get_prediction_run should use direct lookup")

    monkeypatch.setattr(repository, "list_prediction_runs", fail_list_scan)

    run = repository.get_prediction_run(PREDICTION_RUN_API_ID)

    assert run is not None
    assert run.prediction_run_id == PREDICTION_RUN_API_ID


def test_latest_prediction_and_scaling_summary_match_filtered_workload() -> None:
    service = PredictionScalingService()

    latest = service.get_latest_prediction(
        metric_name="http_requests_per_second",
        namespace="default",
        workload="api",
    )
    events = service.get_scaling_events(namespace="default", workload="api", limit=10)
    summary = service.get_scaling_summary(namespace="default", workload="api")

    assert latest.predicted_value == 150.0
    assert [event.scaling_event_id for event in events.items] == [
        SCALING_EVENT_UP_ID,
        SCALING_EVENT_DOWN_ID,
    ]
    assert summary.total_events == 2
    assert summary.prediction_driven_events == 1
    assert summary.latest_desired_replicas == 3
    assert summary.max_desired_replicas == 4


def test_prediction_and_scaling_snapshots_include_evidence() -> None:
    service = PredictionScalingService()

    prediction_snapshot = service.create_prediction_snapshot(
        prediction_run_id=PREDICTION_RUN_API_ID,
    )
    scaling_snapshot = service.create_scaling_analysis_snapshot(
        namespace="default",
        workload="api",
    )

    assert prediction_snapshot.snapshot_id.startswith(
        f"prediction-snapshot-{PREDICTION_RUN_API_ID}-"
    )
    assert len(prediction_snapshot.metrics) == 3
    assert prediction_snapshot.error_metrics.mean_absolute_percentage_error == 0.0534
    assert scaling_snapshot.snapshot_id.startswith("scaling-snapshot-default-api-")
    assert scaling_snapshot.evidence["event_ids"] == [
        SCALING_EVENT_UP_ID,
        SCALING_EVENT_DOWN_ID,
    ]


def test_predictive_scaling_status_merges_prediction_exporter_and_k8s_state() -> None:
    metrics_text = """
aiops_predicted_rps{namespace="onprem",service="payment",model_version="exporter-v1"} 275
aiops_onprem_adjusted_pods{namespace="onprem",service="payment",model_version="exporter-v1"} 4
"""
    service = PredictionScalingService(
        repository=FakePredictiveRepository(),
        metrics_reader=FakeMetricsReader(metrics_text),
        kubernetes_reader=FakePredictiveKubernetesReader(),
        now_provider=lambda: NOW,
    )

    result = service.get_predictive_scaling_status(service="service-payment")

    assert result.namespace == "kkpp"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.service == "service-payment"
    assert item.short_service == "payment"
    assert item.predicted_rps == 275.0
    assert item.onprem_adjusted_pods == 4.0
    assert item.current_replicas == 4
    assert item.scale_gap == 0
    assert item.scaling_active is True
    assert item.scaling_limited is False
    assert item.prediction_freshness == "fresh"
    assert item.risk_level == "low"
    assert item.model_version == "exporter-v1"


def test_predictive_scaling_status_accepts_short_service_filter() -> None:
    service = PredictionScalingService(
        repository=FakePredictiveRepository(),
        metrics_reader=FakeMetricsReader(),
        kubernetes_reader=FakePredictiveKubernetesReader(),
        now_provider=lambda: NOW,
    )

    result = service.get_predictive_scaling_status(service="payment")

    assert [item.service for item in result.items] == ["service-payment"]
    assert result.items[0].short_service == "payment"


def test_predictive_scaling_status_marks_high_risk_for_large_scale_gap() -> None:
    metrics_text = """
aiops_onprem_adjusted_pods{namespace="onprem",service="payment"} 7
aiops_predicted_pods{namespace="onprem",service="payment"} 7
"""
    service = PredictionScalingService(
        repository=FakePredictiveRepository(),
        metrics_reader=FakeMetricsReader(metrics_text),
        kubernetes_reader=FakePredictiveKubernetesReader(current_replicas=3),
        now_provider=lambda: NOW,
    )

    item = service.get_predictive_scaling_status(service="payment").items[0]

    assert item.scale_gap == 4
    assert item.risk_level == "high"


def test_predictive_scaling_status_marks_stale_prediction_as_medium() -> None:
    service = PredictionScalingService(
        repository=FakePredictiveRepository(
            created_at=(NOW - timedelta(hours=25)).isoformat()
        ),
        metrics_reader=FakeMetricsReader(),
        kubernetes_reader=FakePredictiveKubernetesReader(),
        now_provider=lambda: NOW,
    )

    item = service.get_predictive_scaling_status(service="payment").items[0]

    assert item.prediction_freshness == "stale"
    assert item.risk_level == "medium"


def test_predictive_scaling_status_marks_missing_prediction_as_high() -> None:
    service = PredictionScalingService(
        repository=EmptyPredictiveRepository(),
        metrics_reader=FakeMetricsReader(),
        kubernetes_reader=FakePredictiveKubernetesReader(),
        now_provider=lambda: NOW,
    )

    item = service.get_predictive_scaling_status(service="payment").items[0]

    assert item.prediction_freshness == "missing"
    assert item.risk_level == "high"


def test_invalid_prediction_scaling_inputs_raise_domain_errors() -> None:
    service = PredictionScalingService()

    with pytest.raises(PredictionScalingValidationError, match="limit must be an integer"):
        service.get_model_versions(limit=True)

    with pytest.raises(PredictionScalingValidationError, match="metric_name is invalid"):
        service.get_latest_prediction(metric_name="bad metric")

    with pytest.raises(
        PredictionScalingValidationError,
        match="prediction run was not found",
    ):
        service.get_prediction_error_metrics(prediction_run_id="missing-run")

    with pytest.raises(PredictionScalingValidationError, match="service is not supported"):
        service.get_predictive_scaling_status(service="unknown")
