"""Security control ledgers; additive only. Existing visitor tokens fail closed.

Frozen PostgreSQL DDL; no application metadata import or historical migration edits.
"""

from alembic import op

revision = "0017_security_controls"
down_revision = "0016_customer_memory"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE tool_executions ADD CONSTRAINT uq_tool_executions_tenant_identity UNIQUE (tenant_id, id)"
    )
    op.execute(
        "CREATE TABLE erasure_requests (\n\ttenant_id UUID NOT NULL, \n\trequested_by UUID NOT NULL, \n\tsubject_type VARCHAR(16) NOT NULL, \n\tsubject_id UUID NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tattempts INTEGER NOT NULL, \n\tassessment JSONB NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_erasure_requests PRIMARY KEY (id), \n\tCONSTRAINT uq_erasure_requests_tenant_id UNIQUE (tenant_id, subject_type, subject_id), \n\tCONSTRAINT ck_erasure_requests_subject_type CHECK (subject_type IN ('user','customer','conversation')), \n\tCONSTRAINT ck_erasure_requests_status CHECK (status IN ('REQUESTED','ACCESS_BLOCKED','DEPENDENCY_CHECK','PURGING','PURGED','BLOCKED')), \n\tCONSTRAINT fk_erasure_requests_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id), \n\tCONSTRAINT fk_erasure_requests_requested_by_users FOREIGN KEY(requested_by) REFERENCES users (id)\n)"
    )
    op.execute("ALTER TABLE erasure_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE erasure_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON erasure_requests USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE tool_approvals (\n\ttenant_id UUID NOT NULL, \n\trequested_by UUID NOT NULL, \n\tdecided_by UUID, \n\tconversation_id UUID NOT NULL, \n\tagent_config_id UUID NOT NULL, \n\ttool_id UUID NOT NULL, \n\tidempotency_key UUID NOT NULL, \n\tstatus VARCHAR(24) NOT NULL, \n\tpayload_digest VARCHAR(64) NOT NULL, \n\tencrypted_arguments TEXT NOT NULL, \n\tbinding JSONB NOT NULL, \n\treason VARCHAR(1000), \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tdecided_at TIMESTAMP WITH TIME ZONE, \n\texecution_id UUID, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_tool_approvals PRIMARY KEY (id), \n\tCONSTRAINT uq_tool_approvals_tenant_identity UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_tool_approvals_request_key UNIQUE (tenant_id, requested_by, idempotency_key), \n\tCONSTRAINT fk_tool_approvals_tenant_id_conversations FOREIGN KEY(tenant_id, conversation_id) REFERENCES conversations (tenant_id, id), \n\tCONSTRAINT fk_tool_approvals_tenant_id_agent_configs FOREIGN KEY(tenant_id, agent_config_id) REFERENCES agent_configs (tenant_id, id), \n\tCONSTRAINT fk_tool_approvals_tenant_id_tool_definitions FOREIGN KEY(tenant_id, tool_id) REFERENCES tool_definitions (tenant_id, id), \n\tCONSTRAINT fk_tool_approvals_tenant_id_tool_executions FOREIGN KEY(tenant_id, execution_id) REFERENCES tool_executions (tenant_id, id), \n\tCONSTRAINT ck_tool_approvals_status CHECK (status IN ('PENDING_APPROVAL','APPROVED','REJECTED','EXPIRED','REVOKED','EXECUTED')), \n\tCONSTRAINT ck_tool_approvals_separation CHECK (decided_by IS NULL OR decided_by <> requested_by), \n\tCONSTRAINT fk_tool_approvals_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id), \n\tCONSTRAINT fk_tool_approvals_requested_by_users FOREIGN KEY(requested_by) REFERENCES users (id), \n\tCONSTRAINT fk_tool_approvals_decided_by_users FOREIGN KEY(decided_by) REFERENCES users (id), \n\tCONSTRAINT uq_tool_approvals_execution_id UNIQUE (execution_id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_tool_approvals_queue ON tool_approvals (tenant_id, status, expires_at)"
    )
    op.execute("ALTER TABLE tool_approvals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tool_approvals FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON tool_approvals USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE budget_policies (\n\ttenant_id UUID NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\trun_limit NUMERIC(24, 12) NOT NULL, \n\tdaily_limit NUMERIC(24, 12) NOT NULL, \n\tmonthly_limit NUMERIC(24, 12) NOT NULL, \n\ttotal_limit NUMERIC(24, 12) NOT NULL, \n\tagent_limits JSONB NOT NULL, \n\tprice_catalog_digest VARCHAR(64) NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_budget_policies PRIMARY KEY (id), \n\tCONSTRAINT uq_budget_policies_tenant_id UNIQUE (tenant_id), \n\tCONSTRAINT ck_budget_policies_limits CHECK (run_limit >= 0 AND daily_limit >= 0 AND monthly_limit >= 0 AND total_limit >= 0), \n\tCONSTRAINT ck_budget_policies_version CHECK (version > 0), \n\tCONSTRAINT fk_budget_policies_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id)\n)"
    )
    op.execute("ALTER TABLE budget_policies ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE budget_policies FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON budget_policies USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE cost_reservations (\n\ttenant_id UUID NOT NULL, \n\tmodel_call_id UUID NOT NULL, \n\tagent_config_id UUID NOT NULL, \n\tstep_index INTEGER NOT NULL, \n\tpolicy_version INTEGER NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\treserved NUMERIC(24, 12) NOT NULL, \n\tcharged NUMERIC(24, 12) NOT NULL, \n\tpricing JSONB NOT NULL, \n\tstatus VARCHAR(16) NOT NULL, \n\tsettled_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_cost_reservations PRIMARY KEY (id), \n\tCONSTRAINT uq_cost_reservations_tenant_id UNIQUE (tenant_id, model_call_id, step_index), \n\tCONSTRAINT fk_cost_reservations_tenant_id_model_calls FOREIGN KEY(tenant_id, model_call_id) REFERENCES model_calls (tenant_id, id), \n\tCONSTRAINT fk_cost_reservations_tenant_id_agent_configs FOREIGN KEY(tenant_id, agent_config_id) REFERENCES agent_configs (tenant_id, id), \n\tCONSTRAINT ck_cost_reservations_amounts CHECK (reserved >= 0 AND charged >= 0), \n\tCONSTRAINT ck_cost_reservations_status CHECK (status IN ('RESERVED','SETTLED','RELEASED','UNKNOWN','OVERRUN')), \n\tCONSTRAINT fk_cost_reservations_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id)\n)"
    )
    op.execute(
        "CREATE INDEX ix_cost_reservations_accounting ON cost_reservations (tenant_id, created_at, status)"
    )
    op.execute("ALTER TABLE cost_reservations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE cost_reservations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON cost_reservations USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE widget_sites (\n\ttenant_id UUID NOT NULL, \n\tpublication_id UUID NOT NULL, \n\torigin VARCHAR(300) NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tversion INTEGER NOT NULL, \n\tchallenge_hash VARCHAR(64) NOT NULL, \n\tchallenge_expires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tverified_at TIMESTAMP WITH TIME ZONE, \n\tverification_expires_at TIMESTAMP WITH TIME ZONE, \n\tencrypted_secret TEXT NOT NULL, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_widget_sites PRIMARY KEY (id), \n\tCONSTRAINT uq_widget_sites_tenant_identity UNIQUE (tenant_id, id), \n\tCONSTRAINT uq_widget_sites_publication_origin UNIQUE (tenant_id, publication_id, origin), \n\tCONSTRAINT fk_widget_sites_tenant_id_publications FOREIGN KEY(tenant_id, publication_id) REFERENCES publications (tenant_id, id), \n\tCONSTRAINT ck_widget_sites_version CHECK (version > 0), \n\tCONSTRAINT fk_widget_sites_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id)\n)"
    )
    op.execute("ALTER TABLE widget_sites ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE widget_sites FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON widget_sites USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE TABLE widget_bootstraps (\n\ttenant_id UUID NOT NULL, \n\tsite_id UUID NOT NULL, \n\tsite_version INTEGER NOT NULL, \n\tpublication_version INTEGER NOT NULL, \n\tnonce UUID NOT NULL, \n\ttoken_hash VARCHAR(64) NOT NULL, \n\texpires_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tconsumed_at TIMESTAMP WITH TIME ZONE, \n\tid UUID NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n\tCONSTRAINT pk_widget_bootstraps PRIMARY KEY (id), \n\tCONSTRAINT uq_widget_bootstraps_tenant_id UNIQUE (tenant_id, site_id, nonce), \n\tCONSTRAINT fk_widget_bootstraps_tenant_id_widget_sites FOREIGN KEY(tenant_id, site_id) REFERENCES widget_sites (tenant_id, id), \n\tCONSTRAINT fk_widget_bootstraps_tenant_id_tenants FOREIGN KEY(tenant_id) REFERENCES tenants (id), \n\tCONSTRAINT uq_widget_bootstraps_token_hash UNIQUE (token_hash)\n)"
    )
    op.execute("ALTER TABLE widget_bootstraps ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE widget_bootstraps FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON widget_bootstraps USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid) WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)"
    )
    op.execute("ALTER TABLE visitor_sessions ADD COLUMN site_id UUID")
    op.execute("ALTER TABLE visitor_sessions ADD COLUMN site_version INTEGER")
    op.execute(
        "ALTER TABLE visitor_sessions ADD CONSTRAINT fk_visitor_sessions_tenant_id_widget_sites FOREIGN KEY(tenant_id, site_id) REFERENCES widget_sites (tenant_id, id)"
    )


def downgrade():
    raise RuntimeError(
        "Security ledgers require a reviewed preservation and revocation plan before downgrade"
    )
