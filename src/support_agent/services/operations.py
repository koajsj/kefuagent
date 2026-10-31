"""Tenant-scoped inbox, collaboration and row-locked operator control."""

from datetime import UTC, datetime

from sqlalchemy import select

from support_agent.errors import AppError, forbidden
from support_agent.models import Collaboration, Conversation, Membership, User
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def service_times(row):
    now = datetime.now(UTC)
    response = (
        (row.first_response_at - row.created_at).total_seconds() if row.first_response_at else None
    )
    wait_end = row.human_started_at or row.resolved_at or now
    wait = max(0, (wait_end - row.waiting_since).total_seconds()) if row.waiting_since else None
    resolution = (
        max(0, (row.resolved_at - row.created_at).total_seconds()) if row.resolved_at else None
    )
    # 5-minute first response / human wait, 24-hour resolution; urgent uses 1 minute / 1 hour.
    response_limit, resolution_limit = (60, 3600) if row.priority == "urgent" else (300, 86400)
    ratios = []
    if row.status == "open":
        if row.first_response_at is None:
            ratios.append(max(0, (now - row.created_at).total_seconds()) / response_limit)
        if row.support_state == "waiting" and wait is not None:
            ratios.append(wait / response_limit)
        ratios.append(max(0, (now - row.created_at).total_seconds()) / resolution_limit)
    ratio = max(ratios, default=0)
    return {
        "first_response_seconds": response,
        "human_wait_seconds": wait,
        "resolution_seconds": resolution,
        "state": "overdue" if ratio >= 1 else "due_soon" if ratio >= 0.8 else "ok",
    }


def check_version(row, expected):
    if expected is not None and row.version != expected:
        raise AppError(409, "version_conflict", "Conversation changed; reload before changing it")


def operator(db, context, user_id):
    user = db.scalar(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.tenant_id == context.tenant_id,
            Membership.status == "active",
            Membership.user_id == user_id,
            User.status == "active",
        )
        .with_for_update(read=True)
    )
    if not user:
        raise AppError(
            422, "invalid_assignee", "Assignee must be an active member of this enterprise"
        )
    return user


def operators(db, context):
    return (
        db.execute(
            select(User.id, User.display_name)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == context.tenant_id,
                Membership.status == "active",
                User.status == "active",
            )
            .order_by(User.display_name, User.id)
            .limit(500)
        )
        .mappings()
        .all()
    )


def controlled(db, context, row):
    if context.role == "admin":
        return
    if row.assignee_id != context.user_id:
        raise forbidden()
    operator(db, context, context.user_id)


def log(db, context, row, request, kind, details, content=""):
    item = Collaboration(
        tenant_id=context.tenant_id,
        conversation_id=row.id,
        actor_id=context.user_id,
        kind=kind,
        content=content,
        details=details,
    )
    db.add(item)
    record(
        db,
        request,
        "conversation." + kind,
        "conversation",
        row.id,
        tenant_id=context.tenant_id,
        details=details,
    )
    return item


def update(db, context, cid, data, request):
    row = get_owned(db, Conversation, context, cid, lock=True)
    check_version(row, data.expected_version)
    controlled(db, context, row)
    fields = data.model_dump(exclude_unset=True, exclude={"expected_version"})
    if "assignee_id" in fields:
        if context.role != "admin":
            raise forbidden()
        if fields["assignee_id"] is not None:
            operator(db, context, fields["assignee_id"])
        if row.support_state == "human" and fields["assignee_id"] is None:
            raise AppError(
                409, "handoff_required", "Return to waiting before unassigning a human conversation"
            )
    if fields.get("priority", "normal") is None or fields.get("tags", []) is None:
        raise AppError(422, "invalid_operations", "Priority and tags cannot be null")
    if "category" in fields:
        fields["category"] = fields["category"] or ""
    old_assignee = row.assignee_id
    changed = {key: value for key, value in fields.items() if value != getattr(row, key)}
    if changed:
        for key, value in changed.items():
            setattr(row, key, value)
        row.version += 1
        row.updated_at = datetime.now(UTC)
        details = {"fields": sorted(changed), "version": row.version}
        if "assignee_id" in changed:
            details.update(
                previous=str(old_assignee) if old_assignee else None,
                assignee=str(row.assignee_id) if row.assignee_id else None,
            )
        log(
            db,
            context,
            row,
            request,
            "assignment" if "assignee_id" in changed else "metadata",
            details,
        )
    db.flush()
    return row


def notes(db, context, cid, limit, offset):
    get_owned(db, Conversation, context, cid)
    return db.scalars(
        select(Collaboration)
        .where(Collaboration.tenant_id == context.tenant_id, Collaboration.conversation_id == cid)
        .order_by(Collaboration.created_at.desc(), Collaboration.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()


def add_note(db, context, cid, data, request):
    row = get_owned(db, Conversation, context, cid, lock=True)
    item = log(db, context, row, request, "note", {}, data.content)
    # Notes are not Message objects, never included in transcript, summary or analytics previews.
    row.updated_at = datetime.now(UTC)
    db.flush()
    return item


def listing(db, context, *, limit, offset, q, queue, assignee_id, priority, sort):
    stmt = select(Conversation).where(Conversation.tenant_id == context.tenant_id)
    if q:
        stmt = stmt.where(Conversation.subject.icontains(q, autoescape=True))
    if queue in {"human", "ai", "resolved"}:
        stmt = stmt.where(Conversation.support_state == queue)
    elif queue == "pending":
        stmt = stmt.where(Conversation.support_state == "waiting")
    elif queue == "unassigned":
        stmt = stmt.where(Conversation.assignee_id.is_(None), Conversation.status == "open")
    elif queue == "mine":
        stmt = stmt.where(Conversation.assignee_id == context.user_id)
    if assignee_id:
        stmt = stmt.where(Conversation.assignee_id == assignee_id)
    if priority:
        stmt = stmt.where(Conversation.priority == priority)
    order = (Conversation.created_at, Conversation.id)
    return db.scalars(
        stmt.order_by(*(c.desc() for c in order) if sort == "newest" else order)
        .limit(limit)
        .offset(offset)
    ).all()


def public_reply_guard(db, context, row, request):
    from support_agent.models import VisitorSession
    from support_agent.services.public_delivery import locate

    visitor = db.scalar(
        select(VisitorSession)
        .where(
            VisitorSession.tenant_id == context.tenant_id, VisitorSession.conversation_id == row.id
        )
        .with_for_update(read=True)
    )
    if not visitor or visitor.ended_at or visitor.expires_at <= datetime.now(UTC):
        raise AppError(409, "visitor_access_revoked", "Visitor session is unavailable")
    publication, _, _ = locate(db, visitor.publication_id, request)
    if (
        publication.tenant_id != context.tenant_id
        or publication.version != visitor.publication_version
    ):
        raise AppError(409, "visitor_access_revoked", "Public delivery is no longer authorized")
