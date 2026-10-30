"""phase2_knowledge_rag"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_knowledge_rag"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_agent_configs_tenant_identity", "agent_configs", ["tenant_id", "id"]
    )
    op.create_table(
        "knowledge_bases",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="active", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active','deleting')", name=op.f("ck_knowledge_bases_status")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_knowledge_bases_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_knowledge_bases_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_bases")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_knowledge_bases_tenant_identity")),
        sa.UniqueConstraint("tenant_id", "name", name=op.f("uq_knowledge_bases_tenant_name")),
    )
    op.create_index(
        op.f("ix_knowledge_bases_tenant_id"), "knowledge_bases", ["tenant_id"], unique=False
    )
    op.create_table(
        "model_credentials",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("ref", sa.String(length=80), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_model_credentials_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_model_credentials_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_credentials")),
        sa.UniqueConstraint("tenant_id", "ref", name=op.f("uq_model_credentials_tenant_id")),
    )
    op.create_index(
        op.f("ix_model_credentials_tenant_id"), "model_credentials", ["tenant_id"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=200), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processing_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending','processing','ready','failed','deleting')",
            name=op.f("ck_documents_status"),
        ),
        sa.CheckConstraint(
            "chunk_count >= 0 AND generation >= 0", name=op.f("ck_documents_counts")
        ),
        sa.CheckConstraint(
            "size_bytes > 0 AND size_bytes <= 5242880", name=op.f("ck_documents_size")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_documents_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["knowledge_bases.tenant_id", "knowledge_bases.id"],
            name=op.f("fk_documents_tenant_id_knowledge_bases"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_documents_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_documents_tenant_identity")),
        sa.UniqueConstraint(
            "tenant_id", "knowledge_base_id", "sha256", name=op.f("uq_documents_content")
        ),
    )
    op.create_index(op.f("ix_documents_tenant_id"), "documents", ["tenant_id"], unique=False)
    op.create_table(
        "model_calls",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("agent_config_id", sa.Uuid(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
        sa.Column("input_digest", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('chat','connection_test')", name=op.f("ck_model_calls_kind")),
        sa.CheckConstraint(
            "status IN ('running','answered','unresolved','failed','connected')",
            name=op.f("ck_model_calls_status"),
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) AND (output_tokens IS NULL OR output_tokens >= 0) AND attempts >= 0",
            name=op.f("ck_model_calls_usage"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_model_calls_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"],
            ["agent_configs.tenant_id", "agent_configs.id"],
            name=op.f("fk_model_calls_tenant_id_agent_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_model_calls_tenant_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_model_calls_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_calls")),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "idempotency_key",
            name=op.f("uq_model_calls_idempotency"),
        ),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_model_calls_tenant_identity")),
    )
    op.create_index(
        "ix_model_calls_active_conversation",
        "model_calls",
        ["tenant_id", "conversation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running' AND conversation_id IS NOT NULL"),
    )
    op.create_index(op.f("ix_model_calls_request_id"), "model_calls", ["request_id"], unique=False)
    op.create_index(
        "ix_model_calls_tenant_created",
        "model_calls",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(op.f("ix_model_calls_tenant_id"), "model_calls", ["tenant_id"], unique=False)
    op.create_table(
        "document_chunks",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(length=200), nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, content)", persisted=True),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("page IS NULL OR page > 0", name=op.f("ck_document_chunks_page")),
        sa.CheckConstraint(
            "position >= 0 AND generation > 0", name=op.f("ck_document_chunks_position")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "document_id"],
            ["documents.tenant_id", "documents.id"],
            name=op.f("fk_document_chunks_tenant_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_document_chunks_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
        sa.UniqueConstraint("document_id", "position", name=op.f("uq_document_chunks_document_id")),
        sa.UniqueConstraint("tenant_id", "id", name=op.f("uq_document_chunks_tenant_id")),
    )
    op.create_index(
        "ix_document_chunks_search",
        "document_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        op.f("ix_document_chunks_tenant_id"), "document_chunks", ["tenant_id"], unique=False
    )
    op.add_column("agent_configs", sa.Column("base_url", sa.String(length=500), nullable=True))
    op.add_column(
        "messages",
        sa.Column("source", sa.String(length=16), server_default="manual", nullable=False),
    )
    op.add_column("messages", sa.Column("model_call_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_messages_tenant_id_model_calls"),
        "messages",
        "model_calls",
        ["tenant_id", "model_call_id"],
        ["tenant_id", "id"],
    )
    op.create_check_constraint(op.f("ck_messages_source"), "messages", "source IN ('manual','rag')")
    op.create_check_constraint(
        op.f("ck_messages_source_call"),
        "messages",
        "(source = 'rag') = (model_call_id IS NOT NULL)",
    )
    for table in (
        "knowledge_bases",
        "documents",
        "document_chunks",
        "model_credentials",
        "model_calls",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({scope}) WITH CHECK ({scope})"
        )


def downgrade():
    op.drop_constraint(op.f("ck_messages_source_call"), "messages", type_="check")
    op.drop_constraint(op.f("ck_messages_source"), "messages", type_="check")
    op.drop_constraint(op.f("fk_messages_tenant_id_model_calls"), "messages", type_="foreignkey")
    op.drop_column("messages", "model_call_id")
    op.drop_column("messages", "source")
    op.drop_column("agent_configs", "base_url")
    op.drop_index(op.f("ix_document_chunks_tenant_id"), table_name="document_chunks")
    op.drop_index("ix_document_chunks_search", table_name="document_chunks", postgresql_using="gin")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_model_calls_tenant_id"), table_name="model_calls")
    op.drop_index("ix_model_calls_tenant_created", table_name="model_calls")
    op.drop_index(op.f("ix_model_calls_request_id"), table_name="model_calls")
    op.drop_index(
        "ix_model_calls_active_conversation",
        table_name="model_calls",
        postgresql_where=sa.text("status = 'running' AND conversation_id IS NOT NULL"),
    )
    op.drop_table("model_calls")
    op.drop_index(op.f("ix_documents_tenant_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_model_credentials_tenant_id"), table_name="model_credentials")
    op.drop_table("model_credentials")
    op.drop_index(op.f("ix_knowledge_bases_tenant_id"), table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
    op.drop_constraint("uq_agent_configs_tenant_identity", "agent_configs", type_="unique")
