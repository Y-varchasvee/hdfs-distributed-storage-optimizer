#!/usr/bin/env bash
# Builds the application container images, aborting if the host's free disk falls below a safety margin.
# Image builds grow the VM's disk on the host; on a nearly full machine that can make every write fail.
set -uo pipefail
source "$(dirname "$0")/env.sh"
cd "$PROJECT_ROOT"
MINIMUM_FREE_KB=$(( ${MINIMUM_FREE_GB:-2} * 1024 * 1024 ))
free_kb() { df -k "$PROJECT_ROOT" | awk 'NR==2 {print $4}'; }

if [ "$(free_kb)" -lt "$MINIMUM_FREE_KB" ]; then
  echo "Refusing to build: less than ${MINIMUM_FREE_GB:-2} GB free on the host."
  exit 2
fi
docker compose --profile app build backend frontend &
BUILD=$!
while kill -0 "$BUILD" 2>/dev/null; do
  if [ "$(free_kb)" -lt "$MINIMUM_FREE_KB" ]; then
    echo "ABORTED: host free disk fell below the safety margin. Cleaning up the build."
    kill "$BUILD" 2>/dev/null
    wait "$BUILD" 2>/dev/null
    docker image prune -f >/dev/null
    colima ssh -p "$COLIMA_PROFILE" -- sudo fstrim -a >/dev/null 2>&1 || true
    exit 3
  fi
  sleep 2
done
wait "$BUILD"
