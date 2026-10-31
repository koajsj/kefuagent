"""Only used immediately after initdb for this project's new isolated local cluster."""

import os
import sys
from secrets import token_urlsafe

import psycopg
from psycopg import sql

socket, port = sys.argv[1:]
password = token_urlsafe(32)
with psycopg.connect(
    host=socket, port=int(port), user="support_owner", dbname="postgres", autocommit=True
) as db:
    db.execute(
        sql.SQL("CREATE ROLE support_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}").format(
            sql.Literal(password)
        )
    )
    db.execute("CREATE DATABASE support_agent_dev OWNER support_app")
    db.execute("REVOKE CONNECT ON DATABASE support_agent_dev FROM PUBLIC")
    db.execute("GRANT CONNECT ON DATABASE support_agent_dev TO support_app")
url = f"postgresql+psycopg://support_app:{password}@127.0.0.1:{port}/support_agent_dev"
fd = os.open(".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as stream:
    stream.write(f"DATABASE_URL={url}\nSESSION_HOURS=12\n")
print("Created dedicated dev database and private .env (0600); no users seeded.")
