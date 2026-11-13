"""Member-specific read cursors and confirmed personal-memory use metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0012_support_experience"
down_revision = "0011_user_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_memories", sa.Column("last_used_at", sa.DateTime(timezone=True)))
    op.create_table(
        "conversation_read_cursors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "conversation_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "message_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            ondelete="CASCADE",
        ),
    )
    op.execute("ALTER TABLE conversation_read_cursors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversation_read_cursors FORCE ROW LEVEL SECURITY")
    condition = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid AND user_id = nullif(current_setting('app.user_id', true), '')::uuid"
    op.execute(
        f"CREATE POLICY tenant_isolation ON conversation_read_cursors USING ({condition}) WITH CHECK ({condition})"
    )


def downgrade():
    op.drop_table("conversation_read_cursors")
    op.drop_column("user_memories", "last_used_at")
