from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from support_agent.db import set_tenant
from support_agent.errors import AppError, forbidden
from support_agent.models import AuthSession, Membership, Tenant, User
from support_agent.security import token_digest
from support_agent.tool_protocol import ExecutionContext

_bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    with request.app.state.sessions() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


Database = Annotated[Session, Depends(get_db, scope="function")]


def current_user(
    request: Request,
    db: Database,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
):
    if not credentials or len(credentials.credentials) > 256:
        raise AppError(401, "authentication_required", "A valid bearer session is required")
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == token_digest(credentials.credentials),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
        )
    )
    user = db.get(User, session.user_id) if session else None
    if not user or user.status != "active":
        raise AppError(401, "authentication_required", "A valid bearer session is required")
    request.state.actor_id = user.id
    request.state.session_id = session.id
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def platform_admin(user: CurrentUser):
    if not user.is_platform_admin:
        raise forbidden()
    return user


PlatformAdmin = Annotated[User, Depends(platform_admin)]


def tenant_context(
    request: Request, db: Database, user: CurrentUser, x_tenant_id: Annotated[UUID, Header()]
):
    link = db.scalar(
        select(Membership)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.tenant_id == x_tenant_id,
            Membership.user_id == user.id,
            Membership.status == "active",
            Tenant.status == "active",
        )
    )
    if not link:
        raise forbidden()
    set_tenant(db, link.tenant_id)
    request.state.tenant_id = link.tenant_id
    return ExecutionContext(
        tenant_id=link.tenant_id,
        user_id=user.id,
        membership_id=link.id,
        role=link.role,
        request_id=request.state.request_id,
    )


TenantContext = Annotated[ExecutionContext, Depends(tenant_context)]


def tenant_admin(context: TenantContext):
    if context.role != "admin":
        raise forbidden()
    return context


TenantAdmin = Annotated[ExecutionContext, Depends(tenant_admin)]


def resume_context(db, context, request, *, admin=False):
    """Revalidate after an explicit transaction boundary, then restore transaction-local RLS."""
    from dataclasses import replace

    user = db.get(User, context.user_id, populate_existing=True)
    auth = db.get(AuthSession, request.state.session_id, populate_existing=True)
    link = db.scalar(
        select(Membership)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.id == context.membership_id,
            Membership.user_id == context.user_id,
            Membership.tenant_id == context.tenant_id,
            Membership.status == "active",
            Tenant.status == "active",
        )
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or user.status != "active"
        or not auth
        or auth.revoked_at
        or auth.expires_at <= datetime.now(UTC)
    ):
        raise AppError(401, "authentication_required", "A valid bearer session is required")
    if not link or (admin and link.role != "admin"):
        raise forbidden()
    set_tenant(db, context.tenant_id)
    return replace(context, role=link.role)
