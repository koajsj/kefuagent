from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Timestamped:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(Record, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active','inactive')", name="status"),
        CheckConstraint("failed_logins >= 0", name="failed_logins"),
    )
    login: Mapped[str] = mapped_column(String(160), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Record, Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Tenant(Record, Timestamped, Base):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint("status IN ('active','inactive')", name="status"),)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")


class Membership(Record, Timestamped, Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint("role IN ('admin','member')", name="role"),
        CheckConstraint("status IN ('active','inactive')", name="status"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")


class AgentConfig(Record, Timestamped, Base):
    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        UniqueConstraint("tenant_id", "id", name="uq_agent_configs_tenant_identity"),
        CheckConstraint("version > 0", name="version"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    provider: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(120))
    runtime: Mapped[dict] = mapped_column(JSONB)
    behavior: Mapped[dict] = mapped_column(JSONB)
    credential_ref: Mapped[str | None] = mapped_column(String(80))
    base_url: Mapped[str | None] = mapped_column(String(500))


class Conversation(Record, Timestamped, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint("status IN ('open','closed')", name="status"),
        Index("ix_conversations_tenant_created", "tenant_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")


class Message(Record, Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        CheckConstraint("role IN ('user','assistant','tool')", name="role"),
        CheckConstraint("source IN ('manual','rag','agent')", name="source"),
        CheckConstraint(
            "(source IN ('rag','agent')) = (model_call_id IS NOT NULL)", name="source_call"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "model_call_id"], ["model_calls.tenant_id", "model_calls.id"]
        ),
        Index("ix_messages_history", "tenant_id", "conversation_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    conversation_id: Mapped[UUID]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="manual", server_default="manual")
    model_call_id: Mapped[UUID | None]
    tool_call_id: Mapped[str | None] = mapped_column(String(128))
    message_metadata: Mapped[dict] = mapped_column("metadata", JSONB)


class ToolDefinition(Record, Timestamped, Base):
    __tablename__ = "tool_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key"),
        UniqueConstraint("tenant_id", "id", name="uq_tool_definitions_tenant_identity"),
        CheckConstraint("risk_level IN ('low','medium','high')", name="risk_level"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint("execution_type IN ('unbound','read_only','write')", name="execution_type"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000))
    parameters: Mapped[dict] = mapped_column(JSONB)
    risk_level: Mapped[str] = mapped_column(String(16))
    permissions: Mapped[list] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    execution_type: Mapped[str] = mapped_column(
        String(16), default="unbound", server_default="unbound"
    )
    output_schema: Mapped[dict | None] = mapped_column(JSONB)


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("outcome IN ('success','failure','rejected')", name="outcome"),
        Index("ix_audit_tenant_created", "tenant_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(60))
    resource_id: Mapped[UUID | None]
    request_id: Mapped[UUID] = mapped_column(index=True)
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))


class KnowledgeBase(Record, Timestamped, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_bases_tenant_identity"),
        UniqueConstraint("tenant_id", "name", name="uq_knowledge_bases_tenant_name"),
        CheckConstraint("status IN ('active','deleting')", name="status"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(2000), default="")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")


class Document(Record, Timestamped, Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_documents_tenant_identity"),
        UniqueConstraint("tenant_id", "knowledge_base_id", "sha256", name="uq_documents_content"),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"], ["knowledge_bases.tenant_id", "knowledge_bases.id"]
        ),
        CheckConstraint(
            "status IN ('pending','processing','ready','failed','deleting')", name="status"
        ),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name="size"),
        CheckConstraint("chunk_count >= 0 AND generation >= 0", name="counts"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    knowledge_base_id: Mapped[UUID]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    error_category: Mapped[str | None] = mapped_column(String(80))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    processing_token: Mapped[UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(Record, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("document_id", "position"),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("position >= 0 AND generation > 0", name="position"),
        CheckConstraint("page IS NULL OR page > 0", name="page"),
        Index("ix_document_chunks_search", "search_vector", postgresql_using="gin"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, content)", persisted=True)
    )


class ModelCredential(Record, Timestamped, Base):
    __tablename__ = "model_credentials"
    __table_args__ = (UniqueConstraint("tenant_id", "ref"),)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    ref: Mapped[str] = mapped_column(String(80))
    encrypted_secret: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ModelCall(Record, Timestamped, Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_model_calls_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "conversation_id", "idempotency_key", name="uq_model_calls_idempotency"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        CheckConstraint(
            "status IN ('running','answered','unresolved','failed','connected')", name="status"
        ),
        CheckConstraint("kind IN ('chat','connection_test','agent','tool_execution')", name="kind"),
        CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0) AND attempts >= 0",
            name="usage",
        ),
        Index(
            "ix_model_calls_active_conversation",
            "tenant_id",
            "conversation_id",
            unique=True,
            postgresql_where=text("status = 'running' AND conversation_id IS NOT NULL"),
        ),
        Index("ix_model_calls_tenant_created", "tenant_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[UUID | None]
    agent_config_id: Mapped[UUID]
    config_version: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(20))
    idempotency_key: Mapped[UUID | None]
    input_digest: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[UUID] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    error_category: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int | None] = mapped_column(Integer, default=0, server_default="0")
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    steps: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))


class AgentTool(Record, Timestamped, Base):
    __tablename__ = "agent_tools"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_config_id", "tool_id"),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tool_id"], ["tool_definitions.tenant_id", "tool_definitions.id"]
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    agent_config_id: Mapped[UUID]
    tool_id: Mapped[UUID]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class ToolExecution(Record, Base):
    __tablename__ = "tool_executions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "model_call_id", "tool_call_id"),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "model_call_id"], ["model_calls.tenant_id", "model_calls.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tool_id"], ["tool_definitions.tenant_id", "tool_definitions.id"]
        ),
        CheckConstraint(
            "status IN ('running','succeeded','failed','timed_out','denied')", name="status"
        ),
        Index("ix_tool_executions_tenant_created", "tenant_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    model_call_id: Mapped[UUID]
    agent_config_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    tool_id: Mapped[UUID | None]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[UUID]
    tool_call_id: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[int | None] = mapped_column(Integer)
    argument_digest: Mapped[str] = mapped_column(String(64))
    argument_summary: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16))
    error_category: Mapped[str | None] = mapped_column(String(80))
    delivery_error: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[dict | None] = mapped_column(JSONB)
