"""tenant operations summaries feedback"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_operations"
down_revision = "0008_public_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_messages_conversation_identity", "messages", ["tenant_id", "conversation_id", "id"]
    )
    op.create_table(
        "conversation_collaboration",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(length=4000), server_default="", nullable=False),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('note','assignment','handling','metadata')",
            name=op.f("ck_conversation_collaboration_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["users.id"], name=op.f("fk_conversation_collaboration_actor_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_conversation_collaboration_tenant_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_conversation_collaboration_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_collaboration")),
    )
    op.create_index(
        "ix_collaboration_history",
        "conversation_collaboration",
        ["tenant_id", "conversation_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "visitor_feedback",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("visitor_session_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.String(length=1000), server_default="", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rating IN ('satisfied','dissatisfied')", name=op.f("ck_visitor_feedback_rating")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_visitor_feedback_tenant_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "visitor_session_id"],
            ["visitor_sessions.tenant_id", "visitor_sessions.id"],
            name=op.f("fk_visitor_feedback_tenant_id_visitor_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_visitor_feedback_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_visitor_feedback")),
        sa.UniqueConstraint(
            "tenant_id", "visitor_session_id", name=op.f("uq_visitor_feedback_tenant_id")
        ),
    )
    op.create_index(
        "ix_visitor_feedback_tenant_created",
        "visitor_feedback",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "conversation_summaries",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(length=6000), nullable=False),
        sa.Column("source_start_id", sa.Uuid(), nullable=False),
        sa.Column("source_end_id", sa.Uuid(), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("model_call_id", sa.Uuid(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version > 0 AND source_count > 0", name=op.f("ck_conversation_summaries_range")
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "source_end_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
            name="fk_summary_source_end",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id", "source_start_id"],
            ["messages.tenant_id", "messages.conversation_id", "messages.id"],
            name="fk_summary_source_start",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"],
            ["conversations.tenant_id", "conversations.id"],
            name=op.f("fk_conversation_summaries_tenant_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "model_call_id"],
            ["model_calls.tenant_id", "model_calls.id"],
            name=op.f("fk_conversation_summaries_tenant_id_model_calls"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name=op.f("fk_conversation_summaries_tenant_id_tenants")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_summaries")),
        sa.UniqueConstraint(
            "tenant_id",
            "conversation_id",
            "version",
            name=op.f("uq_conversation_summaries_tenant_id"),
        ),
    )
    op.add_column("conversations", sa.Column("assignee_id", sa.Uuid(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("priority", sa.String(length=16), server_default="normal", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "tags", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("category", sa.String(length=80), server_default="", nullable=False),
    )
    op.add_column(
        "conversations", sa.Column("version", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column(
        "conversations", sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("waiting_since", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("human_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "conversations",
        sa.Column("ever_human", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(
        "ix_conversations_assignee",
        "conversations",
        ["tenant_id", "assignee_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_conversations_queue",
        "conversations",
        ["tenant_id", "support_state", "created_at", "id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_conversations_assignee_membership",
        "conversations",
        "tenant_memberships",
        ["tenant_id", "assignee_id"],
        ["tenant_id", "user_id"],
    )
    op.create_check_constraint(
        "priority", "conversations", "priority IN ('low','normal','high','urgent')"
    )
    op.create_check_constraint("version", "conversations", "version > 0")
    op.create_check_constraint(
        "tags", "conversations", "jsonb_typeof(tags) = 'array' AND jsonb_array_length(tags) <= 10"
    )
    for table in ("conversation_collaboration", "conversation_summaries", "visitor_feedback"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        scope = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING ({scope}) WITH CHECK ({scope})"
        )
    # Preserve unknown historical timings. Record pre-existing human handling without inventing a start time.
    op.execute("""DO $$ DECLARE tid uuid; BEGIN
        FOR tid IN SELECT id FROM tenants LOOP
            PERFORM set_config('app.tenant_id', tid::text, true);
            UPDATE conversations SET ever_human=true WHERE tenant_id=tid AND support_state='human';
        END LOOP;
        PERFORM set_config('app.tenant_id', '', true);
    END $$""")


def downgrade():
    raise RuntimeError("Review data-preserving rollback before removing operations records")
