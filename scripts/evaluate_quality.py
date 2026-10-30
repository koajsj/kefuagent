"""Explicit offline evaluation only. Does not contain a live provider mode or credentials."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url

from support_agent.config import Settings


def main():
    settings = Settings()
    if "TEST_DATABASE_URL" not in os.environ:
        url = make_url(settings.database_url.get_secret_value())
        if url.host != "127.0.0.1" or url.database != "support_agent_dev":
            raise SystemExit("Set TEST_DATABASE_URL to a separately migrated test database")
        os.environ["TEST_DATABASE_URL"] = url.set(database="support_agent_test").render_as_string(
            hide_password=False
        )
    if "test" not in make_url(os.environ["TEST_DATABASE_URL"]).database:
        raise SystemExit("Refusing a non-test database")
    directory = Path(".local/evaluations")
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / f"quality-offline-{uuid4().hex}.json"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_quality.py", "-q", "--tb=short"],
        env=os.environ | {"P4_EVAL_REPORT": str(report.resolve())},
        check=False,
    )
    if result.returncode:
        raise SystemExit(result.returncode)
    print("Offline mock mechanics report:", report.resolve())
    print("Real model and semantic answer quality: NOT VERIFIED")


if __name__ == "__main__":
    main()
