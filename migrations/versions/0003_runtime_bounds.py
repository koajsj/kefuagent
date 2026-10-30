"""runtime_bounds"""

import sqlalchemy as sa
from alembic import op

revision = "0003_runtime_bounds"
down_revision = "0002_knowledge_rag"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "model_calls",
        "attempts",
        existing_type=sa.INTEGER(),
        nullable=True,
        existing_server_default=sa.text("0"),
    )


def downgrade():
    op.alter_column(
        "model_calls",
        "attempts",
        existing_type=sa.INTEGER(),
        nullable=False,
        existing_server_default=sa.text("0"),
    )
