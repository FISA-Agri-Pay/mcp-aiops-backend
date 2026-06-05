import pytest

from aiops_platform.farmer_bnpl.service import (
    FarmerBnplService,
    FarmerBnplValidationError,
    build_public_id,
)
from tests.seed_constants import (
    FARMER_1_ID,
    FERTILIZER_NPK_ID,
    FERTILIZER_ORGANIC_ID,
    SEED_RICE_ID,
)


def test_start_credit_application_returns_required_documents() -> None:
    service = FarmerBnplService()

    result = service.start_credit_application(
        user_id=FARMER_1_ID,
        requested_amount=1_500_000,
        crop_type="rice",
    )

    assert result.application_id == build_public_id("credit-app", FARMER_1_ID)
    assert result.status == "DRAFT"
    assert result.requested_amount == 1_500_000
    assert "farmland_document" in result.required_documents


def test_farmer_credit_and_repayment_reads_return_skeleton_values() -> None:
    service = FarmerBnplService()

    credit_limit = service.get_user_credit_limit(user_id=FARMER_1_ID)
    repayment = service.get_repayment_schedule(user_id=FARMER_1_ID)
    overdue = service.get_overdue_status(user_id=FARMER_1_ID)

    assert credit_limit.available_limit == 2_550_000
    assert repayment.schedule[0].status == "UPCOMING"
    assert overdue.is_overdue is False


def test_product_search_and_lowest_fertilizer_are_deterministic() -> None:
    service = FarmerBnplService()

    search = service.search_products(query="fertilizer", limit=10)
    lowest = service.search_lowest_price_fertilizer(limit=1)
    detail = service.get_product_detail(product_id=FERTILIZER_ORGANIC_ID)

    assert {item.product_id for item in search.items} == {
        FERTILIZER_NPK_ID,
        FERTILIZER_ORGANIC_ID,
    }
    assert lowest.items[0].product_id == FERTILIZER_ORGANIC_ID
    assert detail.product.unit_price == 24000


def test_cart_total_and_checkout_payload_use_catalog_prices() -> None:
    service = FarmerBnplService()
    items = [
        {"product_id": FERTILIZER_ORGANIC_ID, "quantity": 2},
        {"product_id": SEED_RICE_ID, "quantity": 1},
    ]

    total = service.calculate_cart_total(items=items)
    payload = service.prepare_bnpl_checkout_payload(user_id=FARMER_1_ID, items=items)
    intent = service.create_checkout_intent(user_id=FARMER_1_ID, items=items)

    assert total.total_amount == 84_000
    assert payload.eligible is True
    assert payload.payload["total_amount"] == 84_000
    assert intent.status == "PENDING_USER_CONFIRMATION"


def test_unknown_product_is_rejected_before_checkout_calculation() -> None:
    service = FarmerBnplService()

    with pytest.raises(FarmerBnplValidationError):
        service.calculate_cart_total(items=[{"product_id": "unknown", "quantity": 1}])


def test_non_string_identifier_raises_domain_validation_error() -> None:
    service = FarmerBnplService()

    with pytest.raises(FarmerBnplValidationError, match="user_id is invalid"):
        service.get_user_credit_limit(user_id=123)


def test_public_id_is_length_bounded_and_hash_suffixed() -> None:
    long_user_id = f"Farmer.User:{'A' * 180}"

    public_id = build_public_id("credit-app", long_user_id)

    assert len(public_id) <= 120
    assert public_id.startswith("credit-app-farmer-user-")
    assert public_id.rsplit("-", maxsplit=1)[1].isalnum()
    assert len(public_id.rsplit("-", maxsplit=1)[1]) == 8


def test_public_id_keeps_distinct_hash_for_lossy_normalization_collisions() -> None:
    first = build_public_id("limit", "farmer.a")
    second = build_public_id("limit", "farmer_a")

    assert first != second
