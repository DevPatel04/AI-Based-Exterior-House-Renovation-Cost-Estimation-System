#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo "Running migrations..."
alembic upgrade head

echo "Seeding roles/materials (safe to re-run)..."
python -m app.seed || true

echo "Starting API on PORT=${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
