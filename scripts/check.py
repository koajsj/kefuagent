"""Static source and offline migration checks; never connects to a database."""

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.dialects import postgresql

from support_agent.models import Base
from support_agent.preflight import EXPECTED_REVISION, RLS_TABLES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
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
    schema_index_names = set()
    for table in Base.metadata.sorted_tables:
        names = [item.name for item in table.constraints if item.name]
        if len(names) != len(set(names)):
            raise SystemExit(f"Duplicate constraint name: {table.name}")
        for item in (
            *table.indexes,
            *[
                c
                for c in table.constraints
                if isinstance(c, (PrimaryKeyConstraint, UniqueConstraint))
            ],
        ):
            if item.name in schema_index_names:
                raise SystemExit(f"Duplicate backing index name: {item.name}")
            schema_index_names.add(item.name)
        for foreign_key in table.foreign_key_constraints:
            target = foreign_key.referred_table
            columns = tuple(element.column.name for element in foreign_key.elements)
            unique_keys = {
                tuple(column.name for column in constraint.columns)
                for constraint in target.constraints
                if isinstance(constraint, (PrimaryKeyConstraint, UniqueConstraint))
            }
            if columns not in unique_keys:
                raise SystemExit(f"Foreign key lacks a declared unique target: {foreign_key.name}")
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
    print("Runtime behavior and live database schema: NEEDS_RUNTIME_VERIFICATION")


if __name__ == "__main__":
    main()
