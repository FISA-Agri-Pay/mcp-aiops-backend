from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

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
    OverdueStatusResult,
    ProductDetailResult,
    ProductResult,
    ProductSearchResult,
    RepaymentScheduleItem,
    RepaymentScheduleResult,
    RequiredDocumentsResult,
    UserCreditLimitResult,
)


class FarmerBnplValidationError(ValueError):
    pass


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
DEFAULT_REQUIRED_DOCUMENTS = [
    "identity_verification",
    "farmer_registration",
    "farmland_document",
    "crop_plan",
    "insurance_certificate",
]


PRODUCT_CATALOG = (
    ProductResult(
        product_id="fertilizer-npk-20kg",
        name="NPK 20kg fertilizer",
        category="fertilizer",
        unit_price=28000,
        vendor="AgriMart",
        stock_status="IN_STOCK",
    ),
    ProductResult(
        product_id="fertilizer-organic-20kg",
        name="Organic 20kg fertilizer",
        category="fertilizer",
        unit_price=24000,
        vendor="GreenSupply",
        stock_status="IN_STOCK",
    ),
    ProductResult(
        product_id="seed-rice-10kg",
        name="Rice seed 10kg",
        category="seed",
        unit_price=36000,
        vendor="SeedBank",
        stock_status="LOW_STOCK",
    ),
    ProductResult(
        product_id="pesticide-safe-1l",
        name="Low-toxicity pesticide 1L",
        category="pesticide",
        unit_price=18000,
        vendor="FarmCare",
        stock_status="IN_STOCK",
    ),
)


class FarmerBnplService:
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
            required_documents=list(DEFAULT_REQUIRED_DOCUMENTS),
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
            documents=list(DEFAULT_REQUIRED_DOCUMENTS),
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
        total_limit = 3_000_000
        used_amount = 450_000
        return UserCreditLimitResult(
            user_id=user_id,
            credit_limit_id=build_public_id("limit", user_id),
            total_limit=total_limit,
            used_amount=used_amount,
            available_limit=total_limit - used_amount,
        )

    def get_farmer_profile(self, *, user_id: str) -> FarmerProfileResult:
        validate_identifier(user_id, field_name="user_id")
        return FarmerProfileResult(
            user_id=user_id,
            display_name="Sample farmer",
            region="Jeollabuk-do",
            main_crop="rice",
            profile_status="READY_FOR_REVIEW",
        )

    def get_repayment_schedule(self, *, user_id: str) -> RepaymentScheduleResult:
        validate_identifier(user_id, field_name="user_id")
        today = date.today()
        return RepaymentScheduleResult(
            user_id=user_id,
            schedule=[
                RepaymentScheduleItem(
                    installment_no=1,
                    due_date=(today + timedelta(days=30)).isoformat(),
                    principal_due=300_000,
                    interest_due=12_000,
                    status="UPCOMING",
                ),
                RepaymentScheduleItem(
                    installment_no=2,
                    due_date=(today + timedelta(days=60)).isoformat(),
                    principal_due=300_000,
                    interest_due=9_000,
                    status="UPCOMING",
                ),
            ],
        )

    def get_interest_due(self, *, user_id: str) -> InterestDueResult:
        validate_identifier(user_id, field_name="user_id")
        return InterestDueResult(
            user_id=user_id,
            due_date=(date.today() + timedelta(days=30)).isoformat(),
            interest_due=12_000,
        )

    def get_overdue_status(self, *, user_id: str) -> OverdueStatusResult:
        validate_identifier(user_id, field_name="user_id")
        return OverdueStatusResult(
            user_id=user_id,
            is_overdue=False,
            overdue_amount=0,
            days_overdue=0,
        )

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
        items = [
            product
            for product in PRODUCT_CATALOG
            if product_matches(
                product,
                query=normalized_query,
                category=normalized_category,
            )
        ][:clamped_limit]
        return ProductSearchResult(
            query=query,
            category=category,
            limit=clamped_limit,
            items=items,
        )

    def search_lowest_price_fertilizer(self, *, limit: int = 5) -> ProductSearchResult:
        clamped_limit = clamp_limit(limit)
        items = sorted(
            (product for product in PRODUCT_CATALOG if product.category == "fertilizer"),
            key=lambda product: product.unit_price,
        )[:clamped_limit]
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
        for product in PRODUCT_CATALOG:
            if product.product_id == product_id:
                return product
        raise FarmerBnplValidationError("Product is not available in the BNPL catalog.")


def validate_identifier(value: str, *, field_name: str) -> None:
    if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value):
        return
    raise FarmerBnplValidationError(f"{field_name} is invalid.")


def build_public_id(prefix: str, user_id: str) -> str:
    safe_user_id = user_id.lower().replace("_", "-").replace(".", "-").replace(":", "-")
    return f"{prefix}-{safe_user_id}"


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
    return min(max(limit, 1), 50)


def product_matches(
    product: ProductResult,
    *,
    query: str | None,
    category: str | None,
) -> bool:
    if category is not None and product.category.lower() != category:
        return False
    if query is None:
        return True
    searchable = f"{product.name} {product.category} {product.vendor}".lower()
    return query in searchable
