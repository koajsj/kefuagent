"""p4_runtime_and_chinese_search"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_p4_runtime"
down_revision = "0005_execution_delivery"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE FUNCTION support_cjk_bigrams(value text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE SET search_path = pg_catalog AS $$
        SELECT coalesce(string_agg(substr(value, n, 2), ' '), '')
        FROM generate_series(1, greatest(char_length(value)-1, 0)) n
        WHERE substr(value, n, 2) ~ '^[㐀-鿿]{2}$'
        $$""")
    op.add_column(
        "document_chunks",
        sa.Column(
            "chinese_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, support_cjk_bigrams(content))", persisted=True
            ),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_document_chunks_chinese",
        "document_chunks",
        ["chinese_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.add_column(
        "model_calls",
        sa.Column("phase", sa.String(length=20), server_default="pending", nullable=False),
    )
    op.add_column(
        "model_calls",
        sa.Column("reserved_tokens", sa.Integer(), server_default="0", nullable=False),
    )
    # FORCE RLS remains active; migrate each existing tenant explicitly, never bypass it.
    op.execute("""DO $$ DECLARE tid uuid; BEGIN
      FOR tid IN SELECT id FROM tenants LOOP
        PERFORM set_config('app.tenant_id', tid::text, true);
        UPDATE model_calls SET phase = CASE WHEN status='running' THEN 'pending'
             WHEN status='failed' THEN 'failed' ELSE 'completed' END,
          reserved_tokens = CASE WHEN kind='tool_execution' THEN 0
             WHEN input_tokens IS NOT NULL AND output_tokens IS NOT NULL AND attempts=1
             THEN input_tokens+output_tokens
             WHEN kind='agent' THEN 1310720 ELSE 131072 END
          WHERE tenant_id=tid;
      END LOOP;
      PERFORM set_config('app.tenant_id', '', true);
    END $$""")


def downgrade():
    raise RuntimeError("Retain quota accounting and review an explicit downgrade before reverting")
