#!/bin/sh
# Explicit local-only lifecycle. Never touches a system PostgreSQL service or existing cluster.
set -eu
cd "$(dirname "$0")/.."
project_dir=$(pwd)
local_dir="$project_dir/.local"
pg_bin="${PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
port="${SUPPORT_PG_PORT:-55439}"
case "${1:-}" in
  init)
    if [ -e "$local_dir/pgdata" ] || [ -e .env ]; then
      echo 'Refusing to overwrite an existing cluster or .env.' >&2
      exit 1
    fi
    mkdir -p "$local_dir/socket"
    chmod 700 "$local_dir" "$local_dir/socket"
    "$pg_bin/initdb" -D "$local_dir/pgdata" -U support_owner --auth-local=trust --auth-host=scram-sha-256 --no-locale -E UTF8 > "$local_dir/initdb.log"
    cat >> "$local_dir/pgdata/postgresql.conf" <<EOF
listen_addresses = '127.0.0.1'
port = $port
unix_socket_directories = '$local_dir/socket'
log_statement = 'none'
log_min_error_statement = 'panic'
log_error_verbosity = 'terse'
log_min_messages = 'fatal'
EOF
    "$pg_bin/pg_ctl" -D "$local_dir/pgdata" -l "$local_dir/postgres.log" start
    # Password never appears in a command argument, shell trace or source file.
    .venv/bin/python scripts/provision_local_db.py "$local_dir/socket" "$port"
    ;;
  start)
    "$pg_bin/pg_ctl" -D "$local_dir/pgdata" -l "$local_dir/postgres.log" start
    ;;
  stop)
    "$pg_bin/pg_ctl" -D "$local_dir/pgdata" stop -m fast
    ;;
  status)
    "$pg_bin/pg_ctl" -D "$local_dir/pgdata" status
    ;;
  *) echo 'Usage: scripts/local-postgres.sh init|start|stop|status'; exit 2 ;;
esac
