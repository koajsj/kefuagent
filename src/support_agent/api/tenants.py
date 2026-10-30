from uuid import UUID

from fastapi import APIRouter, Query, Request

from support_agent.dependencies import CurrentUser, Database, PlatformAdmin, TenantAdmin
from support_agent.models import Membership
from support_agent.schemas import (
    MembershipCreate,
    MembershipOut,
    MembershipPatch,
    TenantCreate,
    TenantOut,
    TenantPatch,
)
from support_agent.services import tenants
from support_agent.services.resources import list_owned

router = APIRouter(tags=["Tenants and memberships"])


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(data: TenantCreate, request: Request, db: Database, admin: PlatformAdmin):
    return tenants.create_tenant(db, data, request)


@router.get("/tenants", response_model=list[TenantOut])
def list_tenants(
    db: Database,
    user: CurrentUser,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return tenants.list_tenants(db, user, limit, offset)


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
def tenant_detail(tenant_id: UUID, db: Database, user: CurrentUser):
    return tenants.get_visible_tenant(db, tenant_id, user)


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
def tenant_status(
    tenant_id: UUID, data: TenantPatch, request: Request, db: Database, admin: PlatformAdmin
):
    return tenants.set_status(db, tenant_id, data.status, request)


@router.get("/memberships", response_model=list[MembershipOut])
def list_memberships(
    db: Database,
    context: TenantAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_owned(db, Membership, context, limit, offset)


@router.post("/memberships", response_model=MembershipOut, status_code=201)
def create_membership(data: MembershipCreate, request: Request, db: Database, context: TenantAdmin):
    return tenants.add_member(db, context, data, request)


@router.patch("/memberships/{membership_id}", response_model=MembershipOut)
def update_membership(
    membership_id: UUID, data: MembershipPatch, request: Request, db: Database, context: TenantAdmin
):
    return tenants.update_member(db, context, membership_id, data, request)
