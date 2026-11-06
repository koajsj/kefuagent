"""Opt-in, source-linked user memory; isolated by both tenant and authenticated user."""

import sqlalchemy as sa
from alembic import op

revision = "0011_user_memory"
down_revision = "0010_http_ingress"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("user_memory_consents", "user_memories"):
        common = [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("tenant_id", sa.Uuid(), nullable=False),
            sa.Column("user_id", sa.Uuid(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["tenant_id", "user_id"],
                ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
                ondelete="CASCADE",
            ),
            sa.CheckConstraint("version > 0", name=op.f(f"ck_{name}_version")),
        ]
        if name == "user_memory_consents":
            op.create_table(
                name,
                *common,
                sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.UniqueConstraint("tenant_id", "user_id"),
            )
        else:
            op.create_table(
                name,
                *common,
                sa.Column("memory_key", sa.String(80), nullable=False),
                sa.Column("quote", sa.String(300), nullable=False),
                sa.Column("source_conversation_id", sa.Uuid(), nullable=False),
                sa.Column("source_message_id", sa.Uuid(), nullable=False),
                sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
                sa.UniqueConstraint("tenant_id", "user_id", "memory_key"),
                sa.ForeignKeyConstraint(
                    ["tenant_id", "source_conversation_id", "source_message_id"],
                    ["messages.tenant_id", "messages.conversation_id", "messages.id"],
                    ondelete="CASCADE",
                ),
            )
            op.create_index("ix_user_memories_expiry", name, ["tenant_id", "user_id", "expires_at"])
        op.execute(f"ALTER TABLE {name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {name} FORCE ROW LEVEL SECURITY")
        condition = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid AND user_id = nullif(current_setting('app.user_id', true), '')::uuid"
        op.execute(
            f"CREATE POLICY tenant_isolation ON {name} USING ({condition}) WITH CHECK ({condition})"
        )


def downgrade():
    op.drop_table("user_memories")
    op.drop_table("user_memory_consents")
