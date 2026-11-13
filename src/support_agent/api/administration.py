from fastapi import APIRouter, Request

from support_agent.administration_schemas import AdministrationOut, RetentionPreview
from support_agent.db import EXPECTED_REVISION
from support_agent.dependencies import Database, TenantAdmin
from support_agent.retention import retention_plan

router = APIRouter(tags=["Private administration"])


@router.get("/administration", response_model=AdministrationOut)
def administration(request: Request, context: TenantAdmin):
    settings = request.app.state.settings
    return {
        "deployment_mode": "single_enterprise_private",
        "required_revision": EXPECTED_REVISION,
        "storage_backend": getattr(settings, "document_storage_backend", "local"),
        "external_models_enabled": settings.allow_external_models,
        "automatic_migrations": False,
        "backup_last_verified_at": None,
        "backup_mode": "operator_consistent_database_files_and_keys",
        "worker": "optional_postgresql_worker_product_jobs_opt_in; runtime_health_UNKNOWN",
        "retention": {
            field: getattr(settings, "retention_" + field)
            for field in ("conversations_days", "visitors_days", "calls_days", "audit_days")
        },
        "capabilities": [
            {
                "name": "AI reply suggestions",
                "state": "NEEDS_RUNTIME_VERIFICATION",
                "detail": "Private budgeted worker drafts with citations; only explicit human acceptance writes a message",
            },
            {
                "name": "Complete customer export",
                "state": "NEEDS_RUNTIME_VERIFICATION",
                "detail": "Reviewed subject scope, snapshot JSONL/attachment ZIP, private expiring downloads; S3 physical cleanup remains BLOCKED",
            },
            {
                "name": "Monetary hard budget",
                "state": "NEEDS_RUNTIME_VERIFICATION",
                "detail": "Atomic same-currency ledger at the model gateway; paid requests denied without reviewed cost bounds and enabled policy",
            },
            {
                "name": "Customer identity",
                "state": "staff_confirmed",
                "detail": "Visitor tokens and IP addresses never merge customer profiles",
            },
            {
                "name": "Order integration",
                "state": "BLOCKED",
                "detail": "No approved external order API or credentials",
            },
            {
                "name": "External notifications",
                "state": "BLOCKED",
                "detail": "Only durable in-app staff notifications are configured by code",
            },
            {
                "name": "Semantic retrieval",
                "state": "NEEDS_RUNTIME_VERIFICATION",
                "detail": "Authorized pgvector 1536-dimensional recall with lexical RRF fusion, optional budgeted LLM ranking, diagnostics and durable indexing",
            },
            {
                "name": "Complete erasure",
                "state": "BLOCKED",
                "detail": "User RLS and historical derived/JSON records lack a complete confirmed impact graph",
            },
            {
                "name": "R3 approvals",
                "state": "NEEDS_RUNTIME_VERIFICATION",
                "detail": "Independent one-shot approval for fixed transactional desk commands; external effects and R4 remain denied",
            },
            {
                "name": "Production acceptance",
                "state": "NEEDS_RUNTIME_VERIFICATION",
                "detail": "Static checks do not establish database, model, browser or restore correctness",
            },
        ],
    }


@router.post("/administration/retention/preview")
def preview(data: RetentionPreview, request: Request, db: Database, context: TenantAdmin):
    from types import SimpleNamespace

    values = {
        field: getattr(request.app.state.settings, "retention_" + field)
        for field in ("conversations_days", "visitors_days", "calls_days", "audit_days")
    }
    values.update(data.model_dump(exclude_unset=True))
    values.setdefault("documents", False)
    values.setdefault("batch_size", 20)
    plan = retention_plan(db, context.tenant_id, SimpleNamespace(**values))
    # HTTP is a preview surface; executing even a safe CLI batch remains operator-only.
    return plan | {"execution_channel": "operator_cli_only", "http_execution_enabled": False}
