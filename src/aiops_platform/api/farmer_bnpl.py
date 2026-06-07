from fastapi import APIRouter, HTTPException, Query

from aiops_platform.api.dependencies import FarmerBnplServiceDep
from aiops_platform.farmer_bnpl.schemas import LatestOrderDeliveryStatusResult
from aiops_platform.farmer_bnpl.service import FarmerBnplValidationError

router = APIRouter(prefix="/farmer", tags=["farmer-bnpl"])


@router.get("/orders/latest/delivery", response_model=LatestOrderDeliveryStatusResult)
def get_latest_order_delivery_status(
    service: FarmerBnplServiceDep,
    user_id: str = Query(min_length=1, max_length=120),
) -> LatestOrderDeliveryStatusResult:
    try:
        return service.get_latest_order_delivery_status(user_id=user_id)
    except FarmerBnplValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
