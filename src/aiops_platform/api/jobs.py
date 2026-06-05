from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from aiops_platform.api.dependencies import OrchestrationServiceDep
from aiops_platform.orchestration.schemas import JobActionPreviewResult, JobListResult, JobResult
from aiops_platform.orchestration.service import OrchestrationNotFoundError

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResult)
def list_jobs(
    service: OrchestrationServiceDep,
    status: Annotated[str | None, Query()] = None,
    job_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JobListResult:
    return service.list_jobs(status=status, job_type=job_type, limit=limit)


@router.get("/{job_id}", response_model=JobResult)
def get_job(
    job_id: str,
    service: OrchestrationServiceDep,
) -> JobResult:
    try:
        return service.get_job(job_id)
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{job_id}/retry", response_model=JobActionPreviewResult)
def retry_job(
    job_id: str,
    service: OrchestrationServiceDep,
) -> JobActionPreviewResult:
    try:
        return service.preview_retry_job(job_id)
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{job_id}/cancel", response_model=JobActionPreviewResult)
def cancel_job(
    job_id: str,
    service: OrchestrationServiceDep,
) -> JobActionPreviewResult:
    try:
        return service.preview_cancel_job(job_id)
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
