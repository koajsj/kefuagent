from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from support_agent.config import Settings


def build_database(settings: Settings):
    engine = create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        echo=False,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=10000"},
    )
    return engine, sessionmaker(engine, expire_on_commit=False)


def set_tenant(db: Session, tenant_id) -> None:
    db.execute(
        text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
    )


def check_database(engine) -> None:
    with engine.connect() as connection:
        role = connection.execute(
            text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        ).one()
        if any(role):
            raise RuntimeError("HTTP database role must be NOSUPERUSER NOBYPASSRLS")
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != "0005_execution_delivery":
            raise RuntimeError("Database revision is not supported; run alembic upgrade head")
