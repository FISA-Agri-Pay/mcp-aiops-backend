import pytest
from sqlalchemy import text

from aiops_platform.core.database import SessionLocal
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


def test_latest_order_delivery_status_returns_latest_order() -> None:
    order_id = "90000000-0000-0000-0000-000000000201"
    with SessionLocal() as session:
        session.execute(
            text(
                """
                insert into core.orders (
                    public_id,
                    user_public_id,
                    payment_request_public_id,
                    total_amount,
                    order_status,
                    delivery_status,
                    recipient_name,
                    recipient_phone,
                    delivery_address,
                    delivery_zip_code,
                    ordered_at,
                    created_at,
                    updated_at
                ) values (
                    cast(:order_id as uuid),
                    cast(:user_id as uuid),
                    '92000000-0000-0000-0000-000000000201',
                    50000.00,
                    'CONFIRMED',
                    'PREPARING',
                    'Sample farmer',
                    '010-1111-2222',
                    'jeonbuk',
                    '55000',
                    timestamp '2026-06-06 10:00:00',
                    timestamp '2026-06-06 10:00:00',
                    timestamp '2026-06-06 10:00:00'
                )
                on conflict (public_id) do update set
                    delivery_status = excluded.delivery_status,
                    ordered_at = excluded.ordered_at,
                    updated_at = excluded.updated_at
                """
            ),
            {"order_id": order_id, "user_id": FARMER_1_ID},
        )
        session.commit()
    try:
        delivery = FarmerBnplService().get_latest_order_delivery_status(
            user_id=FARMER_1_ID
        )

        assert delivery.order_id == order_id
        assert delivery.delivery_status == "PREPARING"
        assert delivery.total_amount == 50_000
    finally:
        with SessionLocal() as session:
            session.execute(
                text(
                    """
                    delete from core.orders
                    where public_id = cast(:order_id as uuid)
                    """
                ),
                {"order_id": order_id},
            )
            session.commit()


def test_repayment_schedule_status_uses_business_priority() -> None:
    order_id = "90000000-0000-0000-0000-000000000001"
    principal_id = "91000000-0000-0000-0000-000000000001"
    with SessionLocal() as session:
        session.execute(
            text(
                """
                insert into core.orders (
                    public_id,
                    user_public_id,
                    payment_request_public_id,
                    total_amount,
                    order_status,
                    delivery_status,
                    recipient_name,
                    recipient_phone,
                    delivery_address,
                    delivery_zip_code,
                    ordered_at,
                    created_at,
                    updated_at
                ) values (
                    cast(:order_id as uuid),
                    cast(:user_id as uuid),
                    '92000000-0000-0000-0000-000000000001',
                    1000.00,
                    'CONFIRMED',
                    'PREPARING',
                    'Sample farmer',
                    '010-1111-2222',
                    'jeonbuk',
                    '55000',
                    timestamp '2026-06-05 00:00:00',
                    timestamp '2026-06-05 00:00:00',
                    timestamp '2026-06-05 00:00:00'
                )
                on conflict (public_id) do nothing
                """
            ),
            {"order_id": order_id, "user_id": FARMER_1_ID},
        )
        session.execute(
            text(
                """
                insert into core.principal_repayment_ledger (
                    public_id,
                    credit_limit_public_id,
                    order_public_id,
                    due_date,
                    principal_amount,
                    amount_paid,
                    status,
                    created_at,
                    updated_at
                ) values (
                    cast(:principal_id as uuid),
                    'c0000001-0000-0000-0000-000000000001',
                    cast(:order_id as uuid),
                    date '2026-06-15',
                    1000.00,
                    0.00,
                    'OVERDUE',
                    timestamp '2026-06-05 00:00:00',
                    timestamp '2026-06-05 00:00:00'
                )
                on conflict (public_id) do update set
                    status = excluded.status,
                    due_date = excluded.due_date,
                    updated_at = excluded.updated_at
                """
            ),
            {"principal_id": principal_id, "order_id": order_id},
        )
        session.commit()
    try:
        repayment = FarmerBnplService().get_repayment_schedule(user_id=FARMER_1_ID)

        assert repayment.schedule[0].due_date == "2026-06-15"
        assert repayment.schedule[0].status == "OVERDUE"
    finally:
        with SessionLocal() as session:
            session.execute(
                text(
                    """
                    delete from core.principal_repayment_ledger
                    where public_id = cast(:principal_id as uuid)
                    """
                ),
                {"principal_id": principal_id},
            )
            session.execute(
                text(
                    """
                    delete from core.orders
                    where public_id = cast(:order_id as uuid)
                    """
                ),
                {"order_id": order_id},
            )
            session.commit()


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
