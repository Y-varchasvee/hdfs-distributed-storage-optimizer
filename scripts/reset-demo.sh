#!/usr/bin/env bash
# Deletes disposable demo data only: the managed HDFS directories of this project, and its metadata database.
#
# Paths are fixed literals, not arguments or variables, so this script cannot be pointed at anything else.
# It does not touch the downloaded dataset, source code, results or Docker volumes of other projects.
# Stop the backend first; it must restart with an empty database.
set -euo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"

if [ ! -f backend/app/main.py ] || [ ! -f docker-compose.yml ]; then
  echo "Refusing to run: this does not look like the HDFS Optimizer project."
  exit 1
fi
if curl -fs -m 2 http://127.0.0.1:8100/api/v1/health >/dev/null 2>&1; then
  echo "The backend is still running on port 8100. Stop it first."
  exit 1
fi

if [ "${1:-}" != "--yes" ]; then
  echo "This permanently deletes all managed files in HDFS under /hdfs-optimizer and the metadata database."
  read -r -p "Type RESET to continue: " answer
  [ "$answer" = "RESET" ] || { echo "Cancelled."; exit 1; }
fi

docker compose exec -T namenode hdfs dfs -rm -r -f -skipTrash \
  /hdfs-optimizer /hdfs-optimizer-experiments /hdfs-optimizer-tests /hdfs-optimizer-e2e /hdfs-optimizer-failure-tests

rm -f backend/data/metadata.db backend/data/metadata.db-wal backend/data/metadata.db-shm
rm -rf backend/data/spool
echo "Reset complete. Start the backend to create a new empty database."
