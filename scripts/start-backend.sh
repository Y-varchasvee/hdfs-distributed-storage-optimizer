#!/usr/bin/env bash
# Starts the FastAPI backend on port 8100. Requires backend/.venv (see scripts/setup.sh).
set -euo pipefail
cd "$(dirname "$0")/../backend"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT:-8100}"
