#!/usr/bin/env bash
# Installs project dependencies and builds the Hadoop image. Writes only inside this project and Docker.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"

PYTHON="$(command -v python3.12 || command -v python3.13 || command -v python3)"
echo "Using $("$PYTHON" --version)"
[ -d backend/.venv ] || "$PYTHON" -m venv backend/.venv
backend/.venv/bin/pip install -q --upgrade pip
backend/.venv/bin/pip install -q -r backend/requirements-dev.txt -r reports/source/requirements.txt

(cd frontend && npm ci --no-audit --no-fund && npm run build)

"$PROJECT_ROOT/scripts/start-runtime.sh"
source "$PROJECT_ROOT/scripts/env.sh"
docker compose build namenode
echo "Setup complete. Next: scripts/start-all.sh"
