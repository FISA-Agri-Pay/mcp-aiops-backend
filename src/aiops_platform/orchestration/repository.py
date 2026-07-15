from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from aiops_platform.core.database import SessionLocal
from aiops_platform.mcp.masking import mask_payload
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.schemas import McpToolCallStatus, McpToolPermission
from aiops_platform.orchestration.schemas import (
    ChatMessageResult,
    ChatMessagesResult,
    ChatSessionResult,
    ChatStatus,
    ChatType,
    JobResult,
    JobStatus,
    McpToolCallResult,
    MessageRole,
)

logger = logging.getLogger(__name__)


class OrchestrationRepository(Protocol):
    def create_chat_session(
        self,
        *,
        chat_type: ChatType,
        user_id: str,
        title: str | None = None,
    ) -> ChatSessionResult:
        pass

    def get_chat_session(self, session_id: str, *, chat_type: ChatType) -> ChatSessionResult | None:
        pass

    def list_chat_sessions(
        self,
        *,
        chat_type: ChatType,
        user_id: str | None = None,
        status: ChatStatus | None = None,
        limit: int = 20,
    ) -> list[ChatSessionResult]:
        pass

    def list_chat_messages(self, session_id: str) -> ChatMessagesResult:
        pass

    def close_chat_session(self, session_id: str) -> ChatSessionResult | None:
        pass

    def append_message(
        self,
        *,
        session_id: str,
        role: MessageRole,
        content: str,
        mcp_tool_call_ids: list[str] | None = None,
        ui_cards: list[dict[str, Any]] | None = None,
        ui_actions: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessageResult:
        pass

    def touch_chat_session(self, session_id: str) -> None:
        pass

    def create_job(
        self,
        *,
        job_type: str,
        entity_type: str,
        entity_id: str,
        status: JobStatus,
        scheduled_at: str | None = None,
        job_context: dict[str, Any] | None = None,
    ) -> JobResult:
        pass

    def finish_job(
        self,
        *,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
    ) -> JobResult | None:
        pass

    def get_job(self, job_id: str) -> JobResult | None:
        pass

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int = 20,
    ) -> list[JobResult]:
        pass

    def record_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        tool_permission: McpToolPermission,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | list[Any] | None,
        call_status: McpToolCallStatus,
        job_id: str,
        session_id: str,
        latency_ms: int = 0,
        last_error: str | None = None,
    ) -> McpToolCallResult:
        pass

    def attach_llm_run_to_tool_calls(
        self,
        *,
        job_id: str,
        session_id: str,
        llm_run_id: str,
    ) -> None:
        pass

    def get_tool_call(self, tool_call_id: str) -> McpToolCallResult | None:
        pass

    def list_tool_calls(
        self,
        *,
        server_name: str | None = None,
        tool_name: str | None = None,
        permission: McpToolPermission | None = None,
        status: McpToolCallStatus | None = None,
        limit: int = 20,
    ) -> list[McpToolCallResult]:
        pass


class SqlOrchestrationRepository:
    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def create_chat_session(
        self,
        *,
        chat_type: ChatType,
        user_id: str,
        title: str | None = None,
    ) -> ChatSessionResult:
        query = text(
            """
            insert into ai.chat_sessions (
                user_public_id,
                session_type,
                source_type,
                session_status,
                context
            )
            values (
                :user_public_id,
                :session_type,
                'API',
                'OPEN',
                cast(:context as jsonb)
            )
            returning
                public_id::text as session_id,
                session_type,
                session_status,
                context,
                created_at::text as created_at,
                updated_at::text as updated_at
            """
        )
        context = {"chat_type": chat_type, "user_id": user_id, "title": title}
        params = {
            "user_public_id": user_id if is_uuid(user_id) else None,
            "session_type": db_session_type(chat_type),
            "context": to_json(context),
        }
        with self._session_scope(commit=True) as session:
            row = session.execute(query, params).mappings().one()
        return build_chat_session(row)

    def get_chat_session(self, session_id: str, *, chat_type: ChatType) -> ChatSessionResult | None:
        if not is_uuid(session_id):
            return None
        query = text(
            """
            select
                public_id::text as session_id,
                session_type,
                session_status,
                context,
                created_at::text as created_at,
                updated_at::text as updated_at
            from ai.chat_sessions
            where public_id = cast(:session_id as uuid)
              and session_type = :session_type
            limit 1
            """
        )
        with self._session_scope() as session:
            row = session.execute(
                query,
                {"session_id": session_id, "session_type": db_session_type(chat_type)},
            ).mappings().first()
        return build_chat_session(row) if row is not None else None

    def list_chat_sessions(
        self,
        *,
        chat_type: ChatType,
        user_id: str | None = None,
        status: ChatStatus | None = None,
        limit: int = 20,
    ) -> list[ChatSessionResult]:
        query = text(
            """
            select
                cs.public_id::text as session_id,
                cs.session_type,
                cs.session_status,
                cs.context || jsonb_build_object(
                    'user_id',
                    coalesce(
                        nullif(cs.context->>'user_id', ''),
                        cs.user_public_id::text,
                        'unknown'
                    ),
                    'title',
                    coalesce(
                        nullif(cs.context->>'title', ''),
                        left(first_user_message.content, 120),
                        'Admin Copilot chat'
                    )
                ) as context,
                cs.created_at::text as created_at,
                cs.updated_at::text as updated_at
            from ai.chat_sessions cs
            left join lateral (
                select cm.content
                from ai.chat_messages cm
                where cm.session_public_id = cs.public_id
                  and cm.role = 'USER'
                order by cm.created_at
                limit 1
            ) first_user_message on true
            where cs.session_type = :session_type
              and (
                  cast(:status as text) is null
                  or cs.session_status = cast(:status as text)
              )
              and (
                  cast(:user_id as text) is null
                  or cs.context->>'user_id' = cast(:user_id as text)
                  or cs.user_public_id::text = cast(:user_id as text)
              )
            order by cs.updated_at desc, cs.created_at desc, cs.id desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "session_type": db_session_type(chat_type),
                    "user_id": user_id,
                    "status": status,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_chat_session(row) for row in rows]

    def list_chat_messages(self, session_id: str) -> ChatMessagesResult:
        if not is_uuid(session_id):
            return ChatMessagesResult(session_id=session_id, items=[])
        query = text(
            """
            select
                public_id::text as message_id,
                session_public_id::text as session_id,
                role,
                content,
                message_metadata,
                created_at::text as created_at
            from ai.chat_messages
            where session_public_id = cast(:session_id as uuid)
            order by created_at
            """
        )
        with self._session_scope() as session:
            rows = session.execute(query, {"session_id": session_id}).mappings().all()
        return ChatMessagesResult(
            session_id=session_id,
            items=[build_chat_message(row) for row in rows],
        )

    def close_chat_session(self, session_id: str) -> ChatSessionResult | None:
        if not is_uuid(session_id):
            return None
        query = text(
            """
            update ai.chat_sessions
            set session_status = 'CLOSED',
                updated_at = current_timestamp
            where public_id = cast(:session_id as uuid)
            returning
                public_id::text as session_id,
                session_type,
                session_status,
                context,
                created_at::text as created_at,
                updated_at::text as updated_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(query, {"session_id": session_id}).mappings().first()
        return build_chat_session(row) if row is not None else None

    def append_message(
        self,
        *,
        session_id: str,
        role: MessageRole,
        content: str,
        mcp_tool_call_ids: list[str] | None = None,
        ui_cards: list[dict[str, Any]] | None = None,
        ui_actions: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessageResult:
        query = text(
            """
            insert into ai.chat_messages (
                session_public_id,
                role,
                content,
                masked_content,
                message_metadata
            )
            values (
                cast(:session_id as uuid),
                :role,
                :content,
                :content,
                cast(:metadata as jsonb)
            )
            returning
                public_id::text as message_id,
                session_public_id::text as session_id,
                role,
                content,
                message_metadata,
                created_at::text as created_at
            """
        )
        params = {
            "session_id": session_id,
            "role": role,
            "content": content,
            "metadata": to_json(
                {
                    **(metadata or {}),
                    "mcp_tool_call_ids": mcp_tool_call_ids or [],
                    "ui_cards": ui_cards or [],
                    "ui_actions": ui_actions or [],
                }
            ),
        }
        with self._session_scope(commit=True) as session:
            row = session.execute(query, params).mappings().one()
        return build_chat_message(row)

    def touch_chat_session(self, session_id: str) -> None:
        if not is_uuid(session_id):
            return
        query = text(
            """
            update ai.chat_sessions
            set updated_at = current_timestamp
            where public_id = cast(:session_id as uuid)
            """
        )
        with self._session_scope(commit=True) as session:
            session.execute(query, {"session_id": session_id})

    def create_job(
        self,
        *,
        job_type: str,
        entity_type: str,
        entity_id: str,
        status: JobStatus,
        scheduled_at: str | None = None,
        job_context: dict[str, Any] | None = None,
    ) -> JobResult:
        query = text(
            """
            insert into ai.job_runs (
                job_type,
                run_status,
                target_table,
                target_public_id,
                idempotency_key,
                scheduled_at,
                job_context
            )
            values (
                :db_job_type,
                :status,
                :entity_type,
                :entity_id,
                :idempotency_key,
                cast(:scheduled_at as timestamp),
                cast(:job_context as jsonb)
            )
            returning
                public_id::text as job_id,
                job_type,
                run_status,
                target_table,
                target_public_id::text as target_public_id,
                last_error,
                created_at::text as created_at,
                coalesce(finished_at, created_at)::text as updated_at
            """
        )
        params = {
            "db_job_type": db_job_type(job_type),
            "status": status,
            "entity_type": entity_type,
            "entity_id": entity_id if is_uuid(entity_id) else None,
            "idempotency_key": None,
            "scheduled_at": scheduled_at,
            "job_context": json.dumps(job_context or {}, ensure_ascii=False),
        }
        with self._session_scope(commit=True) as session:
            ensure_job_runs_schedule_columns(session)
            row = session.execute(query, params).mappings().one()
        return build_job(row, api_job_type=job_type)

    def finish_job(
        self,
        *,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
    ) -> JobResult | None:
        if not is_uuid(job_id):
            return None
        query = text(
            """
            update ai.job_runs
            set run_status = :status,
                finished_at = current_timestamp,
                last_error = :error_message
            where public_id = cast(:job_id as uuid)
            returning
                public_id::text as job_id,
                job_type,
                run_status,
                target_table,
                target_public_id::text as target_public_id,
                last_error,
                created_at::text as created_at,
                coalesce(finished_at, created_at)::text as updated_at
            """
        )
        with self._session_scope(commit=True) as session:
            row = session.execute(
                query,
                {"job_id": job_id, "status": status, "error_message": error_message},
            ).mappings().first()
        return build_job(row) if row is not None else None

    def get_job(self, job_id: str) -> JobResult | None:
        if not is_uuid(job_id):
            return None
        query = text(
            """
            select
                public_id::text as job_id,
                job_type,
                run_status,
                target_table,
                target_public_id::text as target_public_id,
                last_error,
                created_at::text as created_at,
                coalesce(finished_at, created_at)::text as updated_at
            from ai.job_runs
            where public_id = cast(:job_id as uuid)
            limit 1
            """
        )
        with self._session_scope() as session:
            row = session.execute(query, {"job_id": job_id}).mappings().first()
        return build_job(row) if row is not None else None

    def list_jobs(
        self,
        *,
        status: JobStatus | None = None,
        job_type: str | None = None,
        limit: int = 20,
    ) -> list[JobResult]:
        query = text(
            """
            select
                public_id::text as job_id,
                job_type,
                run_status,
                target_table,
                target_public_id::text as target_public_id,
                last_error,
                created_at::text as created_at,
                coalesce(finished_at, created_at)::text as updated_at
            from ai.job_runs
            where (
                cast(:status as text) is null
                or run_status = cast(:status as text)
            )
              and (
                  cast(:job_type as text) is null
                  or job_type = cast(:job_type as text)
              )
            order by created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "status": status,
                    "job_type": db_job_type(job_type) if job_type else None,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_job(row) for row in rows]

    def record_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        tool_permission: McpToolPermission,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | list[Any] | None,
        call_status: McpToolCallStatus,
        job_id: str,
        session_id: str,
        latency_ms: int = 0,
        last_error: str | None = None,
    ) -> McpToolCallResult:
        policy = resolve_tool_policy(tool_permission)
        with self._session_scope(commit=True) as session:
            server_public_id, tool_public_id = ensure_mcp_tool(
                session,
                server_name=server_name,
                tool_name=tool_name,
                tool_permission=tool_permission,
            )
            row = session.execute(
                text(
                    """
                    insert into ai.mcp_tool_calls (
                        job_run_public_id,
                        session_public_id,
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
                        cast(:session_id as uuid),
                        cast(:server_public_id as uuid),
                        cast(:tool_public_id as uuid),
                        :tool_name,
                        :tool_permission,
                        :confirmation_policy,
                        cast(:request_payload as jsonb),
                        cast(:masked_request_payload as jsonb),
                        cast(:masked_response_payload as jsonb),
                        :call_status,
                        :latency_ms,
                        :last_error
                    )
                    returning
                        public_id::text as tool_call_id,
                        tool_name,
                        tool_permission,
                        confirmation_policy,
                        masked_request_payload,
                        masked_response_payload,
                        call_status,
                        latency_ms,
                        job_run_public_id::text as job_id,
                        session_public_id::text as session_id,
                        llm_run_public_id::text as llm_run_id,
                        created_at::text as created_at,
                        last_error
                    """
                ),
                {
                    "job_id": job_id,
                    "session_id": session_id,
                    "server_public_id": server_public_id,
                    "tool_public_id": tool_public_id,
                    "tool_name": tool_name,
                    "tool_permission": tool_permission,
                    "confirmation_policy": policy.confirmation_policy,
                    "request_payload": to_json(request_payload),
                    "masked_request_payload": to_json(mask_payload(request_payload)),
                    "masked_response_payload": to_json(mask_payload(response_payload)),
                    "call_status": call_status,
                    "latency_ms": latency_ms,
                    "last_error": last_error,
                },
            ).mappings().one()
        return build_tool_call(row, server_name=server_name)

    def attach_llm_run_to_tool_calls(
        self,
        *,
        job_id: str,
        session_id: str,
        llm_run_id: str,
    ) -> None:
        invalid_identifiers = {
            name: value
            for name, value in {
                "job_id": job_id,
                "session_id": session_id,
                "llm_run_id": llm_run_id,
            }.items()
            if not is_uuid(value)
        }
        if invalid_identifiers:
            logger.error(
                "Invalid MCP tool call LLM run link identifiers: %s",
                invalid_identifiers,
            )
            raise ValueError(
                "invalid MCP tool call LLM run link identifiers: "
                f"{invalid_identifiers}"
            )
        query = text(
            """
            update ai.mcp_tool_calls
            set llm_run_public_id = cast(:llm_run_id as uuid)
            where job_run_public_id = cast(:job_id as uuid)
              and session_public_id = cast(:session_id as uuid)
              and llm_run_public_id is null
            """
        )
        with self._session_scope(commit=True) as session:
            session.execute(
                query,
                {
                    "job_id": job_id,
                    "session_id": session_id,
                    "llm_run_id": llm_run_id,
                },
            )

    def get_tool_call(self, tool_call_id: str) -> McpToolCallResult | None:
        if not is_uuid(tool_call_id):
            return None
        query = base_tool_call_query("where mtc.public_id = cast(:tool_call_id as uuid)")
        with self._session_scope() as session:
            row = session.execute(query, {"tool_call_id": tool_call_id}).mappings().first()
        return build_tool_call(row) if row is not None else None

    def list_tool_calls(
        self,
        *,
        server_name: str | None = None,
        tool_name: str | None = None,
        permission: McpToolPermission | None = None,
        status: McpToolCallStatus | None = None,
        limit: int = 20,
    ) -> list[McpToolCallResult]:
        query = base_tool_call_query(
            """
            where (
                cast(:server_name as text) is null
                or ms.server_name = cast(:server_name as text)
            )
              and (
                  cast(:tool_name as text) is null
                  or mtc.tool_name = cast(:tool_name as text)
              )
              and (
                  cast(:permission as text) is null
                  or mtc.tool_permission = cast(:permission as text)
              )
              and (
                  cast(:status as text) is null
                  or mtc.call_status = cast(:status as text)
              )
            order by mtc.created_at desc
            limit :limit
            """
        )
        with self._session_scope() as session:
            rows = session.execute(
                query,
                {
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "permission": permission,
                    "status": status,
                    "limit": limit,
                },
            ).mappings().all()
        return [build_tool_call(row) for row in rows]

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


def ensure_mcp_tool(
    session: Session,
    *,
    server_name: str,
    tool_name: str,
    tool_permission: McpToolPermission,
) -> tuple[str, str]:
    server_row = session.execute(
        text(
            """
            insert into ai.mcp_servers (server_name, display_name, server_metadata)
            values (:server_name, :display_name, cast(:metadata as jsonb))
            on conflict (server_name) do update
            set updated_at = current_timestamp
            returning public_id::text as public_id
            """
        ),
        {
            "server_name": server_name,
            "display_name": server_name.replace("-", " ").title(),
            "metadata": to_json({"source": "runtime_registry"}),
        },
    ).mappings().one()
    tool_row = session.execute(
        text(
            """
            insert into ai.mcp_tools (
                mcp_server_public_id,
                tool_name,
                display_name,
                tool_permission
            )
            values (
                cast(:server_public_id as uuid),
                :tool_name,
                :display_name,
                :tool_permission
            )
            on conflict (mcp_server_public_id, tool_name) do update
            set tool_permission = excluded.tool_permission,
                updated_at = current_timestamp
            returning public_id::text as public_id
            """
        ),
        {
            "server_public_id": server_row["public_id"],
            "tool_name": tool_name,
            "display_name": tool_name.replace("_", " "),
            "tool_permission": tool_permission,
        },
    ).mappings().one()
    return server_row["public_id"], tool_row["public_id"]


def ensure_job_runs_schedule_columns(session: Session) -> None:
    session.execute(
        text("alter table ai.job_runs add column if not exists scheduled_at timestamp")
    )
    session.execute(
        text(
            "alter table ai.job_runs "
            "add column if not exists job_context jsonb not null default '{}'::jsonb"
        )
    )


def build_chat_session(row) -> ChatSessionResult:
    context = row["context"] or {}
    return ChatSessionResult(
        session_id=row["session_id"],
        chat_type=context.get("chat_type") or api_chat_type(row["session_type"]),
        user_id=context.get("user_id") or "unknown",
        title=context.get("title"),
        status=row["session_status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def build_chat_message(row) -> ChatMessageResult:
    metadata = row["message_metadata"] or {}
    return ChatMessageResult(
        message_id=row["message_id"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        mcp_tool_call_ids=metadata.get("mcp_tool_call_ids", []),
        ui_cards=metadata.get("ui_cards", []),
        ui_actions=metadata.get("ui_actions", []),
        metadata=metadata,
    )


def build_job(row, *, api_job_type: str | None = None) -> JobResult:
    return JobResult(
        job_id=row["job_id"],
        job_type=api_job_type or api_job_type_from_db(row["job_type"]),
        status=row["run_status"],
        entity_type=row["target_table"] or "",
        entity_id=row["target_public_id"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_message=row["last_error"],
    )


def build_tool_call(row, *, server_name: str | None = None) -> McpToolCallResult:
    permission = McpToolPermission(row["tool_permission"])
    policy = resolve_tool_policy(permission)
    return McpToolCallResult(
        tool_call_id=row["tool_call_id"],
        server_name=server_name or row["server_name"],
        tool_name=row["tool_name"],
        tool_permission=permission,
        confirmation_policy=row["confirmation_policy"],
        call_status=row["call_status"],
        execution_policy=policy.execution_policy,
        masked_request_payload=row["masked_request_payload"],
        masked_response_payload=row["masked_response_payload"],
        latency_ms=row["latency_ms"] or 0,
        job_id=row["job_id"],
        session_id=row["session_id"],
        llm_run_id=row["llm_run_id"],
        created_at=row["created_at"],
        last_error=row["last_error"],
    )


def base_tool_call_query(where_clause: str):
    return text(
        f"""
        select
            mtc.public_id::text as tool_call_id,
            ms.server_name,
            mtc.tool_name,
            mtc.tool_permission,
            mtc.confirmation_policy,
            mtc.masked_request_payload,
            mtc.masked_response_payload,
            mtc.call_status,
            mtc.latency_ms,
            mtc.job_run_public_id::text as job_id,
            mtc.session_public_id::text as session_id,
            mtc.llm_run_public_id::text as llm_run_id,
            mtc.created_at::text as created_at,
            mtc.last_error
        from ai.mcp_tool_calls mtc
        join ai.mcp_servers ms on ms.public_id = mtc.mcp_server_public_id
        {where_clause}
        """
    )


def db_session_type(chat_type: ChatType) -> str:
    return {
        "farmer_bnpl": "FARMER_BNPL",
        "admin_copilot": "ADMIN_RISKOPS",
        "sre_copilot": "ADMIN_INFRAOPS",
    }[chat_type]


def api_chat_type(session_type: str) -> ChatType:
    return {
        "FARMER_BNPL": "farmer_bnpl",
        "ADMIN_RISKOPS": "admin_copilot",
        "ADMIN_INFRAOPS": "sre_copilot",
        "ONCALL": "sre_copilot",
    }.get(session_type, "admin_copilot")


def db_job_type(job_type: str) -> str:
    return {
        "farmer_chat": "FARMER_CHAT",
        "admin_copilot": "RISK_ANALYSIS",
        "sre_copilot": "ONCALL",
    }.get(job_type, job_type.upper())


def api_job_type_from_db(job_type: str) -> str:
    return {
        "FARMER_CHAT": "farmer_chat",
        "RISK_ANALYSIS": "admin_copilot",
        "ONCALL": "sre_copilot",
    }.get(job_type, job_type.lower())


def is_uuid(value: str | None) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def to_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, default=str)
