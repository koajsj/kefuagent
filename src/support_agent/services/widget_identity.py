"""Verified website ownership plus server-signed, replay-protected bootstrap grants."""

import hashlib
import hmac
import json
import secrets
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select, text

from support_agent.credentials import Keyring
from support_agent.dependencies import locked_staff_context
from support_agent.errors import AppError
from support_agent.models import WidgetBootstrap, WidgetSite
from support_agent.security import token_digest
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def normalize_origin(value):
    import ipaddress

    parsed = urlsplit(value)
    host = parsed.hostname or ""
    try:
        host = host.encode("idna").decode().lower()
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Website origin requires a public DNS name")
    if (
        parsed.scheme != "https"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or "." not in host
        or host.endswith(".")
        or not all(
            part
            and len(part) <= 63
            and part[0].isalnum()
            and part[-1].isalnum()
            and all(c.isalnum() or c == "-" for c in part)
            for part in host.split(".")
        )
    ):
        raise ValueError("Use one exact HTTPS origin without a path, wildcard or credentials")
    return "https://" + host


def create(db, context, data, request):
    from support_agent.services.public_delivery import locate

    context = locked_staff_context(db, context, request, admin=True)
    from support_agent.services.model_configs import credential_lock

    credential_lock(db, context.tenant_id)
    publication, _, _ = locate(db, data.publication_id, request)
    if publication.tenant_id != context.tenant_id:
        raise AppError(403, "widget_scope_denied", "Publication is outside this enterprise")
    challenge, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    from uuid import uuid4

    row = WidgetSite(
        id=uuid4(),
        tenant_id=context.tenant_id,
        publication_id=publication.id,
        origin=data.origin,
        challenge_hash=token_digest(challenge),
        challenge_expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    row.encrypted_secret = Keyring(request.app.state.settings).seal(
        context.tenant_id, "widget-site:" + str(row.id), secret
    )
    db.add(row)
    db.flush()
    record(db, request, "widget_site.create", "widget_site", row.id, tenant_id=context.tenant_id)
    return {
        "site": row,
        "challenge": challenge,
        "server_secret": secret,
        "verification_url": row.origin + "/.well-known/kefuagent-site-verification",
    }


def verify(db, context, site_id, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    row = get_owned(db, WidgetSite, context, site_id)
    version, origin = row.version, row.origin
    if row.challenge_expires_at <= datetime.now(UTC) or not hmac.compare_digest(
        row.challenge_hash, token_digest(data.challenge)
    ):
        raise AppError(
            409,
            "widget_challenge_invalid",
            "Challenge is expired or invalid; register a new origin configuration",
        )
    db.commit()  # Never retain account/resource locks during remote ownership verification.
    try:
        result = subprocess.run(
            [sys.executable, "-m", "support_agent.widget_verification"],
            input=json.dumps({"origin": origin}).encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        valid = result.returncode == 0 and hmac.compare_digest(
            result.stdout.strip(), token_digest(data.challenge).encode()
        )
    except (subprocess.TimeoutExpired, OSError):
        valid = False
    if not valid:
        raise AppError(
            409,
            "widget_verification_failed",
            "HTTPS ownership verification failed; no redirects or private destinations are accepted",
        )
    context = locked_staff_context(db, context, request, admin=True)
    row = get_owned(db, WidgetSite, context, site_id, lock=True)
    if (
        row.version != version
        or row.origin != origin
        or row.challenge_expires_at <= datetime.now(UTC)
    ):
        raise AppError(409, "widget_site_changed", "Site configuration changed during verification")
    row.verified_at = datetime.now(UTC)
    row.verification_expires_at = row.verified_at + timedelta(days=30)
    row.version += 1
    record(db, request, "widget_site.verified", "widget_site", row.id, tenant_id=context.tenant_id)
    db.flush()
    return row


def change(db, context, site_id, data, request):
    context = locked_staff_context(db, context, request, admin=True)
    row = get_owned(db, WidgetSite, context, site_id, lock=True)
    if row.version != data.expected_version:
        raise AppError(409, "widget_site_changed", "Refresh the site configuration")
    if data.enabled:
        ensure_site(row)
    row.enabled = data.enabled
    row.version += 1  # Every switch revokes all earlier grants and sessions.
    record(
        db,
        request,
        "widget_site.update",
        "widget_site",
        row.id,
        tenant_id=context.tenant_id,
        details={"enabled": row.enabled, "version": row.version},
    )
    db.flush()
    return row


def ensure_site(site, *, active=False):
    if (
        not site
        or not site.verified_at
        or not site.verification_expires_at
        or site.verification_expires_at <= datetime.now(UTC)
        or (active and not site.enabled)
    ):
        raise AppError(
            403,
            "widget_site_untrusted",
            "A current verified and enabled website configuration is required",
        )


def instance_id(settings):
    if settings.widget_instance_id is None:
        raise AppError(
            503,
            "widget_instance_unconfigured",
            "Configure a stable unique WIDGET_INSTANCE_ID before website delivery",
        )
    return settings.widget_instance_id


def signed_payload(settings, publication, site, nonce, expires_at):
    # This exact JSON is signed by the WEBSITE BACKEND, never by browser JavaScript.
    return json.dumps(
        {
            "aud": settings.web_origin,
            "instance_id": str(instance_id(settings)),
            "publication_id": str(publication.id),
            "publication_version": publication.version,
            "site_id": str(site.id),
            "site_version": site.version,
            "origin": site.origin,
            "nonce": str(nonce),
            "expires_at": expires_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def bootstrap(db, pid, data, request):
    from support_agent.services.public_delivery import locate

    publication, _, _ = locate(db, pid, request)
    # Browser clients use the platform iframe: cross-origin fetch is intentionally
    # unsupported (no wildcard CORS), and a forged Origin never replaces the MAC.
    if request.headers.get("origin") != request.app.state.settings.web_origin:
        raise AppError(
            403, "widget_origin_denied", "Bootstrap must be exchanged by the configured iframe"
        )
    site = db.scalar(
        select(WidgetSite)
        .where(
            WidgetSite.tenant_id == publication.tenant_id,
            WidgetSite.id == data.site_id,
            WidgetSite.publication_id == publication.id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    ensure_site(site, active=True)
    now = datetime.now(UTC)
    if not now.timestamp() < data.expires_at <= now.timestamp() + 60:
        raise AppError(
            403, "widget_assertion_expired", "Website assertion must expire within 60 seconds"
        )
    secret = Keyring(request.app.state.settings).open(
        site.tenant_id, "widget-site:" + str(site.id), site.encrypted_secret
    )
    signature = hmac.new(
        secret.encode(),
        signed_payload(request.app.state.settings, publication, site, data.nonce, data.expires_at),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, data.signature):
        raise AppError(403, "widget_assertion_invalid", "Website backend signature is invalid")
    # Unique nonce provides durable cross-process replay protection. No credential
    # is reissued on a retry; the website backend must issue a fresh assertion.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": "widget-bootstrap:" + str(site.tenant_id)},
    )
    count = db.scalar(
        select(func.count())
        .select_from(WidgetBootstrap)
        .where(
            WidgetBootstrap.tenant_id == site.tenant_id,
            WidgetBootstrap.created_at >= now.replace(hour=0, minute=0, second=0, microsecond=0),
        )
    )
    if count >= 2000:
        raise AppError(429, "widget_bootstrap_limit", "Daily bootstrap limit reached")
    from uuid import uuid4

    grant_id = uuid4()
    expires_at = datetime.fromtimestamp(data.expires_at, UTC)
    token = signed_credential(
        request.app.state.settings,
        "bootstrap",
        credential_scope(publication, site, grant_id, expires_at),
    )
    row = WidgetBootstrap(
        id=grant_id,
        tenant_id=site.tenant_id,
        site_id=site.id,
        site_version=site.version,
        publication_version=publication.version,
        nonce=data.nonce,
        token_hash=token_digest(token),
        expires_at=expires_at,
    )
    db.add(row)
    db.flush()
    return {"token": token, "expires_at": row.expires_at, "origin": site.origin}


def consume(db, publication, token, request):
    if request.headers.get("origin") != request.app.state.settings.web_origin:
        raise AppError(403, "widget_origin_denied", "Use the configured iframe")
    # Site first, then grant: shared site lock serializes disable with consumption.
    grant = db.scalar(
        select(WidgetBootstrap).where(
            WidgetBootstrap.tenant_id == publication.tenant_id,
            WidgetBootstrap.token_hash == token_digest(token),
        )
    )
    if not grant:
        raise AppError(401, "widget_bootstrap_invalid", "A fresh website bootstrap is required")
    site = db.scalar(
        select(WidgetSite)
        .where(
            WidgetSite.tenant_id == publication.tenant_id,
            WidgetSite.id == grant.site_id,
            WidgetSite.publication_id == publication.id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    ensure_site(site, active=True)
    grant = db.scalar(
        select(WidgetBootstrap)
        .where(WidgetBootstrap.id == grant.id, WidgetBootstrap.tenant_id == publication.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        grant.consumed_at
        or grant.expires_at <= datetime.now(UTC)
        or grant.site_version != site.version
        or grant.publication_version != publication.version
    ):
        raise AppError(
            401, "widget_bootstrap_invalid", "Bootstrap is expired, revoked or already consumed"
        )
    if not verify_credential(
        request.app.state.settings,
        "bootstrap",
        credential_scope(publication, site, grant.id, grant.expires_at),
        token,
    ):
        raise AppError(401, "widget_bootstrap_invalid", "Bootstrap signature is no longer valid")
    grant.consumed_at = datetime.now(UTC)
    return site


def authenticate_site(db, visitor, request):
    site = db.scalar(
        select(WidgetSite)
        .where(
            WidgetSite.tenant_id == visitor.tenant_id,
            WidgetSite.id == visitor.site_id,
            WidgetSite.publication_id == visitor.publication_id,
        )
        .with_for_update(read=True)
        .execution_options(populate_existing=True)
    )
    ensure_site(site, active=True)
    if visitor.site_version != site.version or request.headers.get("origin") not in (
        None,
        request.app.state.settings.web_origin,
    ):
        raise AppError(401, "visitor_access_revoked", "Website authorization is no longer current")
    return site


def renew(db, context, site_id, request):
    """Rotate the backend secret and challenge, revoking every old website grant."""
    context = locked_staff_context(db, context, request, admin=True)
    from support_agent.services.model_configs import credential_lock

    credential_lock(db, context.tenant_id)
    row = get_owned(db, WidgetSite, context, site_id, lock=True)
    challenge, secret = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    row.enabled = False
    row.verified_at = row.verification_expires_at = None
    row.challenge_hash = token_digest(challenge)
    row.challenge_expires_at = datetime.now(UTC) + timedelta(hours=24)
    row.encrypted_secret = Keyring(request.app.state.settings).seal(
        context.tenant_id, "widget-site:" + str(row.id), secret
    )
    row.version += 1
    record(
        db,
        request,
        "widget_site.rotate",
        "widget_site",
        row.id,
        tenant_id=context.tenant_id,
        details={"version": row.version},
    )
    db.flush()
    return {
        "site": row,
        "challenge": challenge,
        "server_secret": secret,
        "verification_url": row.origin + "/.well-known/kefuagent-site-verification",
    }


def credential_scope(publication, site, identity, expires_at, *, conversation_id=None):
    return {
        "tenant_id": str(publication.tenant_id),
        "publication_id": str(publication.id),
        "publication_version": publication.version,
        "site_id": str(site.id),
        "site_version": site.version,
        "id": str(identity),
        "expires_at": int(expires_at.timestamp()),
        "conversation_id": str(conversation_id) if conversation_id else None,
    }


def signed_credential(settings, purpose, scope, *, nonce=None):
    if settings.public_rate_key is None:
        raise AppError(
            503, "public_rate_key_unavailable", "Configure the private public delivery key"
        )
    nonce = nonce or secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "purpose": purpose,
            "aud": settings.web_origin,
            "instance_id": str(instance_id(settings)),
            "nonce": nonce,
            "scope": scope,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    key = hmac.new(
        settings.public_rate_key.get_secret_value().encode(),
        b"kefu-widget-credentials-v1",
        hashlib.sha256,
    ).digest()
    return "ks1." + nonce + "." + hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_credential(settings, purpose, scope, raw):
    parts = raw.split(".")
    return (
        len(parts) == 3
        and parts[0] == "ks1"
        and len(parts[1]) == 43
        and hmac.compare_digest(raw, signed_credential(settings, purpose, scope, nonce=parts[1]))
    )
