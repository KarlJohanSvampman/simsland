#!/usr/bin/env bash
# The backend without Docker, as one process (SIM_ROLE=all). Start the database first: scripts/local_db.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
export OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://192.168.10.176:11434}
export OLLAMA_MODEL=${OLLAMA_MODEL:-llama3.1:latest}
export DATABASE_URL=${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/sim}
export REDIS_HOST=${REDIS_HOST:-localhost}
export PYTHONPATH=.
# the code reads these where docker-compose mounts them
for pair in "/resources:$ROOT/resources" "/data/simulations:$ROOT/simulations"; do
  target="${pair%%:*}"; src="${pair#*:}"
  if [ ! -e "$target" ]; then
    mkdir -p "$(dirname "$target")" 2>/dev/null && ln -sfn "$src" "$target" 2>/dev/null \
      || { echo "$target is missing: run once as root:  mkdir -p $(dirname "$target") && ln -s $src $target"; exit 1; }
  fi
done
psql "$DATABASE_URL" -qtAc "select 1" >/dev/null 2>&1 || { echo "No database at $DATABASE_URL -- run scripts/local_db.sh"; exit 1; }
exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
