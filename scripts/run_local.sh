#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
export OLLAMA_BASE_URL=${OLLAMA_BASE_URL:-http://localhost:11434}
export DATABASE_URL=${DATABASE_URL:-postgresql://postgres:postgres@localhost:5432/sim}
uvicorn main:app --reload --host 0.0.0.0 --port 8000
