from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from support_agent.config import Settings

EXPECTED_REVISION = "0020_conversation_idempotency"


def build_database(settings: Settings):
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        echo=False,
        # Lock-followed authorization/idempotency reads need a fresh statement snapshot.
        # Snapshot exports opt into REPEATABLE READ on their own transaction.
        isolation_level="READ COMMITTED",
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000"},
    )
    from support_agent.observability import instrument

    instrument(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def private_tenant(db: Session, tenant_id=None, *, allow_empty=False):
    from sqlalchemy import select

    from support_agent.errors import AppError
    from support_agent.models import Tenant

    ids = list(db.scalars(select(Tenant.id).order_by(Tenant.id).limit(2)))
    if len(ids) > 1:
        raise AppError(
            409,
            "private_deployment_conflict",
            "This deployment contains multiple enterprises; an operator must review isolation before use",
        )
    if not ids:
        if allow_empty:
            return None
        raise AppError(
            409, "private_deployment_uninitialized", "Initialize this deployment's enterprise first"
        )
    if tenant_id is not None and str(ids[0]) != str(tenant_id):
        raise AppError(
            403, "private_deployment_scope", "Resource is outside this deployment's enterprise"
        )
    return ids[0]


def set_tenant(db: Session, tenant_id) -> None:
    private_tenant(db, tenant_id)
    db.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
    )


def check_database(engine) -> None:
    with engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication "
                "FROM pg_roles WHERE rolname=current_user"
            )
        ).one()
        if any(role):
            raise RuntimeError("HTTP database role has unsafe administrative privileges")
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if len(connection.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 2")).all()) > 1:
            raise RuntimeError(
                "Private deployment contains multiple enterprises; operator isolation review required"
            )
        if revision != EXPECTED_REVISION:
            raise RuntimeError("Database revision is not supported; run alembic upgrade head")


def authorization_gate(db, *, user_id=None, tenant_id=None, exclusive=False):
    """Account revocations and protected staff commands take gates before row locks."""
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    for kind, identity in (("user", user_id), ("tenant", tenant_id)):
        if identity is not None:
            db.execute(
                text(f"SELECT {function}(hashtextextended(:key, 0))"),
                {"key": f"authorization:{kind}:{identity}"},
            )
