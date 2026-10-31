"""Static checks by default; --database inspects an explicitly configured CI database."""

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql

from support_agent.models import Base
from support_agent.preflight import EXPECTED_REVISION, RLS_TABLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", action="store_true", help="Inspect a fresh isolated CI database"
    )
    args = parser.parse_args()
    for command in (
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "ruff", "format", "--check", "."],
    ):
        subprocess.run(command, check=True)
    paths = [Path("scripts"), Path("src"), Path("migrations")]
    count = 0
    for root in paths:
        for path in root.rglob("*.py"):
            ast.parse(path.read_text(), filename=str(path))
            count += 1
    graph = ScriptDirectory.from_config(Config("alembic.ini"))
    if graph.get_heads() != [EXPECTED_REVISION]:
        raise SystemExit("Migration head does not match the supported application revision")
    revisions = list(graph.walk_revisions())
    if any(revision.is_branch_point or revision.is_merge_point for revision in revisions):
        raise SystemExit("Expected a single linear migration chain")
    # Render SQL only: no database connection, mutation or automatic migration.
    env = os.environ | {
        "DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/offline_schema",
        "MIGRATION_DATABASE_URL": "postgresql+psycopg://unused:unused@localhost/offline_schema",
    }
    sql = subprocess.check_output(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"], env=env, text=True
    )
    preparer = postgresql.dialect().identifier_preparer
    for table in Base.metadata.sorted_tables:
        if f"CREATE TABLE {preparer.quote(table.name)} (" not in sql:
            raise SystemExit(f"Missing migration table: {table.name}")
        for item in (*table.constraints, *table.indexes):
            if item.name and preparer.quote(item.name) not in sql:
                raise SystemExit(f"Missing migration constraint/index: {item.name}")
    for table in RLS_TABLES:
        for clause in ("ENABLE ROW LEVEL SECURITY", "FORCE ROW LEVEL SECURITY"):
            if f"ALTER TABLE {table} {clause}" not in sql:
                raise SystemExit(f"Missing RLS clause: {table}")
        if f"CREATE POLICY tenant_isolation ON {table}" not in sql:
            raise SystemExit(f"Missing tenant policy: {table}")
    print(
        f"Static checks passed: {count} Python files, {len(revisions)} migrations, RLS declarations"
    )
    if args.database:
        if not os.environ.get("DATABASE_URL"):
            raise SystemExit("--database requires explicit DATABASE_URL for a fresh isolated CI DB")
        subprocess.run([sys.executable, "-m", "alembic", "check"], check=True)
        from support_agent.config import Settings
        from support_agent.db import build_database
        from support_agent.preflight import inspect

        engine, _ = build_database(Settings())
        try:
            checks = inspect(Settings(), engine)["checks"]
            failures = [
                item["name"]
                for item in checks
                if item["name"] in {"database_role", "database_revision", "tenant_rls"}
                and item["status"] != "ok"
            ]
            if failures:
                raise SystemExit("Database inspection failed: " + ", ".join(failures))
        finally:
            engine.dispose()
        print("CI database schema, runtime role and FORCE RLS inspection passed")
    else:
        print("Live ORM/database schema comparison: NOT_RUN (use --database in isolated CI)")


if __name__ == "__main__":
    main()
