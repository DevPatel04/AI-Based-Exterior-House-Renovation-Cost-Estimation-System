#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
export PORT="${PORT:-3000}"
echo "Starting Next.js on 0.0.0.0:${PORT}"
exec npx next start --hostname 0.0.0.0 --port "${PORT}"
