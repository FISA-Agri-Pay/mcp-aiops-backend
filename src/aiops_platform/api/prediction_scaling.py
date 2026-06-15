from fastapi import APIRouter, HTTPException, Query

from aiops_platform.api.dependencies import PredictiveScalingSlackAgentServiceDep
from aiops_platform.prediction_scaling.schemas import PredictiveScalingSlackAgentResult
from aiops_platform.prediction_scaling.service import PredictionScalingValidationError

router = APIRouter(prefix="/prediction-scaling", tags=["prediction-scaling"])


@router.post("/slack-agent/run", response_model=PredictiveScalingSlackAgentResult)
def run_predictive_scaling_slack_agent(
    service: PredictiveScalingSlackAgentServiceDep,
    namespace: str | None = Query(default=None, min_length=1, max_length=120),
    target_service: str | None = Query(default=None, alias="service", max_length=120),
    horizon_minutes: int = Query(default=180, ge=1, le=1440),
    include_keda: bool = Query(default=True),
    include_hpa: bool = Query(default=True),
    notify: bool = Query(default=True),
    min_risk: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    dedupe: bool | None = Query(default=None),
) -> PredictiveScalingSlackAgentResult:
    try:
        return service.run_once(
            namespace=namespace,
            service=target_service,
            horizon_minutes=horizon_minutes,
            include_keda=include_keda,
            include_hpa=include_hpa,
            notify=notify,
            min_risk=min_risk,
            dedupe=dedupe,
        )
    except PredictionScalingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
