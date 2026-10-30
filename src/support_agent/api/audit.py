from fastapi import APIRouter, Query

from support_agent.dependencies import Database, PlatformAdmin, TenantAdmin
from support_agent.schemas import AuditOut
from support_agent.services.audit import list_events, list_platform_events

router = APIRouter(tags=["Audit"])


@router.get("/audit-events", response_model=list[AuditOut])
def tenant_audit(
    db: Database,
    context: TenantAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    return list_events(db, context.tenant_id, limit, offset)


@router.get("/platform/audit-events", response_model=list[AuditOut])
def platform_audit(
    db: Database,
    admin: PlatformAdmin,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    # Platform operators see platform management and authentication events only.
    return list_platform_events(db, limit, offset)
