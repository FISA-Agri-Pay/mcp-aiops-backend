from fastapi import APIRouter, Response

from aiops_platform.core.metrics import PROMETHEUS_CONTENT_TYPE, render_prometheus_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics() -> Response:
    return Response(
        content=render_prometheus_metrics(),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )
