"""Shared non-business ingress counters; no customer records or tenant authorization data."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010_http_ingress"
down_revision = "0009_operations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "http_buckets",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("state", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_http_buckets_updated_at", "http_buckets", ["updated_at"])


def downgrade():
    op.drop_index("ix_http_buckets_updated_at", table_name="http_buckets")
    op.drop_table("http_buckets")
