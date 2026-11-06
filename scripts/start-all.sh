#!/usr/bin/env bash
# Starts HDFS, then the backend and frontend in the background of this script. Ctrl+C stops the two app servers.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"

"$PROJECT_ROOT/scripts/start-runtime.sh"
source "$PROJECT_ROOT/scripts/env.sh"
docker compose up -d --wait

mkdir -p backend/data
scripts/start-backend.sh > backend/data/backend.log 2>&1 &
BACKEND_PID=$!
scripts/start-frontend.sh > backend/data/frontend.log 2>&1 &
FRONTEND_PID=$!
trap 'kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  if curl -fs -m 2 http://127.0.0.1:8100/api/v1/health >/dev/null && curl -fs -m 2 -o /dev/null http://127.0.0.1:3100/; then break; fi
  sleep 1
done

cat <<INFO
HDFS Optimizer is running.
  Application      http://localhost:3100
  API docs         http://localhost:8100/docs
  NameNode UI      http://localhost:9870
Logs are in backend/data/. Press Ctrl+C to stop the application; HDFS keeps running (scripts/stop-all.sh stops it).
INFO
wait
