#!/usr/bin/env bash
# Clean shutdown of HDFS. Data stays in Docker volumes. Pass --vm to also stop the Colima VM.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"
docker compose --profile app stop
if [ "${1:-}" = "--vm" ]; then
  colima stop "$COLIMA_PROFILE"
fi
echo "Stopped. Data is kept. Start again with scripts/start-all.sh"
