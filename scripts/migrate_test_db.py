"""Explicit additive migration for the project's independently created local test DB."""

import os
import subprocess
import sys

from sqlalchemy.engine import make_url

from support_agent.config import Settings

url = make_url(Settings().database_url.get_secret_value())
if url.database != "support_agent_dev" or url.host != "127.0.0.1":
    raise SystemExit(
        "Only for local support_agent_dev -> support_agent_test; external setup must specify its own database"
    )
test_url = url.set(database="support_agent_test").render_as_string(hide_password=False)
raise SystemExit(
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=os.environ | {"DATABASE_URL": test_url, "MIGRATION_DATABASE_URL": test_url},
    ).returncode
)
