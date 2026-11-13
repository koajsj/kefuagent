"""Explicit staff-confirmed customer quotations, never inferred model facts."""

import sqlalchemy as sa
from alembic import op

revision = "0016_customer_memory"
down_revision = "0015_conversation_attachments"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_memories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("source_conversation_id", sa.Uuid(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customer_memories_tenant_identity"),
        sa.UniqueConstraint(
            "tenant_id",
            "customer_id",
            "source_message_id",
            "digest",
            name="uq_customer_memories_source_digest",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_conversation_id", "source_message_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
        ),
        sa.CheckConstraint("version > 0", name="version"),
    )
    op.create_index(
        "ix_customer_memories_lifecycle",
        "customer_memories",
        ["tenant_id", "customer_id", "expires_at", "id"],
    )
    op.execute("ALTER TABLE customer_memories ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_memories FORCE ROW LEVEL SECURITY")
    condition = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
    op.execute(
        f"CREATE POLICY tenant_isolation ON customer_memories USING ({condition}) WITH CHECK ({condition})"
    )


def downgrade():
    raise RuntimeError("Customer memory provenance requires a preservation plan before downgrade")
