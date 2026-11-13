"""Tenant-pinned public routes and immutable chunk revisions; no data deletion."""

import sqlalchemy as sa
from alembic import op

revision = "0013_knowledge_governance"
down_revision = "0012_support_experience"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL validates the new FK against existing records. Inconsistent tenant
    # associations abort the migration transaction; never silently reassign them.
    op.create_unique_constraint("uq_public_routes_tenant_id", "public_routes", ["tenant_id", "id"])
    op.create_foreign_key(
        "fk_publications_tenant_route",
        "publications",
        "public_routes",
        ["tenant_id", "id"],
        ["tenant_id", "id"],
    )
    op.drop_constraint("fk_publications_id_public_routes", "publications", type_="foreignkey")

    op.add_column("document_chunks", sa.Column("root_chunk_id", sa.Uuid(), nullable=True))
    op.add_column(
        "document_chunks", sa.Column("revision", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column(
        "document_chunks",
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "document_chunks",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("document_chunks", sa.Column("revised_by", sa.Uuid(), nullable=True))
    op.add_column("document_chunks", sa.Column("revision_reason", sa.String(500), nullable=True))
    # A schema owner subject to FORCE RLS may otherwise update zero rows. Refuse
    # partial backfill rather than relax a policy or require BYPASSRLS. The explicit
    # per-tenant GUC scopes preserve the policy during this DDL transaction.
    op.execute("""
        DO $$ DECLARE tenant uuid; original_scope text;
        BEGIN
          original_scope := current_setting('app.tenant_id', true);
          FOR tenant IN SELECT id FROM tenants LOOP
            PERFORM set_config('app.tenant_id', tenant::text, true);
            UPDATE document_chunks SET root_chunk_id = id WHERE root_chunk_id IS NULL;
          END LOOP;
          PERFORM set_config('app.tenant_id', coalesce(original_scope, ''), true);
        END $$
    """)
    op.alter_column("document_chunks", "root_chunk_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_constraint("uq_document_chunks_document_id", "document_chunks", type_="unique")
    op.create_unique_constraint(
        "uq_document_chunks_version_identity",
        "document_chunks",
        ["tenant_id", "document_id", "generation", "position", "id"],
    )
    op.create_unique_constraint(
        "uq_document_chunks_revision",
        "document_chunks",
        ["tenant_id", "document_id", "generation", "root_chunk_id", "revision"],
    )
    op.create_foreign_key(
        "fk_document_chunks_root",
        "document_chunks",
        "document_chunks",
        ["tenant_id", "document_id", "generation", "position", "root_chunk_id"],
        ["tenant_id", "document_id", "generation", "position", "id"],
    )
    op.create_foreign_key(
        "fk_document_chunks_editor",
        "document_chunks",
        "tenant_memberships",
        ["tenant_id", "revised_by"],
        ["tenant_id", "user_id"],
    )
    op.create_check_constraint(
        "revision",
        "document_chunks",
        "revision > 0 AND ((revision = 1) = (root_chunk_id = id))",
    )
    op.create_index(
        "ix_document_chunks_current",
        "document_chunks",
        ["tenant_id", "document_id", "generation", "position"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    # Existing document_chunks ENABLE/FORCE RLS and tenant policy remain untouched.


def downgrade():
    raise RuntimeError(
        "Immutable knowledge history needs a reviewed preservation plan before downgrade"
    )
