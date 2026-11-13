"""Private service desk customers, tickets, durable history and staff notifications."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_private_service_desk"
down_revision = "0013_knowledge_governance"
branch_labels = None
depends_on = None


def identity():
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
    ]


def upgrade():
    # Preserve existing published sources. New ORM uploads explicitly start unpublished.
    op.add_column(
        "documents", sa.Column("is_published", sa.Boolean(), nullable=False, server_default="true")
    )
    op.create_table(
        "customers",
        *identity(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_customers_request_key"),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("external_ref", sa.String(160)),
        sa.Column("email", sa.String(254)),
        sa.Column("phone", sa.String(40)),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("memory_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "external_ref", name="uq_customers_external_ref"),
        sa.CheckConstraint("version > 0", name="version"),
        sa.CheckConstraint("status IN ('active','archived')", name="status"),
    )
    op.create_index("ix_customers_tenant_updated", "customers", ["tenant_id", "updated_at", "id"])
    op.create_table(
        "conversation_customers",
        *identity(),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.UniqueConstraint("tenant_id", "conversation_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]
        ),
    )
    op.create_table(
        "tickets",
        *identity(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("conversation_id", sa.Uuid()),
        sa.Column("customer_id", sa.Uuid()),
        sa.Column("assignee_id", sa.Uuid()),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_tickets_tenant_identity"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_tickets_request_key"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assignee_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
        ),
        sa.CheckConstraint("version > 0", name="version"),
        sa.CheckConstraint("status IN ('open','in_progress','resolved','closed')", name="status"),
        sa.CheckConstraint("priority IN ('low','normal','high','urgent')", name="priority"),
    )
    op.create_index("ix_tickets_queue", "tickets", ["tenant_id", "status", "due_at", "id"])
    op.create_index("ix_tickets_customer", "tickets", ["tenant_id", "customer_id", "created_at"])
    op.create_table(
        "ticket_events",
        *identity(),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "ticket_id"], ["tickets.tenant_id", "tickets.id"]),
    )
    op.create_index(
        "ix_ticket_events_history", "ticket_events", ["tenant_id", "ticket_id", "created_at", "id"]
    )
    op.create_table(
        "staff_notifications",
        *identity(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("ticket_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "ticket_id", "user_id", "ticket_version", "kind"),
        sa.ForeignKeyConstraint(["tenant_id", "ticket_id"], ["tickets.tenant_id", "tickets.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["tenant_memberships.tenant_id", "tenant_memberships.user_id"]
        ),
    )
    op.create_index(
        "ix_staff_notifications_inbox",
        "staff_notifications",
        ["tenant_id", "user_id", "created_at", "id"],
    )
    for table in (
        "customers",
        "conversation_customers",
        "tickets",
        "ticket_events",
        "staff_notifications",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        condition = "tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({condition}) WITH CHECK ({condition})"
        )


def downgrade():
    raise RuntimeError(
        "Service desk history requires a reviewed preservation/export plan before downgrade"
    )
