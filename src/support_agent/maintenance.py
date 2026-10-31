"""Operator-only, tenant-explicit maintenance. No secret output or RLS bypass."""

import hashlib
import json
from uuid import uuid4

from sqlalchemy import func, select, text

from support_agent.db import set_tenant
from support_agent.errors import AppError
from support_agent.models import AuditEvent, ModelCall, ModelCredential, Tenant


def confirmation(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def scope(db, tenant_id, name, *, shared=False):
    if not db.get(Tenant, tenant_id):
        raise ValueError("Unknown tenant")
    lock = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    db.execute(
        text(f"SELECT {lock}(hashtextextended(:key,0))"), {"key": name + ":" + str(tenant_id)}
    )
    set_tenant(db, tenant_id)


def audit(db, tenant_id, action, details, *, outcome="success", reason=None):
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_id=None,
            action=action,
            resource_type="maintenance",
            resource_id=tenant_id,
            request_id=uuid4(),
            outcome=outcome,
            reason=reason,
            details=details
            | {"source": "operator_cli", "database_role": db.scalar(text("SELECT current_user"))},
        )
    )


def credential_rows(db, tenant_id, *, lock=False):
    stmt = (
        select(ModelCredential)
        .where(ModelCredential.tenant_id == tenant_id)
        .order_by(ModelCredential.id)
        .limit(1001)
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    rows = db.scalars(stmt).all()
    if len(rows) > 1000:
        raise ValueError("Rotation exceeds the reviewed 1000-credential transaction limit")
    return rows


def rotation_plan(db, tenant_id, ring, target, *, check=False):
    scope(db, tenant_id, "credential-rotation", shared=True)
    if target not in ring.keys:
        raise AppError(503, "credential_key_unavailable", "Target key version unavailable")
    rows = credential_rows(db, tenant_id)
    counts = {}
    for row in rows:
        version = ring.version(row.encrypted_secret)
        counts[version] = counts.get(version, 0) + 1
        if check:
            ring.open(tenant_id, row.ref, row.encrypted_secret)
    snapshot = [
        (str(row.id), hashlib.sha256(row.encrypted_secret.encode()).hexdigest()) for row in rows
    ]
    return {
        "tenant_id": str(tenant_id),
        "target": target,
        "counts": counts,
        "affected": sum(n for key, n in counts.items() if key != target),
        "checked": bool(check),
        "confirmation": confirmation([str(tenant_id), target, snapshot]),
    }


def rotate_credentials(db, tenant_id, ring, target, confirm):
    # Caller must stop old-config processes; the DB lock serializes this tenant's credential writes.
    scope(db, tenant_id, "credential-rotation")
    rows = credential_rows(db, tenant_id, lock=True)
    plan = rotation_plan(db, tenant_id, ring, target, check=True)
    if plan["confirmation"] != confirm:
        raise ValueError("Credential set changed; preview and confirm again")
    if db.scalar(
        select(func.count())
        .select_from(ModelCall)
        .where(ModelCall.tenant_id == tenant_id, ModelCall.status == "running")
    ):
        raise ValueError("Drain/reconcile running calls before rotating credentials")
    for row in rows:
        if ring.version(row.encrypted_secret) == target:
            continue
        secret = ring.open(tenant_id, row.ref, row.encrypted_secret)
        encoded = ring.seal(tenant_id, row.ref, secret, version=target)
        if ring.open(tenant_id, row.ref, encoded) != secret:
            raise RuntimeError("Credential re-encryption verification failed")
        row.encrypted_secret = encoded
    audit(db, tenant_id, "credential.rotate", {"target": target, "count": plan["affected"]})
    db.flush()
    db.commit()
    return {"target": target, "rotated": plan["affected"]}
