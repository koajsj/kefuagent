from datetime import datetime
from decimal import Decimal
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
    Numeric,
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
    __table_args__ = (UniqueConstraint("user_id", "id", name="uq_auth_sessions_owner"),)
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
        UniqueConstraint(
            "tenant_id", "created_by", "idempotency_key", name="uq_conversations_create_request"
        ),
        CheckConstraint(
            "(idempotency_key IS NULL AND input_digest IS NULL) OR "
            "(idempotency_key IS NOT NULL AND input_digest IS NOT NULL "
            "AND input_digest ~ '^[0-9a-f]{64}$')",
            name="creation_request",
        ),
        CheckConstraint("status IN ('open','closed')", name="status"),
        CheckConstraint(
            "support_state IN ('ai','waiting','human','resolved')", name="support_state"
        ),
        Index("ix_conversations_tenant_created", "tenant_id", "created_at", "id"),
        Index("ix_conversations_queue", "tenant_id", "support_state", "created_at", "id"),
        Index("ix_conversations_assignee", "tenant_id", "assignee_id", "created_at"),
        ForeignKeyConstraint(
            ["tenant_id", "assignee_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_conversations_assignee_membership",
        ),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="priority"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint(
            "jsonb_typeof(tags) = 'array' AND jsonb_array_length(tags) <= 10", name="tags"
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    subject: Mapped[str] = mapped_column(String(160), default="新会话", server_default="新会话")
    # Nullable only for historical rows and independently authenticated visitor creation.
    idempotency_key: Mapped[UUID | None]
    input_digest: Mapped[str | None] = mapped_column(String(64))
    support_state: Mapped[str] = mapped_column(String(16), default="ai", server_default="ai")
    assignee_id: Mapped[UUID | None]
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    category: Mapped[str] = mapped_column(String(80), default="", server_default="")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    human_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ever_human: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    @property
    def sla(self):
        from support_agent.services.operations import service_times

        return service_times(self)


class AgentKnowledgeBase(Record, Base):
    __tablename__ = "agent_knowledge_bases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_config_id", "knowledge_base_id"),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["knowledge_bases.tenant_id", "knowledge_bases.id"],
            ondelete="CASCADE",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    agent_config_id: Mapped[UUID]
    knowledge_base_id: Mapped[UUID]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class Message(Record, Base):
    __tablename__ = "messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.conversation_id", "model_calls.id"],
            name="fk_messages_call_conversation",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        UniqueConstraint(
            "tenant_id", "conversation_id", "id", name="uq_messages_conversation_identity"
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
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="true")
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
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "generation",
            "position",
            "id",
            name="uq_document_chunks_version_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "document_id",
            "generation",
            "root_chunk_id",
            "revision",
            name="uq_document_chunks_revision",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id", "generation", "position", "root_chunk_id"],
            [
                "document_chunks.tenant_id",
                "document_chunks.document_id",
                "document_chunks.generation",
                "document_chunks.position",
                "document_chunks.id",
            ],
            name="fk_document_chunks_root",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "revised_by"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_document_chunks_editor",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("position >= 0 AND generation > 0", name="position"),
        CheckConstraint("page IS NULL OR page > 0", name="page"),
        CheckConstraint(
            "revision > 0 AND ((revision = 1) = (root_chunk_id = id))", name="revision"
        ),
        Index(
            "ix_document_chunks_current",
            "tenant_id",
            "document_id",
            "generation",
            "position",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("ix_document_chunks_search", "search_vector", postgresql_using="gin"),
        Index("ix_document_chunks_chinese", "chinese_vector", postgresql_using="gin"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    document_id: Mapped[UUID]
    position: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer)
    root_chunk_id: Mapped[UUID]
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    revised_by: Mapped[UUID | None]
    revision_reason: Mapped[str | None] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(200))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, content)", persisted=True)
    )
    chinese_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple'::regconfig, support_cjk_bigrams(content))", persisted=True),
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
    visitor_session_id: Mapped[UUID | None]
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id", "id", name="uq_model_calls_conversation"),
        UniqueConstraint("tenant_id", "agent_config_id", "id", name="uq_model_calls_agent"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "visitor_session_id"],
            [
                "visitor_sessions.tenant_id",
                "visitor_sessions.conversation_id",
                "visitor_sessions.id",
            ],
            name="fk_model_calls_visitor_conversation",
        ),
        CheckConstraint(
            "visitor_session_id IS NULL OR conversation_id IS NOT NULL", name="visitor_conversation"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "visitor_session_id"],
            ["visitor_sessions.tenant_id", "visitor_sessions.id"],
            name="fk_model_calls_visitor_session_id_visitor_sessions",
        ),
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
        CheckConstraint(
            "kind IN ('chat','connection_test','agent','tool_execution','embedding','search','draft')",
            name="kind",
        ),
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
    phase: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    reserved_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    @property
    def usage_complete(self):
        return (
            all(s.get("usage_complete", False) for s in self.steps)
            if self.steps
            else self.attempts == 0
        )


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
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.conversation_id", "model_calls.id"],
            name="fk_tool_executions_call_conversation",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.agent_config_id", "model_calls.id"],
            name="fk_tool_executions_call_agent",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_tool_executions_tenant_identity"),
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


class PublicRoute(Record, Base):
    """Minimal public locator only; all delivery/configuration data stays behind RLS."""

    __tablename__ = "public_routes"
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)


class Publication(Record, Timestamped, Base):
    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "id"],
            ["public_routes.tenant_id", "public_routes.id"],
            name="fk_publications_tenant_route",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        CheckConstraint("version >= 1 AND agent_version >= 1", name="version"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    agent_config_id: Mapped[UUID]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    agent_version: Mapped[int] = mapped_column(Integer)
    public_tool_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VisitorSession(Record, Base):
    __tablename__ = "visitor_sessions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id", "id", name="uq_visitor_sessions_scope"),
        ForeignKeyConstraint(
            ["tenant_id", "publication_id", "site_id"],
            ["widget_sites.tenant_id", "widget_sites.publication_id", "widget_sites.id"],
            name="fk_visitor_sessions_publication_site",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_visitor_sessions_identity"),
        UniqueConstraint("tenant_id", "conversation_id", name="uq_visitor_sessions_conversation"),
        ForeignKeyConstraint(
            ["tenant_id", "publication_id"], ["publications.tenant_id", "publications.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["widget_sites.tenant_id", "widget_sites.id"]
        ),
        CheckConstraint("turn_count >= 0", name="turn_count"),
        Index("ix_visitor_sessions_rate", "tenant_id", "publication_id", "ip_hash", "created_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    publication_id: Mapped[UUID]
    publication_version: Mapped[int] = mapped_column(Integer)
    conversation_id: Mapped[UUID]
    site_id: Mapped[UUID | None]
    site_version: Mapped[int | None] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    ip_hash: Mapped[str] = mapped_column(String(64))
    turn_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Collaboration(Record, Base):
    __tablename__ = "conversation_collaboration"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("kind IN ('note','assignment','handling','metadata')", name="kind"),
        Index("ix_collaboration_history", "tenant_id", "conversation_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[UUID]
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(String(4000), default="", server_default="")
    details: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class ConversationSummary(Record, Base):
    __tablename__ = "conversation_summaries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.conversation_id", "model_calls.id"],
            name="fk_conversation_summaries_call_conversation",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "conversation_id", "version"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "source_start_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
            name="fk_summary_source_start",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "source_end_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
            name="fk_summary_source_end",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("version > 0 AND source_count > 0", name="range"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(String(6000))
    source_start_id: Mapped[UUID]
    source_end_id: Mapped[UUID]
    source_count: Mapped[int] = mapped_column(Integer)
    model_call_id: Mapped[UUID]
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)


class VisitorFeedback(Record, Timestamped, Base):
    __tablename__ = "visitor_feedback"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "visitor_session_id"],
            [
                "visitor_sessions.tenant_id",
                "visitor_sessions.conversation_id",
                "visitor_sessions.id",
            ],
            name="fk_visitor_feedback_session_conversation",
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "visitor_session_id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "visitor_session_id"],
            ["visitor_sessions.tenant_id", "visitor_sessions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("rating IN ('satisfied','dissatisfied')", name="rating"),
        Index("ix_visitor_feedback_tenant_created", "tenant_id", "created_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[UUID]
    visitor_session_id: Mapped[UUID]
    rating: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str] = mapped_column(String(1000), default="", server_default="")


class HttpBucket(Base):
    """Global admission metadata only: HMAC keys, counters and expiring random leases."""

    __tablename__ = "http_buckets"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class UserMemoryConsent(Record, Timestamped, Base):
    __tablename__ = "user_memory_consents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("version > 0", name="version"),
    )
    tenant_id: Mapped[UUID]
    user_id: Mapped[UUID]
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class UserMemory(Record, Timestamped, Base):
    __tablename__ = "user_memories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "memory_key"),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "source_conversation_id", "source_message_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("version > 0", name="version"),
        Index("ix_user_memories_expiry", "tenant_id", "user_id", "expires_at"),
    )
    tenant_id: Mapped[UUID]
    user_id: Mapped[UUID]
    memory_key: Mapped[str] = mapped_column(String(80))
    quote: Mapped[str] = mapped_column(String(300))
    source_conversation_id: Mapped[UUID]
    source_message_id: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationReadCursor(Record, Timestamped, Base):
    __tablename__ = "conversation_read_cursors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id", "user_id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "message_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="CASCADE",
        ),
    )
    tenant_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    user_id: Mapped[UUID]
    message_id: Mapped[UUID]


class Customer(Record, Timestamped, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_identity"),
        UniqueConstraint("tenant_id", "external_ref", name="uq_customers_external_ref"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_customers_request_key"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint("status IN ('active','archived')", name="status"),
        Index("ix_customers_tenant_updated", "tenant_id", "updated_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    external_ref: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(40))
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    notes: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    idempotency_key: Mapped[UUID]
    input_digest: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class ConversationCustomer(Record, Base):
    __tablename__ = "conversation_customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "conversation_id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[UUID]
    customer_id: Mapped[UUID]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))


class Ticket(Record, Timestamped, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tickets_tenant_identity"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_tickets_request_key"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "assignee_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
        ),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint("status IN ('open','in_progress','resolved','closed')", name="status"),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="priority"),
        Index("ix_tickets_queue", "tenant_id", "status", "due_at", "id"),
        Index("ix_tickets_customer", "tenant_id", "customer_id", "created_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[UUID | None]
    customer_id: Mapped[UUID | None]
    assignee_id: Mapped[UUID | None]
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    idempotency_key: Mapped[UUID]
    input_digest: Mapped[str] = mapped_column(String(64))


class TicketEvent(Record, Base):
    __tablename__ = "ticket_events"
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "ticket_id"], ["tickets.tenant_id", "tickets.id"]),
        Index("ix_ticket_events_history", "tenant_id", "ticket_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    ticket_id: Mapped[UUID]
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict] = mapped_column(JSONB)


class StaffNotification(Record, Base):
    __tablename__ = "staff_notifications"
    __table_args__ = (
        UniqueConstraint("tenant_id", "ticket_id", "user_id", "ticket_version", "kind"),
        ForeignKeyConstraint(["tenant_id", "ticket_id"], ["tickets.tenant_id", "tickets.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["tenant_memberships.tenant_id", "tenant_memberships.user_id"]
        ),
        Index("ix_staff_notifications_inbox", "tenant_id", "user_id", "created_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[UUID]
    ticket_id: Mapped[UUID]
    ticket_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConversationAttachment(Record, Base):
    __tablename__ = "conversation_attachments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "visitor_session_id"],
            [
                "visitor_sessions.tenant_id",
                "visitor_sessions.conversation_id",
                "visitor_sessions.id",
            ],
            name="fk_conversation_attachments_visitor_conversation",
        ),
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "visitor_session_id"],
            ["visitor_sessions.tenant_id", "visitor_sessions.id"],
        ),
        CheckConstraint("status IN ('pending','ready','failed')", name="status"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name="size"),
        Index(
            "ix_conversation_attachments_history",
            "tenant_id",
            "conversation_id",
            "created_at",
            "id",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[UUID]
    visitor_session_id: Mapped[UUID | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class CustomerMemory(Record, Timestamped, Base):
    __tablename__ = "customer_memories"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_customer_memories_tenant_identity"),
        UniqueConstraint(
            "tenant_id",
            "customer_id",
            "source_message_id",
            "digest",
            name="uq_customer_memories_source_digest",
        ),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
        ForeignKeyConstraint(
            ["tenant_id", "source_conversation_id", "source_message_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
        ),
        CheckConstraint("version > 0", name="version"),
        Index("ix_customer_memories_lifecycle", "tenant_id", "customer_id", "expires_at", "id"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    customer_id: Mapped[UUID]
    source_conversation_id: Mapped[UUID]
    source_message_id: Mapped[UUID]
    confirmed_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str | None] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class ErasureRequest(Record, Timestamped, Base):
    __tablename__ = "erasure_requests"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject_type", "subject_id"),
        CheckConstraint("subject_type IN ('user','customer','conversation')", name="subject_type"),
        CheckConstraint(
            "status IN ('REQUESTED','ACCESS_BLOCKED','DEPENDENCY_CHECK','PURGING','PURGED','BLOCKED')",
            name="status",
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(24), default="REQUESTED")
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    assessment: Mapped[dict] = mapped_column(JSONB)


class ToolApproval(Record, Timestamped, Base):
    __tablename__ = "tool_approvals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_tool_approvals_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "requested_by", "idempotency_key", name="uq_tool_approvals_request_key"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tool_id"], ["tool_definitions.tenant_id", "tool_definitions.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "execution_id"], ["tool_executions.tenant_id", "tool_executions.id"]
        ),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL','APPROVED','REJECTED','EXPIRED','REVOKED','EXECUTED')",
            name="status",
        ),
        CheckConstraint("decided_by IS NULL OR decided_by <> requested_by", name="separation"),
        Index("ix_tool_approvals_queue", "tenant_id", "status", "expires_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    conversation_id: Mapped[UUID]
    agent_config_id: Mapped[UUID]
    tool_id: Mapped[UUID]
    idempotency_key: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(24), default="PENDING_APPROVAL")
    payload_digest: Mapped[str] = mapped_column(String(64))
    encrypted_arguments: Mapped[str] = mapped_column(Text)
    binding: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String(1000))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    execution_id: Mapped[UUID | None] = mapped_column(unique=True)


class BudgetPolicy(Record, Timestamped, Base):
    __tablename__ = "budget_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        CheckConstraint(
            "run_limit >= 0 AND daily_limit >= 0 AND monthly_limit >= 0 AND total_limit >= 0",
            name="limits",
        ),
        CheckConstraint("version > 0", name="version"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    currency: Mapped[str] = mapped_column(String(3))
    run_limit: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    daily_limit: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    monthly_limit: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    total_limit: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    agent_limits: Mapped[dict] = mapped_column(JSONB, default=dict)
    price_catalog_digest: Mapped[str] = mapped_column(String(64))


class CostReservation(Record, Base):
    __tablename__ = "cost_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.agent_config_id", "model_calls.id"],
            name="fk_cost_reservations_call_agent",
        ),
        UniqueConstraint("tenant_id", "model_call_id", "step_index"),
        ForeignKeyConstraint(
            ["tenant_id", "model_call_id"], ["model_calls.tenant_id", "model_calls.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        CheckConstraint("reserved >= 0 AND charged >= 0", name="amounts"),
        CheckConstraint(
            "status IN ('RESERVED','SETTLED','RELEASED','UNKNOWN','OVERRUN')", name="status"
        ),
        Index("ix_cost_reservations_accounting", "tenant_id", "created_at", "status"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    model_call_id: Mapped[UUID]
    agent_config_id: Mapped[UUID]
    step_index: Mapped[int] = mapped_column(Integer)
    policy_version: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    reserved: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    charged: Mapped[Decimal] = mapped_column(Numeric(24, 12))
    pricing: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="RESERVED")
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WidgetSite(Record, Timestamped, Base):
    __tablename__ = "widget_sites"
    __table_args__ = (
        UniqueConstraint("tenant_id", "publication_id", "id", name="uq_widget_sites_publication"),
        UniqueConstraint("tenant_id", "id", name="uq_widget_sites_tenant_identity"),
        UniqueConstraint(
            "tenant_id", "publication_id", "origin", name="uq_widget_sites_publication_origin"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "publication_id"], ["publications.tenant_id", "publications.id"]
        ),
        CheckConstraint("version > 0", name="version"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    publication_id: Mapped[UUID]
    origin: Mapped[str] = mapped_column(String(300))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    challenge_hash: Mapped[str] = mapped_column(String(64))
    challenge_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    encrypted_secret: Mapped[str] = mapped_column(Text)


class WidgetBootstrap(Record, Base):
    __tablename__ = "widget_bootstraps"
    __table_args__ = (
        UniqueConstraint("tenant_id", "site_id", "nonce"),
        ForeignKeyConstraint(
            ["tenant_id", "site_id"], ["widget_sites.tenant_id", "widget_sites.id"]
        ),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    site_id: Mapped[UUID]
    site_version: Mapped[int] = mapped_column(Integer)
    publication_version: Mapped[int] = mapped_column(Integer)
    nonce: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeIndex(Record, Timestamped, Base):
    __tablename__ = "knowledge_indexes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["requested_by", "auth_session_id"],
            ["auth_sessions.user_id", "auth_sessions.id"],
            name="fk_knowledge_indexes_request_session",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_knowledge_indexes_tenant_identity"),
        UniqueConstraint("tenant_id", "knowledge_base_id", name="uq_knowledge_indexes_base"),
        ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"], ["knowledge_bases.tenant_id", "knowledge_bases.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        CheckConstraint("state IN ('DISABLED','QUEUED','RUNNING','READY','FAILED')", name="state"),
        CheckConstraint("version > 0", name="version"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    knowledge_base_id: Mapped[UUID]
    agent_config_id: Mapped[UUID]
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    auth_session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id"))
    model: Mapped[str] = mapped_column(String(120))
    endpoint: Mapped[str] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    rerank: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(16), default="DISABLED")
    error_category: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]


class ChunkEmbedding(Record, Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("tenant_id", "index_id", "chunk_id", name="uq_chunk_embeddings_source"),
        ForeignKeyConstraint(
            ["tenant_id", "index_id"], ["knowledge_indexes.tenant_id", "knowledge_indexes.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "chunk_id"], ["document_chunks.tenant_id", "document_chunks.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "model_call_id"], ["model_calls.tenant_id", "model_calls.id"]
        ),
        Index(
            "ix_chunk_embeddings_cosine",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
    from support_agent.vector_type import Vector

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    index_id: Mapped[UUID]
    chunk_id: Mapped[UUID]
    model_call_id: Mapped[UUID]
    index_version: Mapped[int] = mapped_column(Integer)
    content_digest: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list] = mapped_column(Vector())


class CustomerExport(Record, Timestamped, Base):
    __tablename__ = "customer_exports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["requested_by", "auth_session_id"],
            ["auth_sessions.user_id", "auth_sessions.id"],
            name="fk_customer_exports_request_session",
        ),
        UniqueConstraint(
            "tenant_id", "requested_by", "request_key", name="uq_customer_exports_request"
        ),
        ForeignKeyConstraint(["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]),
        CheckConstraint(
            "status IN ('REQUESTED','BUILDING','READY','FAILED','EXPIRED','CLEANUP_BLOCKED','DELETED')",
            name="status",
        ),
        Index("ix_customer_exports_queue", "tenant_id", "status", "expires_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    customer_id: Mapped[UUID]
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    auth_session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id"))
    request_key: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(24), default="REQUESTED")
    scope: Mapped[dict] = mapped_column(JSONB)
    scope_digest: Mapped[str] = mapped_column(String(64))
    parts: Mapped[list] = mapped_column(JSONB, default=list)
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_category: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReplyDraft(Record, Timestamped, Base):
    __tablename__ = "reply_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["requested_by", "auth_session_id"],
            ["auth_sessions.user_id", "auth_sessions.id"],
            name="fk_reply_drafts_request_session",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.conversation_id", "model_calls.id"],
            name="fk_reply_drafts_call_conversation",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.agent_config_id", "model_calls.id"],
            name="fk_reply_drafts_call_agent",
        ),
        UniqueConstraint(
            "tenant_id", "requested_by", "request_key", name="uq_reply_drafts_request"
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "model_call_id"], ["model_calls.tenant_id", "model_calls.id"]
        ),
        ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "sent_message_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
        ),
        CheckConstraint(
            "status IN ('DRAFT','GENERATING','GENERATED','EDITED','ACCEPTED','REJECTED','EXPIRED')",
            name="status",
        ),
        CheckConstraint("version > 0", name="version"),
        Index("ix_reply_drafts_queue", "tenant_id", "status", "created_at"),
    )
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    conversation_id: Mapped[UUID]
    agent_config_id: Mapped[UUID]
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    auth_session_id: Mapped[UUID] = mapped_column(ForeignKey("auth_sessions.id"))
    request_key: Mapped[UUID]
    model_call_id: Mapped[UUID | None]
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    version: Mapped[int] = mapped_column(Integer, default=1)
    context_digest: Mapped[str] = mapped_column(String(64))
    content: Mapped[str] = mapped_column(Text, default="")
    original_content: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    feedback: Mapped[str | None] = mapped_column(String(1000))
    sent_message_id: Mapped[UUID | None]
    error_category: Mapped[str | None] = mapped_column(String(80))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
