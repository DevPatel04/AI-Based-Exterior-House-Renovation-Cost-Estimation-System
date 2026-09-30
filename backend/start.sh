#!/usr/bin/env bash
set -euo pipefail

# Always run from backend root (directory containing this script)
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Railway/Nixpacks often don't put the service root on PYTHONPATH
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

echo "Working dir: $ROOT"
echo "PYTHONPATH: $PYTHONPATH"
echo "Running migrations..."
alembic upgrade head

echo "Seeding roles/materials (safe to re-run)..."
python -m app.seed || true

echo "Starting API on PORT=${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
