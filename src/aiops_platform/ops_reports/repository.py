from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from aiops_platform.core.database import SessionLocal
from aiops_platform.mcp.masking import mask_payload
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.schemas import McpToolCallStatus, McpToolPermission
from aiops_platform.ops_reports.schemas import (
    IncludedIncident,
    IncludedRcaReport,
    OpsReportRcaRefResult,
    OpsReportResult,
    ReportIncidentResult,
    ReportMetricSummaryResult,
)
from aiops_platform.orchestration.repository import ensure_mcp_tool


class OpsReportRepository(Protocol):
    def create_ops_report(
        self,
        *,
        report_type: str,
        period_start: datetime,
        period_end: datetime,
        timezone: str,
        title: str,
        summary: str | None,
        sections: list[dict[str, Any]],
        metrics: dict[str, Any],
        llm_run_id: str | None,
        status: str,
    ) -> OpsReportResult:
        pass

    def update_ops_report_status(self, report_id: str, *, status: str) -> OpsReportResult | None:
        pass

    def get_ops_report(self, report_id: str) -> OpsReportResult | None:
        pass

    def list_ops_reports(
        self,
        *,
        report_type: str | None,
        status: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        namespace: str | None,
        service_name: str | None,
        limit: int,
    ) -> list[OpsReportResult]:
        pass

    def list_incidents_for_period(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        namespace: str | None,
        service_name: str | None,
        limit: int,
    ) -> list[IncludedIncident]:
        pass

    def list_rca_reports_for_period(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        namespace: str | None,
        service_name: str | None,
        limit: int,
    ) -> list[IncludedRcaReport]:
        pass

    def add_report_incident(
        self,
        *,
        report_id: str,
        incident_id: str,
        summary: str | None,
    ) -> ReportIncidentResult:
        pass

    def add_report_rca_ref(
        self,
        *,
        report_id: str,
        rca_report_id: str,
        incident_id: str,
        included_reason: str,
    ) -> OpsReportRcaRefResult:
        pass

    def add_metric_summary(
        self,
        *,
        report_id: str,
        source_type: str,
        namespace: str | None,
        service_name: str | None,
        metric_name: str,
        period_start: datetime,
        period_end: datetime,
        summary_values: dict[str, Any],
    ) -> ReportMetricSummaryResult:
        pass

    def list_report_incidents(self, report_id: str) -> list[IncludedIncident]:
        pass

    def list_report_rca_reports(self, report_id: str) -> list[IncludedRcaReport]:
        pass

    def list_report_rca_refs(self, report_id: str) -> list[OpsReportRcaRefResult]:
        pass

    def list_report_metric_summaries(self, report_id: str) -> list[ReportMetricSummaryResult]:
        pass

    def record_mcp_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | list[Any] | None,
        call_status: str,
        job_id: str | None,
        last_error: str | None = None,
    ) -> str:
        pass


class SqlOpsReportRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def create_ops_report(
        self,
        *,
        report_type: str,
        period_start: datetime,
        period_end: datetime,
        timezone: str,
        title: str,
        summary: str | None,
        sections: list[dict[str, Any]],
        metrics: dict[str, Any],
        llm_run_id: str | None,
        status: str,
    ) -> OpsReportResult:
        query = text(
            """
            insert into ai.ops_reports (
                report_type,
                period_start,
                period_end,
                timezone,
                title,
                summary,
                sections,
                metrics,
                llm_run_public_id,
                report_status
            )
            values (
                :report_type,
                :period_start,
                :period_end,
                :timezone,
                :title,
                :summary,
                cast(:sections as jsonb),
                cast(:metrics as jsonb),
                cast(:llm_run_id as uuid),
                :status
            )
            returning
                public_id::text as report_id,
                report_type,
                period_start::text as period_start,
                period_end::text as period_end,
                timezone,
                title,
                summary,
                sections,
                metrics,
                llm_run_public_id::text as llm_run_id,
                report_status,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "report_type": report_type,
                    "period_start": period_start,
                    "period_end": period_end,
                    "timezone": timezone,
                    "title": title,
                    "summary": summary,
                    "sections": to_json(sections),
                    "metrics": to_json(metrics),
                    "llm_run_id": llm_run_id if is_uuid(llm_run_id) else None,
                    "status": status,
                },
            ).mappings().one()
        return build_ops_report(row)

    def update_ops_report_status(self, report_id: str, *, status: str) -> OpsReportResult | None:
        if not is_uuid(report_id):
            return None
        query = base_report_query(
            """
            update ai.ops_reports
            set report_status = :status
            where public_id = cast(:report_id as uuid)
            returning
                public_id::text as report_id,
                report_type,
                period_start::text as period_start,
                period_end::text as period_end,
                timezone,
                title,
                summary,
                sections,
                metrics,
                llm_run_public_id::text as llm_run_id,
                report_status,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {"report_id": report_id, "status": status},
            ).mappings().first()
        return build_ops_report(row) if row is not None else None

    def get_ops_report(self, report_id: str) -> OpsReportResult | None:
        if not is_uuid(report_id):
            return None
        query = base_report_select("where public_id = cast(:report_id as uuid)")
        with self._session_scope() as session:
            row = session.execute(query, {"report_id": report_id}).mappings().first()
        return build_ops_report(row) if row is not None else None

    def list_ops_reports(
        self,
        *,
        report_type: str | None,
        status: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        namespace: str | None,
        service_name: str | None,
        limit: int,
    ) -> list[OpsReportResult]:
        query = base_report_select(
            """
            where (
                cast(:report_type as text) is null
                or report_type = cast(:report_type as text)
            )
              and (
                  cast(:status as text) is null
                  or report_status = cast(:status as text)
              )
              and (
                  cast(:date_from as timestamp) is null
                  or period_end >= cast(:date_from as timestamp)
              )
              and (
                  cast(:date_to as timestamp) is null
                  or period_start < cast(:date_to as timestamp)
              )
              and (
                  cast(:namespace as text) is null
                  or metrics ->> 'namespace' = cast(:namespace as text)
              )
              and (
                  cast(:service_name as text) is null
                  or metrics ->> 'service_name' = cast(:service_name as text)
              )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "report_type": report_type,
                    "status": status,
                    "date_from": date_from,
                    "date_to": date_to,
                    "namespace": namespace,
                    "service_name": service_name,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_ops_report(row) for row in rows]

    def list_incidents_for_period(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        namespace: str | None,
        service_name: str | None,
        limit: int,
    ) -> list[IncludedIncident]:
        query = text(
            """
            select
                public_id::text as incident_id,
                incident_status,
                severity,
                alert_name,
                namespace,
                workload,
                service_name,
                summary,
                starts_at::text as starts_at,
                created_at::text as created_at
            from ai.incidents
            where coalesce(starts_at, created_at) >= :period_start
              and coalesce(starts_at, created_at) < :period_end
              and (
                  cast(:namespace as text) is null
                  or namespace = cast(:namespace as text)
              )
              and (
                  cast(:service_name as text) is null
                  or service_name = cast(:service_name as text)
                  or workload = cast(:service_name as text)
              )
            order by severity desc, coalesce(starts_at, created_at) desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "namespace": namespace,
                    "service_name": service_name,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_included_incident(row) for row in rows]

    def list_rca_reports_for_period(
        self,
        *,
        period_start: datetime,
        period_end: datetime,
        namespace: str | None,
        service_name: str | None,
        limit: int,
    ) -> list[IncludedRcaReport]:
        query = included_rca_query(
            """
            where rr.created_at >= :period_start
              and rr.created_at < :period_end
              and (
                  cast(:namespace as text) is null
                  or i.namespace = cast(:namespace as text)
              )
              and (
                  cast(:service_name as text) is null
                  or i.service_name = cast(:service_name as text)
                  or i.workload = cast(:service_name as text)
              )
            order by rr.created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "namespace": namespace,
                    "service_name": service_name,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_included_rca(row) for row in rows]

    def add_report_incident(
        self,
        *,
        report_id: str,
        incident_id: str,
        summary: str | None,
    ) -> ReportIncidentResult:
        query = text(
            """
            insert into ai.report_incidents (
                report_public_id,
                incident_public_id,
                summary
            )
            values (
                cast(:report_id as uuid),
                cast(:incident_id as uuid),
                :summary
            )
            on conflict (report_public_id, incident_public_id) do update
            set summary = excluded.summary
            returning
                public_id::text as report_incident_id,
                report_public_id::text as report_id,
                incident_public_id::text as incident_id,
                summary,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {"report_id": report_id, "incident_id": incident_id, "summary": summary},
            ).mappings().one()
        return ReportIncidentResult(**row)

    def add_report_rca_ref(
        self,
        *,
        report_id: str,
        rca_report_id: str,
        incident_id: str,
        included_reason: str,
    ) -> OpsReportRcaRefResult:
        query = text(
            """
            insert into ai.ops_report_rca_refs (
                report_public_id,
                rca_report_public_id,
                incident_public_id,
                included_reason
            )
            values (
                cast(:report_id as uuid),
                cast(:rca_report_id as uuid),
                cast(:incident_id as uuid),
                :included_reason
            )
            on conflict (report_public_id, rca_report_public_id) do update
            set included_reason = excluded.included_reason
            returning
                public_id::text as report_rca_ref_id,
                report_public_id::text as report_id,
                rca_report_public_id::text as rca_report_id,
                incident_public_id::text as incident_id,
                included_reason,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "report_id": report_id,
                    "rca_report_id": rca_report_id,
                    "incident_id": incident_id,
                    "included_reason": included_reason,
                },
            ).mappings().one()
        return OpsReportRcaRefResult(**row)

    def add_metric_summary(
        self,
        *,
        report_id: str,
        source_type: str,
        namespace: str | None,
        service_name: str | None,
        metric_name: str,
        period_start: datetime,
        period_end: datetime,
        summary_values: dict[str, Any],
    ) -> ReportMetricSummaryResult:
        query = text(
            """
            insert into ai.report_metric_summaries (
                report_public_id,
                source_type,
                namespace,
                service_name,
                metric_name,
                period_start,
                period_end,
                summary_values
            )
            values (
                cast(:report_id as uuid),
                :source_type,
                :namespace,
                :service_name,
                :metric_name,
                :period_start,
                :period_end,
                cast(:summary_values as jsonb)
            )
            returning
                public_id::text as metric_summary_id,
                report_public_id::text as report_id,
                source_type,
                namespace,
                service_name,
                metric_name,
                period_start::text as period_start,
                period_end::text as period_end,
                summary_values,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "report_id": report_id,
                    "source_type": source_type,
                    "namespace": namespace,
                    "service_name": service_name,
                    "metric_name": metric_name,
                    "period_start": period_start,
                    "period_end": period_end,
                    "summary_values": to_json(summary_values),
                },
            ).mappings().one()
        return build_metric_summary(row)

    def list_report_incidents(self, report_id: str) -> list[IncludedIncident]:
        if not is_uuid(report_id):
            return []
        query = text(
            """
            select
                i.public_id::text as incident_id,
                i.incident_status,
                i.severity,
                i.alert_name,
                i.namespace,
                i.workload,
                i.service_name,
                coalesce(ri.summary, i.summary) as summary,
                i.starts_at::text as starts_at,
                i.created_at::text as created_at
            from ai.report_incidents ri
            join ai.incidents i on i.public_id = ri.incident_public_id
            where ri.report_public_id = cast(:report_id as uuid)
            order by i.created_at desc
            """
        )
        with self._session_scope() as session:
            rows = session.execute(query, {"report_id": report_id}).mappings().all()
        return [build_included_incident(row) for row in rows]

    def list_report_rca_reports(self, report_id: str) -> list[IncludedRcaReport]:
        if not is_uuid(report_id):
            return []
        query = included_rca_query(
            """
            join ai.ops_report_rca_refs ref on ref.rca_report_public_id = rr.public_id
            where ref.report_public_id = cast(:report_id as uuid)
            order by rr.created_at desc
            """
        )
        with self._session_scope() as session:
            rows = session.execute(query, {"report_id": report_id}).mappings().all()
        return [build_included_rca(row) for row in rows]

    def list_report_rca_refs(self, report_id: str) -> list[OpsReportRcaRefResult]:
        if not is_uuid(report_id):
            return []
        query = text(
            """
            select
                public_id::text as report_rca_ref_id,
                report_public_id::text as report_id,
                rca_report_public_id::text as rca_report_id,
                incident_public_id::text as incident_id,
                included_reason,
                created_at::text as created_at
            from ai.ops_report_rca_refs
            where report_public_id = cast(:report_id as uuid)
            order by created_at desc
            """
        )
        with self._session_scope() as session:
            rows = session.execute(query, {"report_id": report_id}).mappings().all()
        return [OpsReportRcaRefResult(**row) for row in rows]

    def list_report_metric_summaries(self, report_id: str) -> list[ReportMetricSummaryResult]:
        if not is_uuid(report_id):
            return []
        query = text(
            """
            select
                public_id::text as metric_summary_id,
                report_public_id::text as report_id,
                source_type,
                namespace,
                service_name,
                metric_name,
                period_start::text as period_start,
                period_end::text as period_end,
                summary_values,
                created_at::text as created_at
            from ai.report_metric_summaries
            where report_public_id = cast(:report_id as uuid)
            order by created_at
            """
        )
        with self._session_scope() as session:
            rows = session.execute(query, {"report_id": report_id}).mappings().all()
        return [build_metric_summary(row) for row in rows]

    def record_mcp_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | list[Any] | None,
        call_status: str,
        job_id: str | None,
        last_error: str | None = None,
    ) -> str:
        permission = McpToolPermission.READ
        policy = resolve_tool_policy(permission)
        with self._session_scope(commit=True) as session:
            server_public_id, tool_public_id = ensure_mcp_tool(
                session,
                server_name=server_name,
                tool_name=tool_name,
                tool_permission=permission,
            )
            row = session.execute(
                text(
                    """
                    insert into ai.mcp_tool_calls (
                        job_run_public_id,
                        mcp_server_public_id,
                        mcp_tool_public_id,
                        tool_name,
                        tool_permission,
                        confirmation_policy,
                        request_payload,
                        masked_request_payload,
                        masked_response_payload,
                        call_status,
                        latency_ms,
                        last_error
                    )
                    values (
                        cast(:job_id as uuid),
                        cast(:server_public_id as uuid),
                        cast(:tool_public_id as uuid),
                        :tool_name,
                        :tool_permission,
                        :confirmation_policy,
                        cast(:request_payload as jsonb),
                        cast(:masked_request_payload as jsonb),
                        cast(:masked_response_payload as jsonb),
                        :call_status,
                        0,
                        :last_error
                    )
                    returning public_id::text as tool_call_id
                    """
                ),
                {
                    "job_id": job_id if is_uuid(job_id) else None,
                    "server_public_id": server_public_id,
                    "tool_public_id": tool_public_id,
                    "tool_name": tool_name,
                    "tool_permission": permission,
                    "confirmation_policy": policy.confirmation_policy,
                    "request_payload": to_json(request_payload),
                    "masked_request_payload": to_json(mask_payload(request_payload)),
                    "masked_response_payload": to_json(mask_payload(response_payload)),
                    "call_status": McpToolCallStatus(call_status),
                    "last_error": last_error,
                },
            ).mappings().one()
        return row["tool_call_id"]

    @contextmanager
    def _session_scope(self, *, commit: bool = False) -> Iterator[Session]:
        if self._session is not None:
            yield self._session
            if commit:
                self._session.commit()
            return
        with SessionLocal() as session:
            yield session
            if commit:
                session.commit()


def base_report_query(query: str):
    return text(query)


def base_report_select(where_clause: str):
    return text(
        f"""
        select
            public_id::text as report_id,
            report_type,
            period_start::text as period_start,
            period_end::text as period_end,
            timezone,
            title,
            summary,
            sections,
            metrics,
            llm_run_public_id::text as llm_run_id,
            report_status,
            created_at::text as created_at
        from ai.ops_reports
        {where_clause}
        """
    )


def included_rca_query(where_clause: str):
    return text(
        f"""
        select
            rr.public_id::text as rca_report_id,
            rr.incident_public_id::text as incident_id,
            rr.report_status,
            rr.summary,
            rr.probable_root_cause,
            rr.confidence,
            rr.created_at::text as created_at
        from ai.rca_reports rr
        join ai.incidents i on i.public_id = rr.incident_public_id
        {where_clause}
        """
    )


def build_ops_report(row) -> OpsReportResult:
    return OpsReportResult(
        report_id=row["report_id"],
        report_type=row["report_type"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        timezone=row["timezone"],
        title=row["title"],
        summary=row["summary"],
        sections=row["sections"] or [],
        metrics=row["metrics"] or {},
        llm_run_id=row["llm_run_id"],
        report_status=row["report_status"],
        created_at=row["created_at"],
    )


def build_included_incident(row) -> IncludedIncident:
    return IncludedIncident(
        incident_id=row["incident_id"],
        status=row["incident_status"],
        severity=row["severity"],
        alert_name=row["alert_name"],
        namespace=row["namespace"],
        workload=row["workload"],
        service_name=row["service_name"],
        summary=row["summary"],
        starts_at=row["starts_at"],
        created_at=row["created_at"],
    )


def build_included_rca(row) -> IncludedRcaReport:
    confidence = row["confidence"]
    return IncludedRcaReport(
        rca_report_id=row["rca_report_id"],
        incident_id=row["incident_id"],
        status=row["report_status"],
        summary=row["summary"],
        probable_root_cause=row["probable_root_cause"],
        confidence=float(confidence) if confidence is not None else None,
        created_at=row["created_at"],
    )


def build_metric_summary(row) -> ReportMetricSummaryResult:
    return ReportMetricSummaryResult(
        metric_summary_id=row["metric_summary_id"],
        report_id=row["report_id"],
        source_type=row["source_type"],
        namespace=row["namespace"],
        service_name=row["service_name"],
        metric_name=row["metric_name"],
        period_start=row["period_start"],
        period_end=row["period_end"],
        summary_values=row["summary_values"] or {},
        created_at=row["created_at"],
    )


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def is_uuid(value: str | None) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True
