from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aiops_platform.models.base import Base


class McpServerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class McpToolPermission(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    USER_CONFIRMED_WRITE = "USER_CONFIRMED_WRITE"
    OPS_WRITE = "OPS_WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class McpToolStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class McpConfirmationPolicy(StrEnum):
    NONE = "NONE"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    ADMIN_APPROVAL = "ADMIN_APPROVAL"
    BLOCKED = "BLOCKED"


class McpToolCallStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


def _check_in(column_name: str, enum_type: type[StrEnum], constraint_name: str) -> CheckConstraint:
    values = ", ".join(f"'{member.value}'" for member in enum_type)
    return CheckConstraint(f"{column_name} IN ({values})", name=constraint_name)


class McpServer(Base):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        _check_in("server_status", McpServerStatus, "ck_ai_mcp_servers_server_status"),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )
    server_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text)
    server_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="ACTIVE")
    server_metadata: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    tools: Mapped[list[McpTool]] = relationship(back_populates="server")


class McpTool(Base):
    __tablename__ = "mcp_tools"
    __table_args__ = (
        UniqueConstraint("mcp_server_public_id", "tool_name"),
        _check_in("tool_permission", McpToolPermission, "ck_ai_mcp_tools_tool_permission"),
        _check_in("tool_status", McpToolStatus, "ck_ai_mcp_tools_tool_status"),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )
    mcp_server_public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ai.mcp_servers.public_id", ondelete="CASCADE"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    tool_permission: Mapped[str] = mapped_column(String(40), nullable=False)
    input_schema: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    output_schema: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    tool_status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )

    server: Mapped[McpServer] = relationship(back_populates="tools")


class McpToolCall(Base):
    __tablename__ = "mcp_tool_calls"
    __table_args__ = (
        _check_in(
            "tool_permission",
            McpToolPermission,
            "ck_ai_mcp_tool_calls_tool_permission",
        ),
        _check_in(
            "confirmation_policy",
            McpConfirmationPolicy,
            "ck_ai_mcp_tool_calls_confirmation_policy",
        ),
        _check_in("call_status", McpToolCallStatus, "ck_ai_mcp_tool_calls_call_status"),
        {"schema": "ai"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        nullable=False,
        unique=True,
        server_default=text("gen_random_uuid()"),
    )
    job_run_public_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    llm_run_public_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    session_public_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    user_public_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    mcp_server_public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ai.mcp_servers.public_id"),
        nullable=False,
    )
    mcp_tool_public_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("ai.mcp_tools.public_id"),
        nullable=False,
    )
    tool_name: Mapped[str] = mapped_column(String(120), nullable=False)
    tool_permission: Mapped[str] = mapped_column(String(40), nullable=False)
    confirmation_policy: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        server_default="NONE",
    )
    request_payload: Mapped[dict | None] = mapped_column(JSONB)
    masked_request_payload: Mapped[dict | None] = mapped_column(JSONB)
    response_ref: Mapped[str | None] = mapped_column(Text)
    masked_response_payload: Mapped[dict | None] = mapped_column(JSONB)
    call_status: Mapped[str] = mapped_column(String(30), nullable=False)
    latency_ms: Mapped[int | None]
    approval_request_public_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    business_ref_public_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
