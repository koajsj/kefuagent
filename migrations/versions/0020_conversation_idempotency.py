"""Persist staff conversation creation identities without rewriting historical rows."""

import sqlalchemy as sa
from alembic import op

revision = "0020_conversation_idempotency"
down_revision = "0019_core_integrity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("idempotency_key", sa.Uuid(), nullable=True))
    op.add_column("conversations", sa.Column("input_digest", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_conversations_create_request",
        "conversations",
        ["tenant_id", "created_by", "idempotency_key"],
    )
    op.create_check_constraint(
        op.f("ck_conversations_creation_request"),
        "conversations",
        "(idempotency_key IS NULL AND input_digest IS NULL) OR "
        "(idempotency_key IS NOT NULL AND input_digest IS NOT NULL "
        "AND input_digest ~ '^[0-9a-f]{64}$')",
    )


def downgrade():
    raise RuntimeError("Dropping creation identities requires a separately reviewed rollback")
