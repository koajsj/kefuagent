"""Small shared tenant-aware reads; authorization is supplied by verified context."""

from sqlalchemy import select

from support_agent.errors import missing


def get_owned(db, model, context, resource_id, *, lock=False, refresh=False):
    query = select(model).where(model.id == resource_id, model.tenant_id == context.tenant_id)
    if lock:
        query = query.with_for_update()
    if lock or refresh:
        query = query.execution_options(populate_existing=True)
    resource = db.scalar(query)
    if resource is None:
        raise missing()
    return resource


def list_owned(db, model, context, limit, offset):
    return db.scalars(
        select(model)
        .where(model.tenant_id == context.tenant_id)
        .order_by(model.created_at, model.id)
        .limit(limit)
        .offset(offset)
    ).all()
