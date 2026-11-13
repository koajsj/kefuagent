"""Bind calls, visitors and worker sessions to their actual owners.

Additive constraints only. Inconsistent historical rows must stop the upgrade;
never silently reassign, delete or bypass RLS to repair them.
"""

from alembic import op

revision = "0019_core_integrity"
down_revision = "0018_core_products"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_auth_sessions_owner", "auth_sessions", ["user_id", "id"])
    op.create_unique_constraint(
        "uq_model_calls_conversation", "model_calls", ["tenant_id", "conversation_id", "id"]
    )
    op.create_unique_constraint(
        "uq_model_calls_agent", "model_calls", ["tenant_id", "agent_config_id", "id"]
    )
    op.create_unique_constraint(
        "uq_visitor_sessions_scope", "visitor_sessions", ["tenant_id", "conversation_id", "id"]
    )
    op.create_unique_constraint(
        "uq_widget_sites_publication", "widget_sites", ["tenant_id", "publication_id", "id"]
    )
    for table in ("messages", "tool_executions", "conversation_summaries", "reply_drafts"):
        op.create_foreign_key(
            f"fk_{table}_call_conversation",
            table,
            "model_calls",
            ["tenant_id", "conversation_id", "model_call_id"],
            ["tenant_id", "conversation_id", "id"],
            ondelete="CASCADE" if table == "conversation_summaries" else None,
        )
    for table in ("tool_executions", "cost_reservations", "reply_drafts"):
        op.create_foreign_key(
            f"fk_{table}_call_agent",
            table,
            "model_calls",
            ["tenant_id", "agent_config_id", "model_call_id"],
            ["tenant_id", "agent_config_id", "id"],
        )
    for table, name in (
        ("model_calls", "fk_model_calls_visitor_conversation"),
        ("conversation_attachments", "fk_conversation_attachments_visitor_conversation"),
        ("visitor_feedback", "fk_visitor_feedback_session_conversation"),
    ):
        op.create_foreign_key(
            name,
            table,
            "visitor_sessions",
            ["tenant_id", "conversation_id", "visitor_session_id"],
            ["tenant_id", "conversation_id", "id"],
            ondelete="CASCADE" if table == "visitor_feedback" else None,
        )
    op.create_check_constraint(
        op.f("ck_model_calls_visitor_conversation"),
        "model_calls",
        "visitor_session_id IS NULL OR conversation_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_visitor_sessions_publication_site",
        "visitor_sessions",
        "widget_sites",
        ["tenant_id", "publication_id", "site_id"],
        ["tenant_id", "publication_id", "id"],
    )
    for table in ("knowledge_indexes", "customer_exports", "reply_drafts"):
        op.create_foreign_key(
            f"fk_{table}_request_session",
            table,
            "auth_sessions",
            ["requested_by", "auth_session_id"],
            ["user_id", "id"],
        )


def downgrade():
    raise RuntimeError("Removing ownership constraints requires a separately reviewed rollback")
