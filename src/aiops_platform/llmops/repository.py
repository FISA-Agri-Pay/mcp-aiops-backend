from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from aiops_platform.core.database import SessionLocal
from aiops_platform.llmops.schemas import (
    AgentSnapshotResult,
    ApprovalRequestResult,
    ApprovalStatus,
    LlmRunResult,
    LlmRunStatus,
    NotificationOutboxResult,
    NotificationStatus,
    PromptScope,
    PromptVersionResult,
)


class LlmOpsRepository(Protocol):
    def ensure_prompt_version(
        self,
        *,
        prompt_key: str,
        version: str,
        scope: PromptScope,
        template: str,
    ) -> PromptVersionResult:
        pass

    def list_prompt_versions(
        self,
        *,
        scope: PromptScope | None = None,
        limit: int = 20,
    ) -> list[PromptVersionResult]:
        pass

    def record_llm_run(
        self,
        *,
        provider: str,
        model: str,
        prompt_key: str,
        prompt_version_id: str | None,
        status: LlmRunStatus,
        masked_input: dict[str, Any],
        masked_output: dict[str, Any],
        output_schema: dict[str, Any],
        validation_errors: list[str],
        job_id: str | None = None,
        session_id: str | None = None,
        latency_ms: int = 0,
        last_error: str | None = None,
    ) -> LlmRunResult:
        pass

    def get_llm_run(self, llm_run_id: str) -> LlmRunResult | None:
        pass

    def list_llm_runs(
        self,
        *,
        provider: str | None = None,
        status: LlmRunStatus | None = None,
        limit: int = 20,
    ) -> list[LlmRunResult]:
        pass

    def create_approval_request(
        self,
        *,
        approval_type: str,
        target_type: str,
        reason: str,
        request_payload: dict[str, Any],
        target_id: str | None = None,
        requester_id: str | None = None,
    ) -> ApprovalRequestResult:
        pass

    def list_approval_requests(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 20,
    ) -> list[ApprovalRequestResult]:
        pass

    def create_notification(
        self,
        *,
        channel: str,
        content: str,
        payload: dict[str, Any],
        recipient: str | None = None,
        title: str | None = None,
    ) -> NotificationOutboxResult:
        pass

    def list_notifications(
        self,
        *,
        status: NotificationStatus | None = None,
        limit: int = 20,
    ) -> list[NotificationOutboxResult]:
        pass

    def create_agent_snapshot(
        self,
        *,
        snapshot_type: str,
        job_id: str | None,
        session_id: str | None,
        llm_run_id: str | None,
        payload: dict[str, Any],
    ) -> AgentSnapshotResult:
        pass

    def list_agent_snapshots(
        self,
        *,
        snapshot_type: str | None = None,
        limit: int = 20,
    ) -> list[AgentSnapshotResult]:
        pass


class SqlLlmOpsRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def ensure_prompt_version(
        self,
        *,
        prompt_key: str,
        version: str,
        scope: PromptScope,
        template: str,
    ) -> PromptVersionResult:
        query = text(
            """
            insert into ai.prompt_versions (
                prompt_key,
                prompt_version,
                domain,
                template,
                prompt_metadata,
                prompt_status
            )
            values (
                :prompt_key,
                :version,
                :domain,
                :template,
                '{}'::jsonb,
                'ACTIVE'
            )
            on conflict (prompt_key, prompt_version) do update
            set template = excluded.template,
                prompt_status = 'ACTIVE'
            returning
                public_id::text as prompt_version_id,
                prompt_key,
                prompt_version,
                domain,
                template,
                prompt_status,
                created_at::text as created_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "prompt_key": prompt_key,
                    "version": version,
                    "domain": db_prompt_scope(scope),
                    "template": template,
                },
            ).mappings().one()
        return build_prompt_version(row)

    def list_prompt_versions(
        self,
        *,
        scope: PromptScope | None = None,
        limit: int = 20,
    ) -> list[PromptVersionResult]:
        query = text(
            """
            select
                public_id::text as prompt_version_id,
                prompt_key,
                prompt_version,
                domain,
                template,
                prompt_status,
                created_at::text as created_at
            from ai.prompt_versions
            where (
                cast(:domain as text) is null
                or domain = cast(:domain as text)
            )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {"domain": db_prompt_scope(scope) if scope else None, "limit": limit},
            ).mappings().all()
        return [build_prompt_version(row) for row in rows]

    def record_llm_run(
        self,
        *,
        provider: str,
        model: str,
        prompt_key: str,
        prompt_version_id: str | None,
        status: LlmRunStatus,
        masked_input: dict[str, Any],
        masked_output: dict[str, Any],
        output_schema: dict[str, Any],
        validation_errors: list[str],
        job_id: str | None = None,
        session_id: str | None = None,
        latency_ms: int = 0,
        last_error: str | None = None,
    ) -> LlmRunResult:
        query = text(
            """
            insert into ai.llm_runs (
                job_run_public_id,
                session_public_id,
                prompt_version_public_id,
                domain,
                purpose,
                provider,
                model,
                temperature,
                latency_ms,
                masked_input,
                raw_output,
                parsed_output,
                run_status,
                last_error
            )
            values (
                cast(:job_id as uuid),
                cast(:session_id as uuid),
                cast(:prompt_version_id as uuid),
                :domain,
                :purpose,
                :provider,
                :model,
                0.0,
                :latency_ms,
                cast(:masked_input as jsonb),
                cast(:masked_output as jsonb),
                cast(:parsed_output as jsonb),
                :status,
                :last_error
            )
            returning
                public_id::text as llm_run_id,
                job_run_public_id::text as job_id,
                session_public_id::text as session_id,
                prompt_version_public_id::text as prompt_version_id,
                domain,
                purpose,
                provider,
                model,
                latency_ms,
                masked_input,
                raw_output,
                parsed_output,
                run_status,
                last_error,
                created_at::text as created_at
            """
        )
        domain, purpose = infer_domain_and_purpose(prompt_key)
        parsed_output = {
            **masked_output,
            "output_schema": output_schema,
            "validation_errors": validation_errors,
            "prompt_key": prompt_key,
        }
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "job_id": job_id,
                    "session_id": session_id,
                    "prompt_version_id": prompt_version_id,
                    "domain": domain,
                    "purpose": purpose,
                    "provider": provider,
                    "model": model,
                    "latency_ms": latency_ms,
                    "masked_input": to_json(masked_input),
                    "masked_output": to_json(masked_output),
                    "parsed_output": to_json(parsed_output),
                    "status": status,
                    "last_error": last_error,
                },
            ).mappings().one()
        return build_llm_run(row)

    def get_llm_run(self, llm_run_id: str) -> LlmRunResult | None:
        query = base_llm_run_query("where public_id = cast(:llm_run_id as uuid)")
        with self._session_scope() as session:
            row = session.execute(query, {"llm_run_id": llm_run_id}).mappings().first()
        return build_llm_run(row) if row is not None else None

    def list_llm_runs(
        self,
        *,
        provider: str | None = None,
        status: LlmRunStatus | None = None,
        limit: int = 20,
    ) -> list[LlmRunResult]:
        query = base_llm_run_query(
            """
            where (
                cast(:provider as text) is null
                or provider = cast(:provider as text)
            )
              and (
                  cast(:status as text) is null
                  or run_status = cast(:status as text)
              )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {"provider": provider, "status": status, "limit": limit},
            ).mappings().all()
        return [build_llm_run(row) for row in rows]

    def create_approval_request(
        self,
        *,
        approval_type: str,
        target_type: str,
        reason: str,
        request_payload: dict[str, Any],
        target_id: str | None = None,
        requester_id: str | None = None,
    ) -> ApprovalRequestResult:
        query = text(
            """
            insert into ai.approval_requests (
                requester_user_public_id,
                approval_type,
                target_table,
                target_public_id,
                approval_status,
                request_payload
            )
            values (
                cast(:requester_id as uuid),
                :approval_type,
                :target_type,
                cast(:target_id as uuid),
                'PENDING',
                cast(:request_payload as jsonb)
            )
            returning
                public_id::text as approval_request_id,
                approval_type,
                target_table,
                target_public_id::text as target_id,
                requester_user_public_id::text as requester_id,
                approval_status,
                request_payload,
                created_at::text as created_at
            """
        )
        payload = {**request_payload, "reason": reason}
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "requester_id": requester_id,
                    "approval_type": approval_type,
                    "target_type": target_type,
                    "target_id": target_id,
                    "request_payload": to_json(payload),
                },
            ).mappings().one()
        return build_approval_request(row)

    def list_approval_requests(
        self,
        *,
        status: ApprovalStatus | None = None,
        limit: int = 20,
    ) -> list[ApprovalRequestResult]:
        query = text(
            """
            select
                public_id::text as approval_request_id,
                approval_type,
                target_table,
                target_public_id::text as target_id,
                requester_user_public_id::text as requester_id,
                approval_status,
                request_payload,
                created_at::text as created_at
            from ai.approval_requests
            where (
                cast(:status as text) is null
                or approval_status = cast(:status as text)
            )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {"status": status, "limit": limit},
            ).mappings().all()
        return [build_approval_request(row) for row in rows]

    def create_notification(
        self,
        *,
        channel: str,
        content: str,
        payload: dict[str, Any],
        recipient: str | None = None,
        title: str | None = None,
    ) -> NotificationOutboxResult:
        query = text(
            """
            insert into ai.notification_outbox (
                notification_channel,
                target_recipient,
                title,
                content,
                message_payload,
                send_status
            )
            values (
                :channel,
                :recipient,
                :title,
                :content,
                cast(:payload as jsonb),
                'PENDING'
            )
            returning
                public_id::text as notification_id,
                notification_channel,
                target_recipient,
                send_status,
                message_payload,
                retry_count,
                created_at::text as created_at,
                last_error
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "channel": channel,
                    "recipient": recipient,
                    "title": title,
                    "content": content,
                    "payload": to_json(payload),
                },
            ).mappings().one()
        return build_notification(row)

    def list_notifications(
        self,
        *,
        status: NotificationStatus | None = None,
        limit: int = 20,
    ) -> list[NotificationOutboxResult]:
        query = text(
            """
            select
                public_id::text as notification_id,
                notification_channel,
                target_recipient,
                send_status,
                message_payload,
                retry_count,
                created_at::text as created_at,
                last_error
            from ai.notification_outbox
            where (
                cast(:status as text) is null
                or send_status = cast(:status as text)
            )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {"status": status, "limit": limit},
            ).mappings().all()
        return [build_notification(row) for row in rows]

    def create_agent_snapshot(
        self,
        *,
        snapshot_type: str,
        job_id: str | None,
        session_id: str | None,
        llm_run_id: str | None,
        payload: dict[str, Any],
    ) -> AgentSnapshotResult:
        query = text(
            """
            insert into ai.observability_snapshots (
                snapshot_type,
                time_start,
                time_end,
                snapshot_status,
                masked,
                summary,
                created_by_job_public_id
            )
            values (
                :snapshot_type,
                current_timestamp,
                current_timestamp,
                'COMPLETED',
                true,
                :summary,
                cast(:job_id as uuid)
            )
            returning
                public_id::text as snapshot_id,
                snapshot_type,
                snapshot_status,
                created_by_job_public_id::text as job_id,
                created_at::text as created_at
            """
        )
        summary = f"Agent snapshot for {snapshot_type}: {len(payload)} payload fields."
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {
                    "snapshot_type": db_snapshot_type(snapshot_type),
                    "summary": summary,
                    "job_id": job_id,
                },
            ).mappings().one()
        return AgentSnapshotResult(
            snapshot_id=row["snapshot_id"],
            snapshot_type=api_snapshot_type(row["snapshot_type"]),
            job_id=row["job_id"],
            session_id=session_id,
            llm_run_id=llm_run_id,
            snapshot_status=row["snapshot_status"],
            payload=payload,
            created_at=row["created_at"],
        )

    def list_agent_snapshots(
        self,
        *,
        snapshot_type: str | None = None,
        limit: int = 20,
    ) -> list[AgentSnapshotResult]:
        query = text(
            """
            select
                public_id::text as snapshot_id,
                snapshot_type,
                snapshot_status,
                created_by_job_public_id::text as job_id,
                summary,
                created_at::text as created_at
            from ai.observability_snapshots
            where (
                cast(:snapshot_type as text) is null
                or snapshot_type = cast(:snapshot_type as text)
            )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "snapshot_type": db_snapshot_type(snapshot_type) if snapshot_type else None,
                    "limit": limit,
                },
            ).mappings().all()
        return [
            AgentSnapshotResult(
                snapshot_id=row["snapshot_id"],
                snapshot_type=api_snapshot_type(row["snapshot_type"]),
                job_id=row["job_id"],
                session_id=None,
                llm_run_id=None,
                snapshot_status=row["snapshot_status"],
                payload={"summary": row["summary"]},
                created_at=row["created_at"],
            )
            for row in rows
        ]

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


def build_prompt_version(row) -> PromptVersionResult:
    return PromptVersionResult(
        prompt_version_id=row["prompt_version_id"],
        prompt_key=row["prompt_key"],
        version=row["prompt_version"],
        scope=api_prompt_scope(row["domain"]),
        template=row["template"],
        is_active=row["prompt_status"] == "ACTIVE",
        created_at=row["created_at"],
    )


def build_llm_run(row) -> LlmRunResult:
    parsed_output = row["parsed_output"] or {}
    return LlmRunResult(
        llm_run_id=row["llm_run_id"],
        provider=row["provider"],
        model=row["model"],
        prompt_version_id=row["prompt_version_id"],
        prompt_key=parsed_output.get("prompt_key", api_purpose_prompt_key(row["purpose"])),
        run_status=row["run_status"],
        job_id=row["job_id"],
        session_id=row["session_id"],
        masked_input=row["masked_input"] or {},
        masked_output=row["raw_output"] or {},
        output_schema=parsed_output.get("output_schema", {}),
        validation_errors=parsed_output.get("validation_errors", []),
        latency_ms=row["latency_ms"] or 0,
        created_at=row["created_at"],
        last_error=row["last_error"],
    )


def build_approval_request(row) -> ApprovalRequestResult:
    payload = row["request_payload"] or {}
    return ApprovalRequestResult(
        approval_request_id=row["approval_request_id"],
        approval_type=row["approval_type"],
        target_type=row["target_table"],
        target_id=row["target_id"],
        requester_id=row["requester_id"],
        approval_status=row["approval_status"],
        reason=payload.get("reason", ""),
        request_payload=payload,
        created_at=row["created_at"],
    )


def build_notification(row) -> NotificationOutboxResult:
    return NotificationOutboxResult(
        notification_id=row["notification_id"],
        channel=row["notification_channel"],
        recipient=row["target_recipient"],
        notification_status=row["send_status"],
        payload=row["message_payload"] or {},
        attempts=row["retry_count"] or 0,
        created_at=row["created_at"],
        last_error=row["last_error"],
    )


def base_llm_run_query(where_clause: str):
    return text(
        f"""
        select
            public_id::text as llm_run_id,
            job_run_public_id::text as job_id,
            session_public_id::text as session_id,
            prompt_version_public_id::text as prompt_version_id,
            domain,
            purpose,
            provider,
            model,
            latency_ms,
            masked_input,
            raw_output,
            parsed_output,
            run_status,
            last_error,
            created_at::text as created_at
        from ai.llm_runs
        {where_clause}
        """
    )


def db_prompt_scope(scope: PromptScope) -> str:
    return {
        "farmer_bnpl": "FARMER_BNPL",
        "admin_copilot": "RISKOPS",
        "rca": "INFRAOPS",
        "ops_report": "REPORT",
        "common": "INFRAOPS",
    }[scope]


def api_prompt_scope(domain: str) -> PromptScope:
    return {
        "FARMER_BNPL": "farmer_bnpl",
        "RISKOPS": "admin_copilot",
        "INFRAOPS": "rca",
        "REPORT": "ops_report",
    }.get(domain, "common")


def infer_domain_and_purpose(prompt_key: str) -> tuple[str, str]:
    if prompt_key.startswith("farmer_bnpl"):
        return "FARMER_BNPL", "FARMER_CHAT"
    if prompt_key.startswith("admin_copilot"):
        return "RISKOPS", "RISK_ANALYSIS"
    if prompt_key.startswith("ops_report"):
        return "REPORT", "DAILY_REPORT"
    return "INFRAOPS", "RCA"


def api_purpose_prompt_key(purpose: str) -> str:
    return {
        "FARMER_CHAT": "farmer_bnpl_chat",
        "RISK_ANALYSIS": "admin_copilot",
        "DAILY_REPORT": "ops_report",
        "RCA": "rca",
    }.get(purpose, "common")


def db_snapshot_type(snapshot_type: str) -> str:
    if snapshot_type in {"farmer_bnpl", "farm_advisory"}:
        return "FARM_ADVISORY"
    if snapshot_type in {"admin_copilot", "riskops"}:
        return "RISKOPS"
    if snapshot_type in {"ops_report", "report"}:
        return "REPORT"
    if snapshot_type in {"prediction_scaling", "scaling"}:
        return "PREDICTION_SCALING"
    return "RCA"


def api_snapshot_type(snapshot_type: str) -> str:
    return snapshot_type.lower()


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
