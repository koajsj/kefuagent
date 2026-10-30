from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from support_agent.errors import AppError, forbidden, missing
from support_agent.models import Membership, Tenant, User
from support_agent.services.audit import record


def create_tenant(db: Session, data, request):
    user = db.scalar(select(User).where(User.id == data.admin_user_id).with_for_update())
    if not user or user.status != "active":
        raise AppError(
            422, "invalid_admin", "Initial administrator must be an active existing user"
        )
    tenant = Tenant(name=data.name, slug=data.slug)
    db.add(tenant)
    db.flush()
    db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="admin"))
    db.flush()
    record(db, request, "tenant.create", "tenant", tenant.id, tenant_id=tenant.id)
    return tenant


def list_tenants(db: Session, user, limit: int, offset: int):
    query = select(Tenant)
    if not user.is_platform_admin:
        query = query.join(Membership, Membership.tenant_id == Tenant.id).where(
            Membership.user_id == user.id, Membership.status == "active"
        )
    return db.scalars(
        query.order_by(Tenant.created_at, Tenant.id).limit(limit).offset(offset)
    ).all()


def set_status(db: Session, tenant_id: UUID, status: str, request):
    tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    if not tenant:
        raise missing()
    tenant.status = status
    db.flush()
    record(db, request, "tenant.status", "tenant", tenant.id, tenant_id=tenant.id)
    return tenant


def add_member(db: Session, context, data, request):
    user = db.scalar(select(User).where(User.id == data.user_id).with_for_update())
    if not user or user.status != "active":
        raise AppError(422, "invalid_member", "Member must be an active existing user")
    _lock_and_recheck_admin(db, context)
    membership = Membership(tenant_id=context.tenant_id, user_id=user.id, role=data.role)
    db.add(membership)
    db.flush()
    record(
        db, request, "membership.create", "membership", membership.id, tenant_id=context.tenant_id
    )
    return membership


def _lock_and_recheck_admin(db: Session, context):
    tenant = db.scalar(
        select(Tenant)
        .where(Tenant.id == context.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    actor = db.scalar(
        select(Membership)
        .where(Membership.id == context.membership_id, Membership.tenant_id == context.tenant_id)
        .execution_options(populate_existing=True)
    )
    actor_user = db.scalar(
        select(User).where(User.id == context.user_id).execution_options(populate_existing=True)
    )
    if (
        not tenant
        or tenant.status != "active"
        or not actor
        or actor.status != "active"
        or actor.role != "admin"
        or not actor_user
        or actor_user.status != "active"
    ):
        raise forbidden()


def update_member(db: Session, context, membership_id: UUID, data, request):
    member = db.scalar(
        select(Membership).where(
            Membership.id == membership_id, Membership.tenant_id == context.tenant_id
        )
    )
    if not member:
        raise missing()
    db.scalar(select(User).where(User.id == member.user_id).with_for_update())
    _lock_and_recheck_admin(db, context)
    db.refresh(member)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise AppError(422, "empty_update", "At least one change is required")
    next_role = changes.get("role", member.role)
    next_status = changes.get("status", member.status)
    if (
        member.role == "admin"
        and member.status == "active"
        and (next_role != "admin" or next_status != "active")
    ):
        others = db.scalar(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.tenant_id == context.tenant_id,
                Membership.role == "admin",
                Membership.status == "active",
                Membership.id != member.id,
                User.status == "active",
            )
            .limit(1)
        )
        if not others:
            raise AppError(
                409, "last_tenant_admin", "Cannot remove the last active tenant administrator"
            )
    for field, value in changes.items():
        setattr(member, field, value)
    db.flush()
    record(db, request, "membership.update", "membership", member.id, tenant_id=context.tenant_id)
    return member


def get_visible_tenant(db: Session, tenant_id: UUID, user):
    query = select(Tenant).where(Tenant.id == tenant_id)
    if not user.is_platform_admin:
        query = query.join(Membership, Membership.tenant_id == Tenant.id).where(
            Membership.user_id == user.id, Membership.status == "active"
        )
    tenant = db.scalar(query)
    if not tenant:
        raise missing()
    return tenant
