from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from aiops_platform.core.database import SessionLocal


@dataclass(frozen=True)
class RiskOpsUserRecord:
    user_id: str
    farmer_name: str
    region: str
    main_crop: str
    credit_limit: int
    used_amount: int
    risk_level: str
    overdue_amount: int
    days_overdue: int
    application_id: str | None = None
    application_status: str | None = None
    application_submitted_at: str | None = None
    bss_score: int | None = None
    farmland_area_hectare: float | None = None
    missing_documents: list[str] | None = None


class AdminRiskOpsRepository(Protocol):
    def list_users(self) -> list[RiskOpsUserRecord]:
        pass

    def list_credit_review_users(self) -> list[RiskOpsUserRecord]:
        pass


class SqlAdminRiskOpsRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def list_users(self) -> list[RiskOpsUserRecord]:
        return self._fetch_users(include_all_applications=True)

    def list_credit_review_users(self) -> list[RiskOpsUserRecord]:
        return self._fetch_users(include_all_applications=False)

    def _fetch_users(self, *, include_all_applications: bool) -> list[RiskOpsUserRecord]:
        status_filter = "" if include_all_applications else "where cla.status = 'PENDING'"
        query = text(
            f"""
            with latest_bss as (
                select distinct on (user_public_id)
                    user_public_id,
                    coalesce(total_score, monthly_score, annual_score) as score
                from core.bss_scores
                order by user_public_id, calculated_at desc nulls last, created_at desc
            ),
            overdue as (
                select
                    user_public_id,
                    sum(overdue_amount) filter (where resolved_at is null) as overdue_amount,
                    max(overdue_days) filter (where resolved_at is null) as days_overdue
                from core.loan_overdue_ledger
                group by user_public_id
            ),
            documents as (
                select
                    application_id,
                    array_agg(document_type order by document_type) as submitted_documents
                from core.farmer_documents
                group by application_id
            )
            select
                u.public_id::text as user_id,
                u.name as farmer_name,
                coalesce(nullif(fp.farm_address, ''), nullif(u.address, ''), 'UNKNOWN') as region,
                coalesce(fp.main_crop, cl.crop_type_snapshot, 'UNKNOWN') as main_crop,
                coalesce(cl.total_limit, 0) as credit_limit,
                coalesce(cl.used_amount, 0) as used_amount,
                coalesce(o.overdue_amount, 0) as overdue_amount,
                coalesce(o.days_overdue, 0) as days_overdue,
                cla.public_id::text as application_id,
                cla.status as application_status,
                cla.applied_at::text as application_submitted_at,
                lb.score as bss_score,
                fp.field_aream2 as field_aream2,
                coalesce(documents.submitted_documents, array[]::varchar[]) as submitted_documents
            from core.credit_limit_applications cla
            join core.users u on u.id = cla.user_id
            left join core.credit_limits cl on cl.application_public_id = cla.public_id
            left join core.farmer_profiles fp on fp.user_id = u.id
            left join overdue o on o.user_public_id = u.public_id
            left join latest_bss lb on lb.user_public_id = u.public_id
            left join documents on documents.application_id = cla.id
            {status_filter}
            order by cla.applied_at desc nulls last, cla.created_at desc
            """
        )
        with self._session_scope() as session:
            rows = session.execute(query).mappings().all()
        return [build_user_record(row) for row in rows]

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
            return
        with SessionLocal() as session:
            yield session


def build_user_record(row) -> RiskOpsUserRecord:
    credit_limit = to_int(row["credit_limit"])
    used_amount = to_int(row["used_amount"])
    overdue_amount = to_int(row["overdue_amount"])
    days_overdue = int(row["days_overdue"] or 0)
    bss_score = int(row["bss_score"]) if row["bss_score"] is not None else None
    return RiskOpsUserRecord(
        user_id=row["user_id"],
        farmer_name=row["farmer_name"],
        region=normalize_region(row["region"]),
        main_crop=str(row["main_crop"]).lower(),
        credit_limit=credit_limit,
        used_amount=used_amount,
        risk_level=derive_risk_level(
            credit_limit=credit_limit,
            used_amount=used_amount,
            overdue_amount=overdue_amount,
            days_overdue=days_overdue,
            bss_score=bss_score,
        ),
        overdue_amount=overdue_amount,
        days_overdue=days_overdue,
        application_id=row["application_id"],
        application_status=row["application_status"],
        application_submitted_at=row["application_submitted_at"],
        bss_score=bss_score,
        farmland_area_hectare=field_area_to_hectare(row["field_aream2"]),
        missing_documents=missing_documents(row["submitted_documents"] or []),
    )


def normalize_region(value: str) -> str:
    return str(value).strip().split()[0].lower() or "unknown"


def to_int(value: Decimal | int | float | None) -> int:
    return int(value or 0)


def field_area_to_hectare(value: Decimal | int | float | None) -> float | None:
    if value is None:
        return None
    return round(float(value) / 10_000, 4)


def missing_documents(submitted_documents: list[str]) -> list[str]:
    required = {
        "identity_verification",
        "farmer_registration",
        "farmland_document",
        "crop_plan",
        "insurance_certificate",
    }
    submitted = {item.lower() for item in submitted_documents}
    return sorted(required - submitted)


def derive_risk_level(
    *,
    credit_limit: int,
    used_amount: int,
    overdue_amount: int,
    days_overdue: int,
    bss_score: int | None,
) -> str:
    utilization = used_amount / credit_limit if credit_limit else 0
    if overdue_amount >= 500_000 or days_overdue >= 15 or utilization >= 0.85:
        return "HIGH"
    if days_overdue > 0 or utilization >= 0.6 or (bss_score is not None and bss_score < 700):
        return "MEDIUM"
    return "LOW"
