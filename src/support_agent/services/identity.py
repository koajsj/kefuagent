from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from support_agent.errors import AppError
from support_agent.models import AuthSession, Membership, Tenant, User
from support_agent.security import hash_password, token_digest, verify_password
from support_agent.services.audit import record

# Equal-cost password verification also for unknown logins; never a usable login.
_DUMMY_HASH = hash_password(token_urlsafe(32))


def login(db: Session, data, settings, request):
    user = db.scalar(select(User).where(User.login == data.login.lower()).with_for_update())
    valid = verify_password(
        user.password_hash if user else _DUMMY_HASH, data.password.get_secret_value()
    )
    now = datetime.now(UTC)
    if (
        not user
        or user.status != "active"
        or (user.locked_until and user.locked_until > now)
        or not valid
    ):
        if user and user.status == "active" and not (user.locked_until and user.locked_until > now):
            user.failed_logins += 1
            if user.failed_logins >= 5:
                user.locked_until = now + timedelta(minutes=5)
                user.failed_logins = 0
        record(
            db, request, "auth.login", "session", outcome="failure", reason="invalid_credentials"
        )
        # Authentication failure counters and failure audit are the sole intended mutation.
        db.commit()
        request.state.audit_handled = True
        raise AppError(
            401, "invalid_credentials", "Invalid credentials or temporarily unavailable account"
        )
    user.failed_logins = 0
    user.locked_until = None
    token = token_urlsafe(32)
    expires = now + timedelta(hours=settings.session_hours)
    db.add(AuthSession(user_id=user.id, token_hash=token_digest(token), expires_at=expires))
    request.state.actor_id = user.id
    record(db, request, "auth.login", "session")
    return {"access_token": token, "expires_at": expires}


def create_user(db: Session, data, request):
    user = User(
        login=data.login,
        display_name=data.display_name,
        password_hash=hash_password(data.password.get_secret_value()),
    )
    db.add(user)
    db.flush()
    record(db, request, "user.create", "user", user.id)
    return user


def set_user_status(db: Session, user_id: UUID, status: str, request):
    # Lock in stable order: user, then all involved tenant rows. Membership changes lock
    # target users before tenants too, preventing last-admin checks racing user deactivation.
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise AppError(404, "user_not_found", "User not found")
    if user.is_platform_admin:
        raise AppError(
            409, "protected_platform_admin", "Platform administrator lifecycle is CLI managed"
        )
    if status == "inactive":
        tenant_ids = db.scalars(
            select(Membership.tenant_id)
            .where(
                Membership.user_id == user_id,
                Membership.role == "admin",
                Membership.status == "active",
            )
            .order_by(Membership.tenant_id)
        ).all()
        for tenant_id in tenant_ids:
            db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
            other = db.scalar(
                select(Membership.id)
                .join(User, User.id == Membership.user_id)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.role == "admin",
                    Membership.status == "active",
                    User.status == "active",
                    User.id != user_id,
                )
                .limit(1)
            )
            if not other:
                raise AppError(
                    409, "last_tenant_admin", "Cannot disable the last active tenant administrator"
                )
        now = datetime.now(UTC)
        for token in db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        ):
            token.revoked_at = now
    user.status = status
    db.flush()
    record(db, request, "user.status", "user", user.id)
    return user


def logout(db: Session, session_id: UUID, request):
    session = db.get(AuthSession, session_id)
    session.revoked_at = datetime.now(UTC)
    record(db, request, "auth.logout", "session")


def list_users(db: Session, limit: int, offset: int):
    return db.scalars(
        select(User).order_by(User.created_at, User.id).limit(limit).offset(offset)
    ).all()
