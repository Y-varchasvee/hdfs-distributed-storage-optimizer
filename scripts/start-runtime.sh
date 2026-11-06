#!/usr/bin/env bash
# Starts a dedicated Colima VM (macOS). Skips itself when any Docker daemon is already reachable.
set -euo pipefail
source "$(dirname "$0")/env.sh"
if docker info >/dev/null 2>&1; then echo "Docker daemon already reachable"; exit 0; fi
command -v colima >/dev/null || { echo "Install a Docker runtime first: brew install colima docker docker-compose"; exit 1; }
colima start "$COLIMA_PROFILE" --cpu "${COLIMA_CPU:-4}" --memory "${COLIMA_MEMORY:-4}" --disk "${COLIMA_DISK:-30}" \
  --vm-type vz --mount-type virtiofs --mount "$PROJECT_ROOT:w"
source "$(dirname "$0")/env.sh"
docker info --format 'Docker {{.ServerVersion}} on {{.Architecture}}, {{.NCPU}} CPUs, {{.MemTotal}} bytes RAM'
