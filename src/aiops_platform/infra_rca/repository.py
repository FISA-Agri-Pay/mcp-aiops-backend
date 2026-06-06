from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from aiops_platform.core.database import SessionLocal
from aiops_platform.infra_rca.schemas import (
    IncidentAlertResult,
    IncidentResult,
    ObservabilitySnapshotResult,
    RcaReportResult,
    SnapshotItemResult,
)
from aiops_platform.mcp.masking import mask_payload
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.schemas import McpToolCallStatus, McpToolPermission
from aiops_platform.orchestration.repository import ensure_mcp_tool


class InfraRcaRepository(Protocol):
    def upsert_incident(
        self,
        *,
        dedup_key: str,
        status: str,
        severity: str,
        alert_name: str | None,
        namespace: str | None,
        workload: str | None,
        service_name: str | None,
        summary: str | None,
        labels: dict[str, Any],
        annotations: dict[str, Any],
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> IncidentResult:
        pass

    def upsert_incident_alert(
        self,
        *,
        incident_id: str,
        fingerprint: str,
        status: str,
        event_payload: dict[str, Any],
        labels: dict[str, Any],
        annotations: dict[str, Any],
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> tuple[IncidentAlertResult, bool]:
        pass

    def update_incident_status(self, incident_id: str, *, status: str) -> IncidentResult | None:
        pass

    def create_observability_snapshot(
        self,
        *,
        incident_id: str,
        job_id: str,
        time_start: datetime,
        time_end: datetime,
        summary: str,
    ) -> ObservabilitySnapshotResult:
        pass

    def add_snapshot_item(
        self,
        *,
        snapshot_id: str,
        source_type: str,
        tool_name: str,
        query_text: str | None,
        query_params: dict[str, Any],
        raw_data: dict[str, Any] | list[Any] | None,
        masked_data: dict[str, Any] | list[Any] | None,
        summary: str | None,
        last_error: str | None = None,
    ) -> SnapshotItemResult:
        pass

    def complete_observability_snapshot(
        self,
        snapshot_id: str,
        *,
        status: str,
        summary: str,
    ) -> ObservabilitySnapshotResult | None:
        pass

    def create_rca_report(
        self,
        *,
        incident_id: str,
        llm_run_id: str | None,
        snapshot_id: str | None,
        status: str,
        summary: str | None,
        probable_root_cause: str | None,
        impact: str | None,
        timeline: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        recommended_actions: list[dict[str, Any]],
        confidence: float | None,
        prompt_version: str | None,
    ) -> RcaReportResult:
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


class SqlInfraRcaRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def upsert_incident(
        self,
        *,
        dedup_key: str,
        status: str,
        severity: str,
        alert_name: str | None,
        namespace: str | None,
        workload: str | None,
        service_name: str | None,
        summary: str | None,
        labels: dict[str, Any],
        annotations: dict[str, Any],
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> IncidentResult:
        query = text(
            """
            insert into ai.incidents (
                dedup_key,
                source_type,
                incident_status,
                severity,
                alert_name,
                namespace,
                workload,
                service_name,
                summary,
                labels,
                annotations,
                starts_at,
                ends_at
            )
            values (
                :dedup_key,
                'ALERTMANAGER',
                :status,
                :severity,
                :alert_name,
                :namespace,
                :workload,
                :service_name,
                :summary,
                cast(:labels as jsonb),
                cast(:annotations as jsonb),
                :starts_at,
                :ends_at
            )
            on conflict (dedup_key) do update
            set incident_status = excluded.incident_status,
                severity = excluded.severity,
                alert_name = excluded.alert_name,
                namespace = excluded.namespace,
                workload = excluded.workload,
                service_name = excluded.service_name,
                summary = excluded.summary,
                labels = excluded.labels,
                annotations = excluded.annotations,
                starts_at = coalesce(ai.incidents.starts_at, excluded.starts_at),
                ends_at = excluded.ends_at,
                last_seen_at = current_timestamp,
                updated_at = current_timestamp
            returning
                public_id::text as incident_id,
                dedup_key,
                source_type,
                incident_status,
                severity,
                alert_name,
                namespace,
                workload,
                service_name,
                summary,
                starts_at::text as starts_at,
                ends_at::text as ends_at,
                created_at::text as created_at,
                updated_at::text as updated_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "dedup_key": dedup_key,
                    "status": status,
                    "severity": severity,
                    "alert_name": alert_name,
                    "namespace": namespace,
                    "workload": workload,
                    "service_name": service_name,
                    "summary": summary,
                    "labels": to_json(labels),
                    "annotations": to_json(annotations),
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                },
            ).mappings().one()
        return build_incident(row)

    def upsert_incident_alert(
        self,
        *,
        incident_id: str,
        fingerprint: str,
        status: str,
        event_payload: dict[str, Any],
        labels: dict[str, Any],
        annotations: dict[str, Any],
        starts_at: datetime | None,
        ends_at: datetime | None,
    ) -> tuple[IncidentAlertResult, bool]:
        insert_query = text(
            """
            insert into ai.incident_alerts (
                incident_public_id,
                fingerprint,
                alert_status,
                event_payload,
                labels,
                annotations,
                starts_at,
                ends_at
            )
            values (
                cast(:incident_id as uuid),
                :fingerprint,
                :status,
                cast(:event_payload as jsonb),
                cast(:labels as jsonb),
                cast(:annotations as jsonb),
                :starts_at,
                :ends_at
            )
            on conflict (incident_public_id, fingerprint) do nothing
            returning
                public_id::text as incident_alert_id,
                incident_public_id::text as incident_id,
                fingerprint,
                alert_status,
                starts_at::text as starts_at,
                ends_at::text as ends_at,
                received_at::text as received_at
            """
        )
        update_query = text(
            """
            update ai.incident_alerts
            set alert_status = :status,
                event_payload = cast(:event_payload as jsonb),
                labels = cast(:labels as jsonb),
                annotations = cast(:annotations as jsonb),
                starts_at = :starts_at,
                ends_at = :ends_at
            where incident_public_id = cast(:incident_id as uuid)
              and fingerprint = :fingerprint
            returning
                public_id::text as incident_alert_id,
                incident_public_id::text as incident_id,
                fingerprint,
                alert_status,
                starts_at::text as starts_at,
                ends_at::text as ends_at,
                received_at::text as received_at
            """
        )
        params = {
            "incident_id": incident_id,
            "fingerprint": fingerprint,
            "status": status,
            "event_payload": to_json(event_payload),
            "labels": to_json(labels),
            "annotations": to_json(annotations),
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
        with self._session_scope(commit=True) as session:
            row = session.execute(insert_query, params).mappings().first()
            was_existing = row is None
            if row is None:
                row = session.execute(update_query, params).mappings().one()
        return build_incident_alert(row), was_existing

    def update_incident_status(self, incident_id: str, *, status: str) -> IncidentResult | None:
        if not is_uuid(incident_id):
            return None
        query = text(
            """
            update ai.incidents
            set incident_status = :status,
                updated_at = current_timestamp
            where public_id = cast(:incident_id as uuid)
            returning
                public_id::text as incident_id,
                dedup_key,
                source_type,
                incident_status,
                severity,
                alert_name,
                namespace,
                workload,
                service_name,
                summary,
                starts_at::text as starts_at,
                ends_at::text as ends_at,
                created_at::text as created_at,
                updated_at::text as updated_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {"incident_id": incident_id, "status": status},
            ).mappings().first()
        return build_incident(row) if row is not None else None

    def create_observability_snapshot(
        self,
        *,
        incident_id: str,
        job_id: str,
        time_start: datetime,
        time_end: datetime,
        summary: str,
    ) -> ObservabilitySnapshotResult:
        query = text(
            """
            insert into ai.observability_snapshots (
                incident_public_id,
                snapshot_type,
                time_start,
                time_end,
                snapshot_status,
                masked,
                summary,
                created_by_job_public_id,
                snapshot_payload
            )
            values (
                cast(:incident_id as uuid),
                'RCA',
                :time_start,
                :time_end,
                'COLLECTING',
                true,
                :summary,
                cast(:job_id as uuid),
                cast(:payload as jsonb)
            )
            returning
                public_id::text as snapshot_id,
                incident_public_id::text as incident_id,
                snapshot_type,
                time_start::text as time_start,
                time_end::text as time_end,
                snapshot_status,
                summary,
                created_at::text as created_at
            """
        )
        payload = {"time_start": time_start.isoformat(), "time_end": time_end.isoformat()}
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "incident_id": incident_id,
                    "job_id": job_id,
                    "time_start": time_start,
                    "time_end": time_end,
                    "summary": summary,
                    "payload": to_json(payload),
                },
            ).mappings().one()
        return build_snapshot(row, items=[])

    def add_snapshot_item(
        self,
        *,
        snapshot_id: str,
        source_type: str,
        tool_name: str,
        query_text: str | None,
        query_params: dict[str, Any],
        raw_data: dict[str, Any] | list[Any] | None,
        masked_data: dict[str, Any] | list[Any] | None,
        summary: str | None,
        last_error: str | None = None,
    ) -> SnapshotItemResult:
        data_hash = hash_payload(masked_data if masked_data is not None else raw_data)
        query = text(
            """
            insert into ai.snapshot_items (
                snapshot_public_id,
                source_type,
                tool_name,
                query_text,
                query_params,
                raw_data,
                masked_data,
                summary,
                data_hash,
                last_error
            )
            values (
                cast(:snapshot_id as uuid),
                :source_type,
                :tool_name,
                :query_text,
                cast(:query_params as jsonb),
                cast(:raw_data as jsonb),
                cast(:masked_data as jsonb),
                :summary,
                :data_hash,
                :last_error
            )
            returning
                public_id::text as snapshot_item_id,
                source_type,
                tool_name,
                summary,
                last_error
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "snapshot_id": snapshot_id,
                    "source_type": source_type,
                    "tool_name": tool_name,
                    "query_text": query_text,
                    "query_params": to_json(query_params),
                    "raw_data": to_json(raw_data),
                    "masked_data": to_json(masked_data),
                    "summary": summary,
                    "data_hash": data_hash,
                    "last_error": last_error,
                },
            ).mappings().one()
        return build_snapshot_item(row)

    def complete_observability_snapshot(
        self,
        snapshot_id: str,
        *,
        status: str,
        summary: str,
    ) -> ObservabilitySnapshotResult | None:
        if not is_uuid(snapshot_id):
            return None
        query = text(
            """
            update ai.observability_snapshots
            set snapshot_status = :status,
                summary = :summary
            where public_id = cast(:snapshot_id as uuid)
            returning
                public_id::text as snapshot_id,
                incident_public_id::text as incident_id,
                snapshot_type,
                time_start::text as time_start,
                time_end::text as time_end,
                snapshot_status,
                summary,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {"snapshot_id": snapshot_id, "status": status, "summary": summary},
            ).mappings().first()
        return build_snapshot(row, items=[]) if row is not None else None

    def create_rca_report(
        self,
        *,
        incident_id: str,
        llm_run_id: str | None,
        snapshot_id: str | None,
        status: str,
        summary: str | None,
        probable_root_cause: str | None,
        impact: str | None,
        timeline: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        recommended_actions: list[dict[str, Any]],
        confidence: float | None,
        prompt_version: str | None,
    ) -> RcaReportResult:
        query = text(
            """
            insert into ai.rca_reports (
                incident_public_id,
                llm_run_public_id,
                snapshot_public_id,
                report_status,
                summary,
                probable_root_cause,
                impact,
                timeline,
                evidence,
                recommended_actions,
                confidence,
                prompt_version
            )
            values (
                cast(:incident_id as uuid),
                cast(:llm_run_id as uuid),
                cast(:snapshot_id as uuid),
                :status,
                :summary,
                :probable_root_cause,
                :impact,
                cast(:timeline as jsonb),
                cast(:evidence as jsonb),
                cast(:recommended_actions as jsonb),
                :confidence,
                :prompt_version
            )
            returning
                public_id::text as rca_report_id,
                incident_public_id::text as incident_id,
                llm_run_public_id::text as llm_run_id,
                snapshot_public_id::text as snapshot_id,
                report_status,
                summary,
                probable_root_cause,
                impact,
                timeline,
                evidence,
                recommended_actions,
                confidence,
                prompt_version,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "incident_id": incident_id,
                    "llm_run_id": llm_run_id if is_uuid(llm_run_id) else None,
                    "snapshot_id": snapshot_id if is_uuid(snapshot_id) else None,
                    "status": status,
                    "summary": summary,
                    "probable_root_cause": probable_root_cause,
                    "impact": impact,
                    "timeline": to_json(timeline),
                    "evidence": to_json(evidence),
                    "recommended_actions": to_json(recommended_actions),
                    "confidence": confidence,
                    "prompt_version": prompt_version,
                },
            ).mappings().one()
        return build_rca_report(row)

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


def build_incident(row) -> IncidentResult:
    return IncidentResult(
        incident_id=row["incident_id"],
        dedup_key=row["dedup_key"],
        source_type=row["source_type"],
        status=row["incident_status"],
        severity=row["severity"],
        alert_name=row["alert_name"],
        namespace=row["namespace"],
        workload=row["workload"],
        service_name=row["service_name"],
        summary=row["summary"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def build_incident_alert(row) -> IncidentAlertResult:
    return IncidentAlertResult(
        incident_alert_id=row["incident_alert_id"],
        incident_id=row["incident_id"],
        fingerprint=row["fingerprint"],
        status=row["alert_status"],
        starts_at=row["starts_at"],
        ends_at=row["ends_at"],
        received_at=row["received_at"],
    )


def build_snapshot(row, *, items: list[SnapshotItemResult]) -> ObservabilitySnapshotResult:
    return ObservabilitySnapshotResult(
        snapshot_id=row["snapshot_id"],
        incident_id=row["incident_id"],
        snapshot_type=row["snapshot_type"],
        time_start=row["time_start"],
        time_end=row["time_end"],
        status=row["snapshot_status"],
        summary=row["summary"],
        items=items,
        created_at=row["created_at"],
    )


def build_snapshot_item(row) -> SnapshotItemResult:
    return SnapshotItemResult(
        snapshot_item_id=row["snapshot_item_id"],
        source_type=row["source_type"],
        tool_name=row["tool_name"],
        summary=row["summary"],
        last_error=row["last_error"],
    )


def build_rca_report(row) -> RcaReportResult:
    confidence = row["confidence"]
    return RcaReportResult(
        rca_report_id=row["rca_report_id"],
        incident_id=row["incident_id"],
        llm_run_id=row["llm_run_id"],
        snapshot_id=row["snapshot_id"],
        status=row["report_status"],
        summary=row["summary"],
        probable_root_cause=row["probable_root_cause"],
        impact=row["impact"],
        timeline=row["timeline"] or [],
        evidence=row["evidence"] or [],
        recommended_actions=row["recommended_actions"] or [],
        confidence=float(confidence) if confidence is not None else None,
        prompt_version=row["prompt_version"],
        created_at=row["created_at"],
    )


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def hash_payload(value: Any) -> str:
    return hashlib.sha256(to_json(value).encode("utf-8")).hexdigest()


def is_uuid(value: str | None) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True
