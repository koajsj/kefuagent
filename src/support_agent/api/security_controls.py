"""Real security administration; blocked assessments never masquerade as purges."""

from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from support_agent.dependencies import Database, TenantAdmin, TenantContext
from support_agent.errors import forbidden
from support_agent.models import CostReservation, ErasureRequest, ToolApproval, WidgetSite
from support_agent.security_schemas import (
    ApprovalDecision,
    ApprovalDetail,
    ApprovalInput,
    ApprovalOut,
    BudgetInput,
    BudgetOut,
    BudgetOverview,
    CostOut,
    ErasureInput,
    ErasureOut,
    SiteCreated,
    SiteInput,
    SiteIntegration,
    SiteOut,
    SitePatch,
    SiteVerify,
)
from support_agent.services import approvals, budgets, erasure, widget_identity
from support_agent.services.resources import get_owned, list_owned
from support_agent.tool_protocol import ToolResult

router = APIRouter(tags=["Security controls"])


@router.post("/security/erasure/preview")
def erasure_preview(data: ErasureInput, db: Database, context: TenantAdmin):
    return erasure.preview(db, context, data)


@router.post("/security/erasure", response_model=ErasureOut)
def erasure_request(data: ErasureInput, request: Request, db: Database, context: TenantAdmin):
    return erasure.request_erasure(db, context, data, request)


@router.get("/security/erasure", response_model=list[ErasureOut])
def erasure_list(
    db: Database,
    context: TenantAdmin,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, ErasureRequest, context, limit, offset)


@router.post("/security/approvals", response_model=ApprovalOut)
def approval_request(data: ApprovalInput, request: Request, db: Database, context: TenantContext):
    return approvals.create(db, context, data, request)


@router.get("/security/approvals", response_model=list[ApprovalOut])
def approval_list(
    request: Request,
    db: Database,
    context: TenantContext,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    stmt = select(ToolApproval).where(ToolApproval.tenant_id == context.tenant_id)
    if context.role != "admin":
        stmt = stmt.where(ToolApproval.requested_by == context.user_id)
    rows = list(
        db.scalars(
            stmt.order_by(ToolApproval.created_at.desc(), ToolApproval.id.desc())
            .limit(limit)
            .offset(offset)
            .with_for_update()
        )
    )
    for row in rows:
        approvals.expire(db, row, request)
    return rows


@router.get("/security/approvals/{aid}", response_model=ApprovalDetail)
def approval_detail(aid: UUID, request: Request, db: Database, context: TenantContext):
    row = get_owned(db, ToolApproval, context, aid, lock=True)
    if context.role != "admin" and row.requested_by != context.user_id:
        raise forbidden()
    approvals.expire(db, row, request)
    return {
        "approval": ApprovalOut.model_validate(row).model_dump(mode="json"),
        "arguments": approvals.arguments(row, request),
    }


@router.post("/security/approvals/{aid}/decision", response_model=ApprovalOut)
def approval_decision(
    aid: UUID, data: ApprovalDecision, request: Request, db: Database, context: TenantAdmin
):
    return approvals.decide_request(db, context, aid, data, request)


@router.post("/security/approvals/{aid}/execute", response_model=ToolResult)
def approval_execute(aid: UUID, request: Request, db: Database, context: TenantContext):
    return approvals.execute(db, context, aid, request)


@router.get("/security/budget", response_model=BudgetOverview)
def budget_view(request: Request, db: Database, context: TenantAdmin):
    row = budgets.policy(db, context.tenant_id)
    used = budgets.usage(db, context.tenant_id)
    remaining = {k: getattr(row, k + "_limit") - used[k] for k in used} if row else None
    state = (
        "PAID_CALLS_DISABLED"
        if not row or not row.enabled
        else "PRICE_CATALOG_CHANGED"
        if row.price_catalog_digest != budgets.catalog(request.app.state.settings)
        else "NO_POSITIVE_CAPACITY"
        if any(v <= 0 for v in remaining.values())
        else "PER_CALL_CHECK"
    )
    return {
        "admission_state": state,
        "remaining": remaining,
        "policy": BudgetOut.model_validate(row).model_dump(mode="json") if row else None,
        "usage": {k: str(v) for k, v in used.items()},
        "price_catalog_digest": budgets.catalog(request.app.state.settings),
        "prices": [
            p.model_dump(mode="json", exclude={"endpoint"})
            for p in request.app.state.settings.model_prices
        ],
        "basis": "internal_deployment_price_not_supplier_invoice",
        "timezone": "UTC",
        "unknown_carry_forward": True,
    }


@router.put("/security/budget", response_model=BudgetOut)
def budget_save(data: BudgetInput, request: Request, db: Database, context: TenantAdmin):
    return budgets.save(db, context, data, request)


@router.get("/security/costs", response_model=list[CostOut])
def cost_list(
    db: Database,
    context: TenantAdmin,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return db.scalars(
        select(CostReservation)
        .where(CostReservation.tenant_id == context.tenant_id)
        .order_by(CostReservation.created_at.desc(), CostReservation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


@router.post("/security/widget-sites", response_model=SiteCreated)
def site_create(data: SiteInput, request: Request, db: Database, context: TenantAdmin):
    return widget_identity.create(db, context, data, request)


@router.get("/security/widget-sites", response_model=list[SiteOut])
def site_list(
    db: Database,
    context: TenantAdmin,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, WidgetSite, context, limit, offset)


@router.post("/security/widget-sites/{site_id}/verify", response_model=SiteOut)
def site_verify(
    site_id: UUID, data: SiteVerify, request: Request, db: Database, context: TenantAdmin
):
    return widget_identity.verify(db, context, site_id, data, request)


@router.patch("/security/widget-sites/{site_id}", response_model=SiteOut)
def site_change(
    site_id: UUID, data: SitePatch, request: Request, db: Database, context: TenantAdmin
):
    return widget_identity.change(db, context, site_id, data, request)


@router.post("/security/widget-sites/{site_id}/challenge", response_model=SiteCreated)
def site_challenge(site_id: UUID, request: Request, db: Database, context: TenantAdmin):
    return widget_identity.renew(db, context, site_id, request)


@router.get("/security/widget-sites/{site_id}/integration", response_model=SiteIntegration)
def site_integration(site_id: UUID, request: Request, db: Database, context: TenantAdmin):
    from support_agent.models import Publication

    row = get_owned(db, WidgetSite, context, site_id)
    publication = get_owned(db, Publication, context, row.publication_id)
    return {
        "instance_id": widget_identity.instance_id(request.app.state.settings),
        "aud": request.app.state.settings.web_origin,
        "publication_id": str(publication.id),
        "publication_version": publication.version,
        "site_id": str(row.id),
        "site_version": row.version,
        "origin": row.origin,
        "algorithm": "HMAC-SHA256",
        "max_assertion_seconds": 60,
        "signing_secret_exposed": False,
    }
