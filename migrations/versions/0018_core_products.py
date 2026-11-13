"""Private hybrid retrieval, customer portability and human-reviewed drafts.

Frozen additive SQL; pgvector must be installed by a separately authorized operator.
No historical migration or existing row is rewritten.
"""

from alembic import op

revision = "0018_core_products"
down_revision = "0017_security_controls"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector') THEN RAISE EXCEPTION 'Install and authorize pgvector before applying 0018; application role must not install extensions'; END IF; END $$"
    )
    op.execute("ALTER TABLE model_calls DROP CONSTRAINT ck_model_calls_kind")
    op.execute(
        "ALTER TABLE model_calls ADD CONSTRAINT ck_model_calls_kind CHECK (kind IN ('chat','connection_test','agent','tool_execution','embedding','search','draft'))"
    )
    op.execute(
        "CREATE TABLE customer_exports (\n\ttenant_id UUID NOT NULL, \n\tcustomer_id UUID NOT NULL, \n\trequested_by UUID NOT NULL, \n\tauth_session_id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tscope JSONB NOT NULL, \n\tscope_digest VARCHAR(64) NOT NULL, \n\tparts JSONB NOT NULL, \n\tmanifest JSONB NOT NULL, \n\terror_category VARCHAR(80), \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tlease_token UUID, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_customer_exports PRIMARY KEY (id), \n\tCONSTRAINT uq_customer_exports_request UNIQUE (tenant_id, requested_by, request_key), \n\tCONSTRAINT fk_customer_exports_tenant_id_customers FOREIGN KEY(tenant_id, customer_id) REFERENCES customers (tenant_id, id), \n\tCONSTRAINT ck_customer_exports_status CHECK (status IN ('REQUESTED','BUILDING','READY','FAILED','EXPIRED','CLEANUP_BLOCKED','DELETED')), \n\tCONSTRAINT fk_customer_exports_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id), \n\tCONSTRAINT fk_customer_exports_requested_by_users FOREIGN KEY(requested_by) REFERENCES users (id), \n\tCONSTRAINT fk_customer_exports_auth_session_id_auth_sessions FOREIGN KEY(auth_session_id) REFERENCES auth_sessions (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_customer_exports_queue ON customer_exports (tenant_id, status, expires_at)"
    )
    op.execute("ALTER TABLE customer_exports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE customer_exports FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON customer_exports USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE knowledge_indexes (\n\ttenant_id UUID NOT NULL, \n\tknowledge_base_id UUID NOT NULL, \n\tagent_config_id UUID NOT NULL, \n\trequested_by UUID NOT NULL, \n\tauth_session_id UUID NOT NULL, \n\tmodel VARCHAR(120) NOT NULL, \n\tendpoint VARCHAR(500) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\trerank BOOLEAN NOT NULL, \n\tstate VARCHAR(16) NOT NULL, \n\terror_category VARCHAR(80), \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tlease_token UUID, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_knowledge_indexes PRIMARY KEY (id), \n\tCONSTRAINT uq_knowledge_indexes_tenant_identity UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_knowledge_indexes_base UNIQUE (tenant_id, knowledge_base_id), \n\tCONSTRAINT fk_knowledge_indexes_tenant_id_knowledge_bases FOREIGN KEY(tenant_id, knowledge_base_id) REFERENCES knowledge_bases (tenant_id, id), \n\tCONSTRAINT fk_knowledge_indexes_tenant_id_agent_configs FOREIGN KEY(tenant_id, agent_config_id) REFERENCES agent_configs (tenant_id, id), \n\tCONSTRAINT ck_knowledge_indexes_state CHECK (state IN ('DISABLED','QUEUED','RUNNING','READY','FAILED')), \n\tCONSTRAINT ck_knowledge_indexes_version CHECK (version > 0), \n\tCONSTRAINT fk_knowledge_indexes_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id), \n\tCONSTRAINT fk_knowledge_indexes_requested_by_users FOREIGN KEY(requested_by) REFERENCES users (id), \n\tCONSTRAINT fk_knowledge_indexes_auth_session_id_auth_sessions FOREIGN KEY(auth_session_id) REFERENCES auth_sessions (id)\n)"
    )
    op.execute("ALTER TABLE knowledge_indexes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_indexes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON knowledge_indexes USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE chunk_embeddings (\n\ttenant_id UUID NOT NULL, \n\tindex_id UUID NOT NULL, \n\tchunk_id UUID NOT NULL, \n\tmodel_call_id UUID NOT NULL, \n\tindex_version INTEGER NOT NULL, \n\tcontent_digest VARCHAR(64) NOT NULL, \n\tembedding VECTOR(1536) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_chunk_embeddings PRIMARY KEY (id), \n\tCONSTRAINT uq_chunk_embeddings_source UNIQUE (tenant_id, index_id, chunk_id), \n\tCONSTRAINT fk_chunk_embeddings_tenant_id_knowledge_indexes FOREIGN KEY(tenant_id, index_id) REFERENCES knowledge_indexes (tenant_id, id), \n\tCONSTRAINT fk_chunk_embeddings_tenant_id_document_chunks FOREIGN KEY(tenant_id, chunk_id) REFERENCES document_chunks (tenant_id, id), \n\tCONSTRAINT fk_chunk_embeddings_tenant_id_model_calls FOREIGN KEY(tenant_id, model_call_id) REFERENCES model_calls (tenant_id, id), \n\tCONSTRAINT fk_chunk_embeddings_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_chunk_embeddings_cosine ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("ALTER TABLE chunk_embeddings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE chunk_embeddings FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON chunk_embeddings USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE reply_drafts (\n\ttenant_id UUID NOT NULL, \n\tconversation_id UUID NOT NULL, \n\tagent_config_id UUID NOT NULL, \n\trequested_by UUID NOT NULL, \n\tauth_session_id UUID NOT NULL, \n\trequest_key UUID NOT NULL, \n\tmodel_call_id UUID, \n\tstatus VARCHAR(16) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcontext_digest VARCHAR(64) NOT NULL, \n\tcontent TEXT NOT NULL, \n\toriginal_content TEXT NOT NULL, \n\tcitations JSONB NOT NULL, \n\twarnings JSONB NOT NULL, \n\tfeedback VARCHAR(1000), \n\tsent_message_id UUID, \n\terror_category VARCHAR(80), \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_reply_drafts PRIMARY KEY (id), \n\tCONSTRAINT uq_reply_drafts_request UNIQUE (tenant_id, requested_by, request_key), \n\tCONSTRAINT fk_reply_drafts_tenant_id_conversations FOREIGN KEY(tenant_id, conversation_id) REFERENCES conversations (tenant_id, id), \n\tCONSTRAINT fk_reply_drafts_tenant_id_agent_configs FOREIGN KEY(tenant_id, agent_config_id) REFERENCES agent_configs (tenant_id, id), \n\tCONSTRAINT fk_reply_drafts_tenant_id_model_calls FOREIGN KEY(tenant_id, model_call_id) REFERENCES model_calls (tenant_id, id), \n\tCONSTRAINT fk_reply_drafts_tenant_id_messages FOREIGN KEY(tenant_id, conversation_id, sent_message_id) REFERENCES messages (tenant_id, conversation_id, id), \n\tCONSTRAINT ck_reply_drafts_status CHECK (status IN ('DRAFT','GENERATING','GENERATED','EDITED','ACCEPTED','REJECTED','EXPIRED')), \n\tCONSTRAINT ck_reply_drafts_version CHECK (version > 0), \n\tCONSTRAINT fk_reply_drafts_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id), \n\tCONSTRAINT fk_reply_drafts_requested_by_users FOREIGN KEY(requested_by) REFERENCES users (id), \n\tCONSTRAINT fk_reply_drafts_auth_session_id_auth_sessions FOREIGN KEY(auth_session_id) REFERENCES auth_sessions (id)\n)"
    )
    op.execute("CREATE INDEX ix_reply_drafts_queue ON reply_drafts (tenant_id, status, created_at)")
    op.execute("ALTER TABLE reply_drafts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE reply_drafts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON reply_drafts USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade():
    raise RuntimeError("Product records and private exports require a reviewed preservation plan")
