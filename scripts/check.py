"""Run bounded checks against the separately migrated test DB; no reset or deletion."""

import os
import subprocess
import sys

from sqlalchemy.engine import make_url

from support_agent.config import Settings


def main():
    settings = Settings()
    if "TEST_DATABASE_URL" not in os.environ:
        local_url = make_url(settings.database_url.get_secret_value())
        if local_url.database != "support_agent_dev" or local_url.host != "127.0.0.1":
            raise SystemExit(
                "Set TEST_DATABASE_URL explicitly for a separately migrated test database"
            )
        os.environ["TEST_DATABASE_URL"] = local_url.set(
            database="support_agent_test"
        ).render_as_string(hide_password=False)
    test_settings = Settings(database_url=os.environ["TEST_DATABASE_URL"])
    if "test" not in make_url(test_settings.database_url.get_secret_value()).database:
        raise SystemExit("Refusing a database whose name does not contain test")
    checks = [
        ([sys.executable, "-m", "ruff", "check", "."], None),
        ([sys.executable, "-m", "ruff", "format", "--check", "."], None),
        ([sys.executable, "-m", "alembic", "check"], None),
        (
            [sys.executable, "-m", "alembic", "check"],
            os.environ
            | {
                "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
                "MIGRATION_DATABASE_URL": os.environ["TEST_DATABASE_URL"],
            },
        ),
        ([sys.executable, "-m", "pytest"], None),
    ]
    for command, env in checks:
        result = subprocess.run(command, env=env, timeout=60 if "pytest" in command else 30)
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
