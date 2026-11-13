"""Private conversation attachments, separate from published knowledge."""

import sqlalchemy as sa
from alembic import op

revision = "0015_conversation_attachments"
down_revision = "0014_private_service_desk"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_attachments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("visitor_session_id", sa.Uuid()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("filename", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("public", sa.Boolean(), nullable=False, server_default="false"),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "visitor_session_id"],
            ["visitor_sessions.tenant_id", "visitor_sessions.id"],
        ),
        sa.CheckConstraint("status IN ('pending','ready','failed')", name="status"),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 5242880", name="size"),
    )
    op.create_index(
        "ix_conversation_attachments_history",
        "conversation_attachments",
        ["tenant_id", "conversation_id", "created_at", "id"],
    )
    op.execute("ALTER TABLE conversation_attachments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversation_attachments FORCE ROW LEVEL SECURITY")
    condition = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"CREATE POLICY tenant_isolation ON conversation_attachments USING ({condition}) WITH CHECK ({condition})"
    )


def downgrade():
    raise RuntimeError("Attachment files and history require a preservation plan before downgrade")
