from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from aiops_platform.core.database import SessionLocal
from aiops_platform.farmer_bnpl.schemas import (
    FarmerProfileResult,
    InterestDueResult,
    OverdueStatusResult,
    ProductResult,
    RepaymentScheduleItem,
    UserCreditLimitResult,
)


class FarmerBnplRepository(Protocol):
    def get_user_credit_limit(self, user_id: str) -> UserCreditLimitResult | None:
        pass

    def get_farmer_profile(self, user_id: str) -> FarmerProfileResult | None:
        pass

    def list_repayment_schedule(self, user_id: str) -> list[RepaymentScheduleItem]:
        pass

    def get_interest_due(self, user_id: str) -> InterestDueResult | None:
        pass

    def get_overdue_status(self, user_id: str) -> OverdueStatusResult | None:
        pass

    def list_products(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> list[ProductResult]:
        pass

    def get_product(self, product_id: str) -> ProductResult | None:
        pass


class SqlFarmerBnplRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def get_user_credit_limit(self, user_id: str) -> UserCreditLimitResult | None:
        if not is_uuid(user_id):
            return None
        query = text(
            """
            select
                public_id::text as credit_limit_id,
                total_limit,
                used_amount,
                status
            from core.credit_limits
            where user_public_id = cast(:user_id as uuid)
            order by created_at desc
            limit 1
            """
        )
        with self._session_scope() as session:
            row = session.execute(query, {"user_id": user_id}).mappings().first()
        if row is None:
            return None
        total_limit = to_int(row["total_limit"])
        used_amount = to_int(row["used_amount"])
        return UserCreditLimitResult(
            user_id=user_id,
            credit_limit_id=row["credit_limit_id"],
            total_limit=total_limit,
            used_amount=used_amount,
            available_limit=max(total_limit - used_amount, 0),
            status=map_credit_limit_status(row["status"]),
        )

    def get_farmer_profile(self, user_id: str) -> FarmerProfileResult | None:
        if not is_uuid(user_id):
            return None
        query = text(
            """
            select
                u.name as display_name,
                coalesce(nullif(fp.farm_address, ''), nullif(u.address, ''), 'UNKNOWN') as region,
                coalesce(fp.main_crop, cl.crop_type_snapshot, 'UNKNOWN') as main_crop,
                case
                    when fp.id is not null then 'ACTIVE'
                    when cl.public_id is not null then 'READY_FOR_REVIEW'
                    else 'INCOMPLETE'
                end as profile_status
            from core.users u
            left join core.farmer_profiles fp on fp.user_id = u.id
            left join core.credit_limits cl on cl.user_public_id = u.public_id
            where u.public_id = cast(:user_id as uuid)
            order by cl.created_at desc nulls last
            limit 1
            """
        )
        with self._session_scope() as session:
            row = session.execute(query, {"user_id": user_id}).mappings().first()
        if row is None:
            return None
        return FarmerProfileResult(
            user_id=user_id,
            display_name=row["display_name"],
            region=row["region"],
            main_crop=str(row["main_crop"]).lower(),
            profile_status=row["profile_status"],
        )

    def list_repayment_schedule(self, user_id: str) -> list[RepaymentScheduleItem]:
        if not is_uuid(user_id):
            return []
        query = text(
            """
            with limits as (
                select public_id
                from core.credit_limits
                where user_public_id = cast(:user_id as uuid)
            ),
            principal as (
                select
                    due_date,
                    principal_amount - amount_paid as principal_due,
                    0::numeric as interest_due,
                    status
                from core.principal_repayment_ledger
                where credit_limit_public_id in (select public_id from limits)
            ),
            interest as (
                select
                    due_date,
                    0::numeric as principal_due,
                    interest_amount - amount_paid as interest_due,
                    status
                from core.interest_ledger
                where credit_limit_public_id in (select public_id from limits)
            )
            select
                due_date::text as due_date,
                sum(principal_due) as principal_due,
                sum(interest_due) as interest_due,
                max(status) as status
            from (
                select * from principal
                union all
                select * from interest
            ) entries
            group by due_date
            order by due_date
            """
        )
        with self._session_scope() as session:
            rows = session.execute(query, {"user_id": user_id}).mappings().all()
        return [
            RepaymentScheduleItem(
                installment_no=index + 1,
                due_date=row["due_date"],
                principal_due=to_int(row["principal_due"]),
                interest_due=to_int(row["interest_due"]),
                status=map_repayment_status(row["status"]),
            )
            for index, row in enumerate(rows)
        ]

    def get_interest_due(self, user_id: str) -> InterestDueResult | None:
        if not is_uuid(user_id):
            return None
        query = text(
            """
            select
                il.due_date::text as due_date,
                il.interest_amount - il.amount_paid as interest_due
            from core.interest_ledger il
            join core.credit_limits cl on cl.public_id = il.credit_limit_public_id
            where cl.user_public_id = cast(:user_id as uuid)
              and il.status <> 'PAID'
            order by il.due_date
            limit 1
            """
        )
        with self._session_scope() as session:
            row = session.execute(query, {"user_id": user_id}).mappings().first()
        if row is None:
            return None
        return InterestDueResult(
            user_id=user_id,
            due_date=row["due_date"],
            interest_due=to_int(row["interest_due"]),
        )

    def get_overdue_status(self, user_id: str) -> OverdueStatusResult | None:
        if not is_uuid(user_id):
            return None
        query = text(
            """
            select
                coalesce(sum(overdue_amount), 0) as overdue_amount,
                coalesce(max(overdue_days), 0) as days_overdue
            from core.loan_overdue_ledger
            where user_public_id = cast(:user_id as uuid)
              and resolved_at is null
            """
        )
        with self._session_scope() as session:
            row = session.execute(query, {"user_id": user_id}).mappings().first()
        if row is None:
            return None
        overdue_amount = to_int(row["overdue_amount"])
        days_overdue = int(row["days_overdue"] or 0)
        return OverdueStatusResult(
            user_id=user_id,
            is_overdue=overdue_amount > 0,
            overdue_amount=overdue_amount,
            days_overdue=days_overdue,
        )

    def list_products(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> list[ProductResult]:
        sql = """
            select
                p.public_id::text as product_id,
                p.name,
                coalesce(c.name, 'uncategorized') as category,
                p.price as unit_price,
                coalesce(c.name, 'catalog') as vendor,
                p.stock_quantity,
                p.status
            from catalog.products p
            left join catalog.categories c on c.public_id = p.category_public_id
            where (cast(:category as text) is null or lower(c.name) = cast(:category as text))
              and (
                  cast(:query as text) is null
                  or lower(p.name) like '%' || cast(:query as text) || '%'
                  or lower(coalesce(p.description, '')) like '%' || cast(:query as text) || '%'
                  or lower(coalesce(c.name, '')) like '%' || cast(:query as text) || '%'
              )
            order by p.price asc, p.created_at desc
            limit :limit
        """
        params = {
            "query": query.lower().strip() if query else None,
            "category": category.lower().strip() if category else None,
            "limit": limit,
        }
        with self._session_scope() as session:
            rows = session.execute(text(sql), params).mappings().all()
        return [build_product(row) for row in rows]

    def get_product(self, product_id: str) -> ProductResult | None:
        if not is_uuid(product_id):
            return None
        query = text(
            """
            select
                p.public_id::text as product_id,
                p.name,
                coalesce(c.name, 'uncategorized') as category,
                p.price as unit_price,
                coalesce(c.name, 'catalog') as vendor,
                p.stock_quantity,
                p.status
            from catalog.products p
            left join catalog.categories c on c.public_id = p.category_public_id
            where p.public_id = cast(:product_id as uuid)
            limit 1
            """
        )
        with self._session_scope() as session:
            row = session.execute(query, {"product_id": product_id}).mappings().first()
        if row is None:
            return None
        return build_product(row)

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
            return
        with SessionLocal() as session:
            yield session


def build_product(row) -> ProductResult:
    return ProductResult(
        product_id=row["product_id"],
        name=row["name"],
        category=str(row["category"]).lower(),
        unit_price=to_int(row["unit_price"]),
        vendor=row["vendor"],
        stock_status=map_stock_status(row["status"], int(row["stock_quantity"] or 0)),
    )


def map_credit_limit_status(value: str) -> str:
    if value == "SUSPENDED":
        return "SUSPENDED"
    if value == "ACTIVE":
        return "ACTIVE"
    return "PENDING"


def map_repayment_status(value: str) -> str:
    if value == "PAID":
        return "PAID"
    if value == "OVERDUE":
        return "OVERDUE"
    return "UPCOMING"


def map_stock_status(status: str, stock_quantity: int) -> str:
    if status == "SOLD_OUT" or stock_quantity <= 0:
        return "OUT_OF_STOCK"
    if stock_quantity <= 10:
        return "LOW_STOCK"
    return "IN_STOCK"


def to_int(value: Decimal | int | float | None) -> int:
    return int(value or 0)


def is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True
