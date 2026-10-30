from sqlalchemy import select

from support_agent.credentials import decrypt_secret, encrypt_secret
from support_agent.errors import AppError
from support_agent.models import ModelCredential
from support_agent.providers import validate_base_url
from support_agent.schemas import RuntimeConfig
from support_agent.services.audit import record
from support_agent.services.resources import get_owned


def master_key(request):
    value = request.app.state.settings.credential_master_key
    return value.get_secret_value() if value else None


def create_credential(db, context, data, request):
    encrypted = encrypt_secret(
        master_key(request), context.tenant_id, data.ref, data.api_key.get_secret_value()
    )
    row = ModelCredential(
        tenant_id=context.tenant_id,
        created_by=context.user_id,
        ref=data.ref,
        encrypted_secret=encrypted,
        enabled=data.enabled,
    )
    db.add(row)
    db.flush()
    record(db, request, "credential.create", "credential", row.id, tenant_id=context.tenant_id)
    return row


def update_credential(db, context, credential_id, data, request):
    row = get_owned(db, ModelCredential, context, credential_id, lock=True)
    if row.ref != data.ref:
        raise AppError(
            409, "credential_ref_immutable", "Create a new credential reference instead of renaming"
        )
    row.encrypted_secret = encrypt_secret(
        master_key(request), context.tenant_id, row.ref, data.api_key.get_secret_value()
    )
    row.enabled = data.enabled
    record(db, request, "credential.update", "credential", row.id, tenant_id=context.tenant_id)
    db.flush()
    return row


def delete_credential(db, context, credential_id, request):
    row = get_owned(db, ModelCredential, context, credential_id, lock=True)
    db.delete(row)
    record(
        db, request, "credential.delete", "credential", credential_id, tenant_id=context.tenant_id
    )
    db.flush()


def resolve_config(db, context, config, request):
    if (
        config.provider != "openai_compatible"
        or not config.enabled
        or not config.base_url
        or not config.credential_ref
    ):
        raise AppError(
            409,
            "model_configuration_unavailable",
            "Enable an OpenAI-compatible configuration with URL and credential reference",
        )
    url = validate_base_url(config.base_url, request.app.state.settings.model_allowed_hosts)
    credential = db.scalar(
        select(ModelCredential).where(
            ModelCredential.tenant_id == context.tenant_id,
            ModelCredential.ref == config.credential_ref,
            ModelCredential.enabled.is_(True),
        )
    )
    if credential is None:
        raise AppError(
            409, "credential_unavailable", "An enabled credential in this tenant is required"
        )
    secret = decrypt_secret(
        master_key(request), context.tenant_id, credential.ref, credential.encrypted_secret
    )
    return {
        "base_url": url,
        "api_key": secret,
        "model": config.model,
        "runtime": RuntimeConfig.model_validate(config.runtime).model_dump(),
    }
