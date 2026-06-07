from typing import Annotated

from fastapi import Depends, Request

from aiops_platform.admin_riskops.service import AdminRiskOpsService
from aiops_platform.farmer_bnpl.service import FarmerBnplService
from aiops_platform.infra_rca.service import InfraRcaService
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.ops_reports.service import OpsReportService
from aiops_platform.orchestration.service import OrchestrationService


def get_orchestration_service(request: Request) -> OrchestrationService:
    return request.app.state.orchestration_service


def get_llmops_service(request: Request) -> LlmOpsService:
    return request.app.state.llmops_service


def get_infra_rca_service(request: Request) -> InfraRcaService:
    return request.app.state.infra_rca_service


def get_ops_report_service(request: Request) -> OpsReportService:
    return request.app.state.ops_report_service


def get_admin_riskops_service(request: Request) -> AdminRiskOpsService:
    return request.app.state.admin_riskops_service


def get_farmer_bnpl_service(request: Request) -> FarmerBnplService:
    return request.app.state.farmer_bnpl_service


OrchestrationServiceDep = Annotated[
    OrchestrationService,
    Depends(get_orchestration_service),
]
LlmOpsServiceDep = Annotated[
    LlmOpsService,
    Depends(get_llmops_service),
]
InfraRcaServiceDep = Annotated[
    InfraRcaService,
    Depends(get_infra_rca_service),
]
OpsReportServiceDep = Annotated[
    OpsReportService,
    Depends(get_ops_report_service),
]
AdminRiskOpsServiceDep = Annotated[
    AdminRiskOpsService,
    Depends(get_admin_riskops_service),
]
FarmerBnplServiceDep = Annotated[
    FarmerBnplService,
    Depends(get_farmer_bnpl_service),
]
