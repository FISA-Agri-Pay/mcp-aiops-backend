from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Any

from aiops_platform.core.config import settings
from aiops_platform.farmer_bnpl.repository import (
    FarmerBnplRepository,
    SqlFarmerBnplRepository,
)
from aiops_platform.farmer_bnpl.schemas import (
    BnplCheckoutPreviewResult,
    CartItem,
    CartLineResult,
    CartTotalResult,
    CheckoutIntentResult,
    CheckoutPayloadResult,
    CreditApplicationDraftResult,
    CreditApplicationRequest,
    CreditLimitStatusResult,
    CropInfoRequest,
    DocumentSubmissionRequest,
    FarmerBnplActionPreviewResult,
    FarmerProfileResult,
    FarmlandInfoRequest,
    InsuranceInfoRequest,
    InterestDueResult,
    LatestOrderDeliveryStatusResult,
    OverdueStatusResult,
    ProductDetailResult,
    ProductResult,
    ProductSearchResult,
    RepaymentScheduleResult,
    RequiredDocumentsResult,
    UserCreditLimitResult,
)


class FarmerBnplValidationError(ValueError):
    pass


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,119}$")
PUBLIC_ID_DISALLOWED_PATTERN = re.compile(r"[^a-z0-9-]+")
PUBLIC_ID_REPEATED_SEPARATOR_PATTERN = re.compile(r"-+")
PUBLIC_ID_MAX_LENGTH = 120
PUBLIC_ID_HASH_LENGTH = 8


class FarmerBnplService:
    def __init__(self, repository: FarmerBnplRepository | None = None) -> None:
        self._repository = repository or SqlFarmerBnplRepository()

    def start_credit_application(
        self,
        *,
        user_id: str,
        requested_amount: int,
        crop_type: str | None = None,
        season: str | None = None,
    ) -> CreditApplicationDraftResult:
        request = CreditApplicationRequest(
            user_id=user_id,
            requested_amount=requested_amount,
            crop_type=crop_type,
            season=season,
        )
        validate_identifier(request.user_id, field_name="user_id")
        return CreditApplicationDraftResult(
            application_id=build_public_id("credit-app", request.user_id),
            user_id=request.user_id,
            requested_amount=request.requested_amount,
            required_documents=get_required_document_keys(),
        )

    def save_farmland_info(
        self,
        *,
        user_id: str,
        location: str,
        area_hectare: float,
        ownership_type: str,
    ) -> FarmerBnplActionPreviewResult:
        request = FarmlandInfoRequest(
            user_id=user_id,
            location=location,
            area_hectare=area_hectare,
            ownership_type=ownership_type,
        )
        return build_action_preview(
            action="save_farmland_info",
            user_id=request.user_id,
            request_payload=request.model_dump(mode="json"),
        )

    def save_crop_info(
        self,
        *,
        user_id: str,
        crop_type: str,
        expected_yield_kg: int | None = None,
        expected_revenue: int | None = None,
    ) -> FarmerBnplActionPreviewResult:
        request = CropInfoRequest(
            user_id=user_id,
            crop_type=crop_type,
            expected_yield_kg=expected_yield_kg,
            expected_revenue=expected_revenue,
        )
        return build_action_preview(
            action="save_crop_info",
            user_id=request.user_id,
            request_payload=request.model_dump(mode="json"),
        )

    def save_insurance_info(
        self,
        *,
        user_id: str,
        provider: str,
        policy_number: str | None = None,
        coverage_amount: int | None = None,
    ) -> FarmerBnplActionPreviewResult:
        request = InsuranceInfoRequest(
            user_id=user_id,
            provider=provider,
            policy_number=policy_number,
            coverage_amount=coverage_amount,
        )
        return build_action_preview(
            action="save_insurance_info",
            user_id=request.user_id,
            request_payload=request.model_dump(mode="json"),
        )

    def get_required_documents(
        self,
        *,
        user_id: str,
        application_type: str = "credit_application",
    ) -> RequiredDocumentsResult:
        validate_identifier(user_id, field_name="user_id")
        return RequiredDocumentsResult(
            user_id=user_id,
            application_type=application_type,
            documents=get_required_document_keys(),
        )

    def submit_credit_documents(
        self,
        *,
        user_id: str,
        application_id: str,
        document_types: list[str],
    ) -> FarmerBnplActionPreviewResult:
        request = DocumentSubmissionRequest(
            user_id=user_id,
            application_id=application_id,
            document_types=document_types,
        )
        validate_identifier(request.application_id, field_name="application_id")
        return build_action_preview(
            action="submit_credit_documents",
            user_id=request.user_id,
            request_payload=request.model_dump(mode="json"),
        )

    def get_credit_limit_status(
        self,
        *,
        user_id: str,
        application_id: str | None = None,
    ) -> CreditLimitStatusResult:
        validate_identifier(user_id, field_name="user_id")
        if application_id is not None:
            validate_identifier(application_id, field_name="application_id")
        return CreditLimitStatusResult(
            user_id=user_id,
            application_id=application_id,
            status="UNDER_REVIEW",
            missing_documents=[],
        )

    def get_user_credit_limit(self, *, user_id: str) -> UserCreditLimitResult:
        validate_identifier(user_id, field_name="user_id")
        credit_limit = self._repository.get_user_credit_limit(user_id)
        if credit_limit is None:
            raise FarmerBnplValidationError("credit limit was not found.")
        return credit_limit

    def get_farmer_profile(self, *, user_id: str) -> FarmerProfileResult:
        validate_identifier(user_id, field_name="user_id")
        profile = self._repository.get_farmer_profile(user_id)
        if profile is None:
            raise FarmerBnplValidationError("farmer profile was not found.")
        return profile

    def get_repayment_schedule(self, *, user_id: str) -> RepaymentScheduleResult:
        validate_identifier(user_id, field_name="user_id")
        schedule = self._repository.list_repayment_schedule(user_id)
        return RepaymentScheduleResult(
            user_id=user_id,
            schedule=schedule,
        )

    def get_interest_due(self, *, user_id: str) -> InterestDueResult:
        validate_identifier(user_id, field_name="user_id")
        interest_due = self._repository.get_interest_due(user_id)
        if interest_due is None:
            raise FarmerBnplValidationError("interest due was not found.")
        return interest_due

    def get_overdue_status(self, *, user_id: str) -> OverdueStatusResult:
        validate_identifier(user_id, field_name="user_id")
        overdue_status = self._repository.get_overdue_status(user_id)
        return overdue_status or OverdueStatusResult(
            user_id=user_id,
            is_overdue=False,
            overdue_amount=0,
            days_overdue=0,
        )

    def get_latest_order_delivery_status(
        self,
        *,
        user_id: str,
    ) -> LatestOrderDeliveryStatusResult:
        validate_identifier(user_id, field_name="user_id")
        delivery_status = self._repository.get_latest_order_delivery_status(user_id)
        if delivery_status is None:
            raise FarmerBnplValidationError("latest order delivery status was not found.")
        return delivery_status

    def search_products(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> ProductSearchResult:
        clamped_limit = clamp_limit(limit)
        normalized_query = query.lower().strip() if query else None
        normalized_category = category.lower().strip() if category else None
        items = self._repository.list_products(
            query=normalized_query,
            category=normalized_category,
            limit=clamped_limit,
        )
        return ProductSearchResult(
            query=query,
            category=category,
            limit=clamped_limit,
            items=items,
        )

    def search_lowest_price_fertilizer(self, *, limit: int = 5) -> ProductSearchResult:
        clamped_limit = clamp_limit(limit)
        items = self._repository.list_products(category="fertilizer", limit=clamped_limit)
        return ProductSearchResult(
            query="lowest_price",
            category="fertilizer",
            limit=clamped_limit,
            items=items,
        )

    def get_product_detail(self, *, product_id: str) -> ProductDetailResult:
        product = self._get_product(product_id)
        return ProductDetailResult(
            product=product,
            description=f"{product.name} supplied by {product.vendor}.",
            tags=[product.category, product.stock_status.lower()],
        )

    def calculate_cart_total(self, *, items: list[dict[str, Any]]) -> CartTotalResult:
        cart_items = parse_cart_items(items)
        return self._calculate_cart_total(cart_items)

    def prepare_bnpl_checkout_payload(
        self,
        *,
        user_id: str,
        items: list[dict[str, Any]],
        credit_limit_id: str | None = None,
    ) -> CheckoutPayloadResult:
        validate_identifier(user_id, field_name="user_id")
        cart_total = self.calculate_cart_total(items=items)
        credit_limit = self.get_user_credit_limit(user_id=user_id)
        resolved_credit_limit_id = credit_limit_id or credit_limit.credit_limit_id
        if credit_limit_id is not None:
            validate_identifier(credit_limit_id, field_name="credit_limit_id")
        return CheckoutPayloadResult(
            user_id=user_id,
            credit_limit_id=resolved_credit_limit_id,
            total_amount=cart_total.total_amount,
            available_limit=credit_limit.available_limit,
            eligible=cart_total.total_amount <= credit_limit.available_limit,
            payload={
                "user_id": user_id,
                "credit_limit_id": resolved_credit_limit_id,
                "items": [item.model_dump(mode="json") for item in cart_total.items],
                "total_amount": cart_total.total_amount,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )

    def create_checkout_intent(
        self,
        *,
        user_id: str,
        items: list[dict[str, Any]],
    ) -> CheckoutIntentResult:
        payload = self.prepare_bnpl_checkout_payload(user_id=user_id, items=items)
        return CheckoutIntentResult(
            checkout_intent_id=build_public_id("checkout-intent", user_id),
            user_id=user_id,
            total_amount=payload.total_amount,
        )

    def add_cart_item(
        self,
        *,
        user_id: str,
        product_id: str,
        quantity: int,
    ) -> FarmerBnplActionPreviewResult:
        validate_identifier(user_id, field_name="user_id")
        item = CartItem(product_id=product_id, quantity=quantity)
        self._get_product(item.product_id)
        return build_action_preview(
            action="add_cart_item",
            user_id=user_id,
            request_payload=item.model_dump(mode="json") | {"user_id": user_id},
        )

    def update_cart_item(
        self,
        *,
        user_id: str,
        product_id: str,
        quantity: int,
    ) -> FarmerBnplActionPreviewResult:
        validate_identifier(user_id, field_name="user_id")
        item = CartItem(product_id=product_id, quantity=quantity)
        self._get_product(item.product_id)
        return build_action_preview(
            action="update_cart_item",
            user_id=user_id,
            request_payload=item.model_dump(mode="json") | {"user_id": user_id},
        )

    def create_bnpl_checkout(
        self,
        *,
        user_id: str,
        checkout_intent_id: str,
        confirmation_token: str | None = None,
    ) -> BnplCheckoutPreviewResult:
        validate_identifier(user_id, field_name="user_id")
        validate_identifier(checkout_intent_id, field_name="checkout_intent_id")
        if confirmation_token is not None:
            validate_identifier(confirmation_token, field_name="confirmation_token")
        return BnplCheckoutPreviewResult(
            checkout_intent_id=checkout_intent_id,
            user_id=user_id,
            safety_notes=[
                "BNPL checkout is prepared as a dry-run preview.",
                "No PG approval or loan drawdown was executed.",
            ],
        )

    def _calculate_cart_total(self, items: list[CartItem]) -> CartTotalResult:
        lines = []
        for item in items:
            product = self._get_product(item.product_id)
            lines.append(
                CartLineResult(
                    product_id=product.product_id,
                    product_name=product.name,
                    quantity=item.quantity,
                    unit_price=product.unit_price,
                    line_total=product.unit_price * item.quantity,
                )
            )
        return CartTotalResult(
            items=lines,
            total_amount=sum(line.line_total for line in lines),
        )

    def _get_product(self, product_id: str) -> ProductResult:
        validate_identifier(product_id, field_name="product_id")
        product = self._repository.get_product(product_id)
        if product is not None:
            return product
        raise FarmerBnplValidationError("Product is not available in the BNPL catalog.")


def validate_identifier(value: str, *, field_name: str) -> None:
    if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value):
        return
    raise FarmerBnplValidationError(f"{field_name} is invalid.")


def build_public_id(prefix: str, user_id: str) -> str:
    if not isinstance(prefix, str) or not prefix:
        raise FarmerBnplValidationError("public id prefix is invalid.")
    if not isinstance(user_id, str) or not user_id:
        raise FarmerBnplValidationError("user_id is invalid.")

    safe_prefix = normalize_public_id_part(prefix)
    safe_user_id = normalize_public_id_part(user_id)
    user_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:PUBLIC_ID_HASH_LENGTH]

    max_prefix_length = PUBLIC_ID_MAX_LENGTH - PUBLIC_ID_HASH_LENGTH - 3
    safe_prefix = safe_prefix[:max_prefix_length].strip("-") or "id"
    max_user_id_length = PUBLIC_ID_MAX_LENGTH - len(safe_prefix) - len(user_hash) - 2
    truncated_user_id = safe_user_id[:max_user_id_length].strip("-") or "id"
    return f"{safe_prefix}-{truncated_user_id}-{user_hash}"


def normalize_public_id_part(value: str) -> str:
    normalized = PUBLIC_ID_DISALLOWED_PATTERN.sub("-", value.lower())
    normalized = PUBLIC_ID_REPEATED_SEPARATOR_PATTERN.sub("-", normalized).strip("-")
    return normalized or "id"


def build_action_preview(
    *,
    action: str,
    user_id: str,
    request_payload: dict[str, Any],
) -> FarmerBnplActionPreviewResult:
    validate_identifier(user_id, field_name="user_id")
    return FarmerBnplActionPreviewResult(
        action=action,
        user_id=user_id,
        request_payload=request_payload,
        safety_notes=[
            "This skeleton records the requested intent only.",
            "No external finance, payment, inventory, or persistence side effect was executed.",
        ],
    )


def parse_cart_items(items: list[dict[str, Any]]) -> list[CartItem]:
    if not items:
        raise FarmerBnplValidationError("Cart items must not be empty.")
    return [CartItem.model_validate(item) for item in items]


def clamp_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise FarmerBnplValidationError("limit must be an integer.")
    return min(max(limit, 1), settings.farmer_bnpl_max_search_limit)


def get_required_document_keys() -> list[str]:
    return [
        item.strip()
        for item in settings.farmer_bnpl_required_documents.split(",")
        if item.strip()
    ]
