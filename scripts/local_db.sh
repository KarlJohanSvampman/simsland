#!/usr/bin/env bash
# Postgres + Redis for running the backend without Docker (scripts/run_local.sh), with the settings docker-compose
# uses: database "sim", user/password postgres/postgres on :5432, scripts/init_db.sql applied once; Redis on :6379.
#   scripts/local_db.sh          start (creating the database the first time)
#   scripts/local_db.sh stop
#   PGDATA_DIR=/some/dir scripts/local_db.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$(dirname "$(command -v pg_ctl 2>/dev/null || ls -d /usr/lib/postgresql/*/bin/pg_ctl 2>/dev/null | sort -V | tail -1)")"
[ -x "$BIN/pg_ctl" ] || { echo "Postgres is not installed (no pg_ctl found)"; exit 1; }

if [ "$(id -u)" = 0 ]; then                    # Postgres refuses to run as root: run it as the postgres user
  DATA="${PGDATA_DIR:-/var/lib/postgresql/simsland}"; AS="su postgres -c"
else
  DATA="${PGDATA_DIR:-$HOME/.simsland/pgdata}"; AS="bash -c"
fi

if [ "${1:-start}" = stop ]; then
  $AS "'$BIN/pg_ctl' -D '$DATA' stop" || true
  redis-cli shutdown nosave 2>/dev/null || true
  exit 0
fi

if [ ! -f "$DATA/PG_VERSION" ]; then
  mkdir -p "$DATA"; [ "$(id -u)" = 0 ] && chown postgres:postgres "$DATA"
  $AS "'$BIN/initdb' -D '$DATA' -U postgres --auth=trust -E UTF8" >/dev/null
  FRESH=1
fi
$AS "'$BIN/pg_ctl' -D '$DATA' status" >/dev/null 2>&1 || $AS "'$BIN/pg_ctl' -D '$DATA' -l '$DATA/log' -o '-p 5432 -k /tmp' -w start"
if [ "${FRESH:-}" = 1 ]; then
  psql -h localhost -U postgres -qc "ALTER USER postgres PASSWORD 'postgres'" -c "CREATE DATABASE sim"
  psql -h localhost -U postgres -d sim -q -f "$ROOT/scripts/init_db.sql"
fi

redis-cli ping >/dev/null 2>&1 || redis-server --port 6379 --daemonize yes --dir "${REDIS_DIR:-/tmp}" >/dev/null
echo "Postgres: postgresql://postgres:postgres@localhost:5432/sim   ($DATA)"
echo "Redis:    localhost:6379 ($(redis-cli ping))"
