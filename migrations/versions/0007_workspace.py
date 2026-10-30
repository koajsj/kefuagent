"""workspace knowledge grants and conversation handling"""

import sqlalchemy as sa
from alembic import op

revision = "0007_workspace"
down_revision = "0006_p4_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "conversations",
        sa.Column("subject", sa.String(160), nullable=False, server_default="新会话"),
    )
    op.add_column(
        "conversations",
        sa.Column("support_state", sa.String(16), nullable=False, server_default="ai"),
    )
    op.create_check_constraint(
        "support_state", "conversations", "support_state IN ('ai','waiting','human','resolved')"
    )
    op.execute("""DO $$ DECLARE tid uuid; BEGIN
      FOR tid IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', tid::text, true);
        UPDATE conversations SET support_state='resolved' WHERE tenant_id=tid AND status='closed';
      END LOOP;
      PERFORM set_config('app.tenant_id', '', true);
    END $$""")
    op.create_table(
        "agent_knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("agent_config_id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "agent_config_id", "knowledge_base_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "agent_config_id"], ["agent_configs.tenant_id", "agent_configs.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "knowledge_base_id"],
            ["knowledge_bases.tenant_id", "knowledge_bases.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_agent_knowledge_bases_tenant_id", "agent_knowledge_bases", ["tenant_id"])
    op.execute("ALTER TABLE agent_knowledge_bases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_knowledge_bases FORCE ROW LEVEL SECURITY")
    scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"CREATE POLICY tenant_isolation ON agent_knowledge_bases USING ({scope}) WITH CHECK ({scope})"
    )


def downgrade():
    raise RuntimeError("Review a data-preserving downgrade before removing workspace state")
