from typing import Any, Literal

from pydantic import BaseModel, Field


class FarmerBnplActionPreviewResult(BaseModel):
    action: str
    user_id: str
    request_payload: dict[str, Any]
    dry_run: bool = True
    status: Literal["DRAFT", "PENDING_CONFIRMATION"] = "PENDING_CONFIRMATION"
    safety_notes: list[str]


class CreditApplicationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    requested_amount: int = Field(gt=0, le=50_000_000)
    crop_type: str | None = Field(default=None, max_length=80)
    season: str | None = Field(default=None, max_length=40)


class CreditApplicationDraftResult(BaseModel):
    application_id: str
    user_id: str
    requested_amount: int
    status: Literal["DRAFT"] = "DRAFT"
    required_documents: list[str]
    dry_run: bool = True


class FarmlandInfoRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=160)
    area_hectare: float = Field(gt=0, le=1000)
    ownership_type: str = Field(min_length=1, max_length=40)


class CropInfoRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    crop_type: str = Field(min_length=1, max_length=80)
    expected_yield_kg: int | None = Field(default=None, gt=0, le=10_000_000)
    expected_revenue: int | None = Field(default=None, ge=0, le=1_000_000_000)


class InsuranceInfoRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=120)
    policy_number: str | None = Field(default=None, max_length=120)
    coverage_amount: int | None = Field(default=None, ge=0, le=1_000_000_000)


class RequiredDocumentsResult(BaseModel):
    user_id: str
    application_type: str
    documents: list[str]


class DocumentSubmissionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    application_id: str = Field(min_length=1, max_length=120)
    document_types: list[str] = Field(min_length=1, max_length=20)


class CreditLimitStatusResult(BaseModel):
    user_id: str
    application_id: str | None = None
    status: Literal["DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED"]
    missing_documents: list[str]


class UserCreditLimitResult(BaseModel):
    user_id: str
    credit_limit_id: str
    total_limit: int
    used_amount: int
    available_limit: int
    currency: Literal["KRW"] = "KRW"
    status: Literal["ACTIVE", "PENDING", "SUSPENDED"] = "ACTIVE"


class FarmerProfileResult(BaseModel):
    user_id: str
    display_name: str
    region: str
    main_crop: str
    profile_status: Literal["INCOMPLETE", "READY_FOR_REVIEW", "ACTIVE"]


class RepaymentScheduleItem(BaseModel):
    installment_no: int
    due_date: str
    principal_due: int
    interest_due: int
    status: Literal["UPCOMING", "PAID", "OVERDUE"]


class RepaymentScheduleResult(BaseModel):
    user_id: str
    currency: Literal["KRW"] = "KRW"
    schedule: list[RepaymentScheduleItem]


class InterestDueResult(BaseModel):
    user_id: str
    due_date: str
    interest_due: int
    currency: Literal["KRW"] = "KRW"


class OverdueStatusResult(BaseModel):
    user_id: str
    is_overdue: bool
    overdue_amount: int
    days_overdue: int
    currency: Literal["KRW"] = "KRW"


class LatestOrderDeliveryStatusResult(BaseModel):
    user_id: str
    order_id: str
    item_name: str
    order_status: str
    delivery_status: str
    total_amount: int
    currency: Literal["KRW"] = "KRW"
    ordered_at: str


class ProductResult(BaseModel):
    product_id: str
    name: str
    category: str
    unit_price: int
    currency: Literal["KRW"] = "KRW"
    vendor: str
    stock_status: Literal["IN_STOCK", "LOW_STOCK", "OUT_OF_STOCK"]


class ProductSearchResult(BaseModel):
    query: str | None = None
    category: str | None = None
    limit: int
    items: list[ProductResult]


class ProductDetailResult(BaseModel):
    product: ProductResult
    description: str
    tags: list[str]


class CartItem(BaseModel):
    product_id: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=1, le=999)


class CartLineResult(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    unit_price: int
    line_total: int


class CartTotalResult(BaseModel):
    currency: Literal["KRW"] = "KRW"
    items: list[CartLineResult]
    total_amount: int


class CheckoutPayloadResult(BaseModel):
    user_id: str
    credit_limit_id: str
    currency: Literal["KRW"] = "KRW"
    total_amount: int
    available_limit: int
    eligible: bool
    payload: dict[str, Any]


class CheckoutIntentResult(BaseModel):
    checkout_intent_id: str
    user_id: str
    status: Literal["PENDING_USER_CONFIRMATION"] = "PENDING_USER_CONFIRMATION"
    total_amount: int
    currency: Literal["KRW"] = "KRW"
    dry_run: bool = True


class BnplCheckoutPreviewResult(BaseModel):
    checkout_intent_id: str
    user_id: str
    status: Literal["PENDING_CONFIRMATION"] = "PENDING_CONFIRMATION"
    payment_method: Literal["BNPL"] = "BNPL"
    dry_run: bool = True
    safety_notes: list[str]
