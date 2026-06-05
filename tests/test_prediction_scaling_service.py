import pytest

from aiops_platform.prediction_scaling.repository import SqlPredictionScalingRepository
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
