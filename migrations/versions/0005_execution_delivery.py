"""Separate actual execution outcome from permission to deliver its payload."""

import sqlalchemy as sa
from alembic import op

revision = "0005_execution_delivery"
down_revision = "0004_tool_execution"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tool_executions", sa.Column("delivery_error", sa.String(80), nullable=True))


def downgrade():
    raise RuntimeError("Retain execution delivery audit data; use a separately reviewed downgrade")
