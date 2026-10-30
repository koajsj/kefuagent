"""Version-pinned public delivery and scoped anonymous sessions."""

import sqlalchemy as sa
from alembic import op

revision = "0008_public_delivery"
down_revision = "0007_workspace"
branch_labels = None
depends_on = None


def upgrade():
    # Definitions are frozen in this migration; never import live application models.
    op.create_table(
        "public_routes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_public_routes_tenant_id", "public_routes", ["tenant_id"])
    op.create_table(
        "publications",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("public_routes.id"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("agent_config_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("agent_version", sa.Integer(), nullable=False),
        sa.Column(
            "public_tool_ids", sa.dialects.postgresql.JSONB(), server_default="[]", nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
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
        sa.UniqueConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        sa.CheckConstraint("version >= 1 AND agent_version >= 1", name="version"),
    )
    op.create_index("ix_publications_tenant_id", "publications", ["tenant_id"])
    op.create_table(
        "visitor_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("publication_version", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("ip_hash", sa.String(64), nullable=False),
        sa.Column("turn_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_visitor_sessions_identity"),
        sa.UniqueConstraint(
            "tenant_id", "conversation_id", name="uq_visitor_sessions_conversation"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "publication_id"], ["publications.tenant_id", "publications.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        sa.CheckConstraint("turn_count >= 0", name="turn_count"),
    )
    op.create_index("ix_visitor_sessions_tenant_id", "visitor_sessions", ["tenant_id"])
    op.create_index(
        "ix_visitor_sessions_rate",
        "visitor_sessions",
        ["tenant_id", "publication_id", "ip_hash", "created_at"],
    )
    op.add_column("model_calls", sa.Column("visitor_session_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_model_calls_visitor_session_id_visitor_sessions",
        "model_calls",
        "visitor_sessions",
        ["tenant_id", "visitor_session_id"],
        ["tenant_id", "id"],
    )
    for table in ["publications", "visitor_sessions"]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({scope}) WITH CHECK ({scope})"
        )


def downgrade():
    raise RuntimeError("Review data preservation before removing public delivery history")
