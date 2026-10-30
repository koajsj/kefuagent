"""tool_execution_engine"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_tool_execution"
down_revision = "0003_runtime_bounds"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_tool_definitions_tenant_identity", "tool_definitions", ["tenant_id", "id"]
    )
    op.create_table(
        "agent_tools",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_config_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
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
            ["created_by"], ["users.id"], name=op.f("fk_agent_tools_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"],
            ["agent_configs.tenant_id", "agent_configs.id"],
            name=op.f("fk_agent_tools_tenant_id_agent_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["tool_definitions.tenant_id", "tool_definitions.id"],
            name=op.f("fk_agent_tools_tenant_id_tool_definitions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_agent_tools_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_tools")),
        sa.UniqueConstraint(
            "tenant_id", "agent_config_id", "tool_id", name=op.f("uq_agent_tools_tenant_id")
        ),
    )
    op.create_index(op.f("ix_agent_tools_tenant_id"), "agent_tools", ["tenant_id"], unique=False)
    op.create_table(
        "tool_executions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("model_call_id", sa.Uuid(), nullable=False),
        sa.Column("agent_config_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=128), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("tool_version", sa.Integer(), nullable=True),
        sa.Column("argument_digest", sa.String(length=64), nullable=False),
        sa.Column("argument_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('running','succeeded','failed','timed_out','denied')",
            name=op.f("ck_tool_executions_status"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_tool_executions_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"],
            ["agent_configs.tenant_id", "agent_configs.id"],
            name=op.f("fk_tool_executions_tenant_id_agent_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_tool_executions_tenant_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.id"],
            name=op.f("fk_tool_executions_tenant_id_model_calls"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["tool_definitions.tenant_id", "tool_definitions.id"],
            name=op.f("fk_tool_executions_tenant_id_tool_definitions"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_tool_executions_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_executions")),
        sa.UniqueConstraint(
            "tenant_id", "model_call_id", "tool_call_id", name=op.f("uq_tool_executions_tenant_id")
        ),
    )
    op.create_index(
        "ix_tool_executions_tenant_created",
        "tool_executions",
        ["tenant_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_executions_tenant_id"), "tool_executions", ["tenant_id"], unique=False
    )
    op.add_column(
        "audit_events",
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("messages", sa.Column("tool_call_id", sa.String(length=128), nullable=True))
    op.add_column(
        "model_calls",
        sa.Column(
            "steps",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "tool_definitions", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "tool_definitions",
        sa.Column("execution_type", sa.String(length=16), server_default="unbound", nullable=False),
    )
    op.add_column(
        "tool_definitions",
        sa.Column("output_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    for name, table, expression in [
        ("ck_messages_source", "messages", "source IN ('manual','rag','agent')"),
        (
            "ck_messages_source_call",
            "messages",
            "(source IN ('rag','agent')) = (model_call_id IS NOT NULL)",
        ),
        (
            "ck_model_calls_kind",
            "model_calls",
            "kind IN ('chat','connection_test','agent','tool_execution')",
        ),
    ]:
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, expression)
    op.create_check_constraint(
        op.f("ck_tool_definitions_version"), "tool_definitions", "version > 0"
    )
    op.create_check_constraint(
        op.f("ck_tool_definitions_execution_type"),
        "tool_definitions",
        "execution_type IN ('unbound','read_only','write')",
    )
    for table in ("agent_tools", "tool_executions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({scope}) WITH CHECK ({scope})"
        )


def downgrade():
    raise RuntimeError(
        "P3 execution history must be archived and a reviewed downgrade written before reverting"
    )
